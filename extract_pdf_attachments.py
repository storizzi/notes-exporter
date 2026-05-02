import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

from notes_export_utils import get_tracker


NOTES_DATA_DIR = Path.home() / "Library" / "Group Containers" / "group.com.apple.notes"
NOTE_DB_NAME = "NoteStore.sqlite"
START_MARKER = "<!-- notes-exporter-pdf-attachments:start -->"
END_MARKER = "<!-- notes-exporter-pdf-attachments:end -->"


@dataclass
class PdfAttachment:
    note_id: str
    source_path: Path
    original_name: str
    creation_time: Optional[float] = None
    modification_time: Optional[float] = None


def _notes_data_dir() -> Path:
    return Path(os.getenv("NOTES_EXPORT_NOTES_DATA_DIR", NOTES_DATA_DIR)).expanduser()


def _copy_database(notes_dir: Path) -> Path:
    source_db = notes_dir / NOTE_DB_NAME
    if not source_db.exists():
        raise FileNotFoundError(f"Apple Notes database not found: {source_db}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="notes-exporter-db-"))
    tmp_db = tmp_dir / NOTE_DB_NAME

    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{source_db}{suffix}")
        if source.exists():
            shutil.copy2(source, Path(f"{tmp_db}{suffix}"))

    return tmp_db


def _get_keys(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute("SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY").fetchall()
    return {name: ent for name, ent in rows}


def _get_account_paths(conn: sqlite3.Connection, keys: Dict[str, int], notes_dir: Path) -> List[Path]:
    account_key = keys.get("ICAccount")
    if not account_key:
        return []

    rows = conn.execute(
        """
        SELECT ZIDENTIFIER
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE Z_ENT = ? AND ZIDENTIFIER IS NOT NULL
        """,
        (account_key,),
    ).fetchall()

    return [notes_dir / "Accounts" / row["ZIDENTIFIER"] for row in rows if row["ZIDENTIFIER"]]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"].lower() == column.lower() for row in rows)


def _resolve_source(notes_dir: Path, account_paths: Iterable[Path], relative_path: Path) -> Optional[Path]:
    candidates = [account_path / relative_path for account_path in account_paths]
    candidates.append(notes_dir / relative_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _core_time_to_epoch(value) -> Optional[float]:
    if value in (None, "", 0):
        return None
    try:
        return float(value) + 978307200
    except (TypeError, ValueError):
        return None


def _find_media_pdfs(conn: sqlite3.Connection, keys: Dict[str, int], notes_dir: Path, account_paths: List[Path]) -> List[PdfAttachment]:
    media_key = keys.get("ICMedia")
    if not media_key:
        return []

    has_generation = _column_exists(conn, "ZICCLOUDSYNCINGOBJECT", "ZGENERATION1")
    generation_expr = "a.ZGENERATION1" if has_generation else "NULL"

    rows = conn.execute(
        f"""
        SELECT
            a.ZIDENTIFIER AS media_identifier,
            a.ZFILENAME AS filename,
            {generation_expr} AS generation,
            b.ZNOTE AS note_pk,
            b.ZCREATIONDATE AS created,
            b.ZMODIFICATIONDATE AS modified,
            a.ZTYPEUTI AS media_uti,
            b.ZTYPEUTI AS attachment_uti
        FROM ZICCLOUDSYNCINGOBJECT AS a
        JOIN ZICCLOUDSYNCINGOBJECT AS b ON b.ZMEDIA = a.Z_PK
        WHERE
            a.Z_ENT = ?
            AND b.ZNOTE IS NOT NULL
            AND (
                lower(coalesce(a.ZFILENAME, '')) LIKE '%.pdf'
                OR lower(coalesce(a.ZTYPEUTI, '')) IN ('public.pdf', 'com.adobe.pdf', 'application/pdf')
                OR lower(coalesce(b.ZTYPEUTI, '')) IN ('public.pdf', 'com.adobe.pdf', 'application/pdf')
            )
        """,
        (media_key,),
    ).fetchall()

    attachments: List[PdfAttachment] = []
    for row in rows:
        filename = row["filename"] or "Attachment.pdf"
        parts = ["Media", row["media_identifier"]]
        if row["generation"]:
            parts.append(row["generation"])
        parts.append(filename)

        source = _resolve_source(notes_dir, account_paths, Path(*parts))
        if not source:
            print(f"Warning: PDF source not found for note {row['note_pk']}: {Path(*parts)}")
            continue

        attachments.append(
            PdfAttachment(
                note_id=str(row["note_pk"]),
                source_path=source,
                original_name=filename,
                creation_time=_core_time_to_epoch(row["created"]),
                modification_time=_core_time_to_epoch(row["modified"]),
            )
        )

    return attachments


def _find_scan_pdfs(conn: sqlite3.Connection, keys: Dict[str, int], notes_dir: Path, account_paths: List[Path]) -> List[PdfAttachment]:
    attachment_key = keys.get("ICAttachment")
    if not attachment_key:
        return []

    has_generation = _column_exists(conn, "ZICCLOUDSYNCINGOBJECT", "ZFALLBACKPDFGENERATION")
    generation_expr = "ZFALLBACKPDFGENERATION" if has_generation else "NULL"

    rows = conn.execute(
        f"""
        SELECT
            ZIDENTIFIER AS identifier,
            {generation_expr} AS generation,
            ZNOTE AS note_pk,
            ZCREATIONDATE AS created,
            ZMODIFICATIONDATE AS modified
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE
            Z_ENT = ?
            AND ZNOTE IS NOT NULL
            AND ZTYPEUTI = 'com.apple.paper.doc.scan'
        """,
        (attachment_key,),
    ).fetchall()

    attachments: List[PdfAttachment] = []
    for row in rows:
        parts = ["FallbackPDFs", row["identifier"]]
        if row["generation"]:
            parts.append(row["generation"])
        parts.append("FallbackPDF.pdf")

        source = _resolve_source(notes_dir, account_paths, Path(*parts))
        if not source:
            continue

        attachments.append(
            PdfAttachment(
                note_id=str(row["note_pk"]),
                source_path=source,
                original_name="Scan.pdf",
                creation_time=_core_time_to_epoch(row["created"]),
                modification_time=_core_time_to_epoch(row["modified"]),
            )
        )

    return attachments


def _find_pdf_attachments(notes_dir: Path) -> List[PdfAttachment]:
    tmp_db = _copy_database(notes_dir)
    try:
        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            keys = _get_keys(conn)
            account_paths = _get_account_paths(conn, keys, notes_dir)
            return _find_media_pdfs(conn, keys, notes_dir, account_paths) + _find_scan_pdfs(
                conn, keys, notes_dir, account_paths
            )
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)


def _safe_filename(name: str) -> str:
    stem = Path(name).stem or "Attachment"
    suffix = Path(name).suffix.lower() or ".pdf"
    stem = re.sub(r"[/\\:|<>\"'?*_,.\t ]+", "-", stem)
    stem = re.sub(r"-+", "-", stem).strip("-") or "Attachment"
    if suffix != ".pdf":
        suffix = ".pdf"
    return f"{stem}{suffix}"


def _attachment_dir(md_file: Path) -> Path:
    return md_file.parent / "attachments"


def _write_attachment(attachment: PdfAttachment, md_file: Path, note_filename: str, index: int) -> str:
    attachments_dir = _attachment_dir(md_file)
    attachments_dir.mkdir(parents=True, exist_ok=True)

    safe_original = _safe_filename(attachment.original_name)
    target_name = f"{note_filename}-pdf-{index:03d}-{safe_original}"
    target = attachments_dir / target_name

    shutil.copy2(attachment.source_path, target)

    if attachment.creation_time or attachment.modification_time:
        os.utime(
            target,
            (
                attachment.modification_time or attachment.creation_time,
                attachment.modification_time or attachment.creation_time,
            ),
        )

    return target_name


def _replace_managed_block(content: str, links: List[str]) -> str:
    block = "\n".join([START_MARKER, "## Attachments", *links, END_MARKER])
    pattern = re.compile(
        rf"\n*{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n*",
        flags=re.DOTALL,
    )

    stripped = pattern.sub("\n", content).rstrip()
    if not links:
        return stripped + ("\n" if stripped else "")

    return f"{stripped}\n\n{block}\n"


def _append_links(md_file: Path, written_files: List[str]):
    content = md_file.read_text(encoding="utf-8")
    links = [
        f"- [{name}](./attachments/{quote(name)})"
        for name in written_files
    ]
    md_file.write_text(_replace_managed_block(content, links), encoding="utf-8")


def extract_pdf_attachments():
    tracker = get_tracker()
    notes_dir = _notes_data_dir()

    try:
        attachments = _find_pdf_attachments(notes_dir)
    except PermissionError as exc:
        print(f"Error: Cannot read Apple Notes data: {exc}")
        print("Grant Full Disk Access to Terminal/Codex, or set NOTES_EXPORT_NOTES_DATA_DIR to a readable copy of group.com.apple.notes.")
        return
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return
    except sqlite3.Error as exc:
        print(f"Error reading Apple Notes database: {exc}")
        return

    by_note: Dict[str, List[PdfAttachment]] = {}
    for attachment in attachments:
        by_note.setdefault(attachment.note_id, []).append(attachment)

    if not by_note:
        print("No PDF attachments found.")
        return

    exported_count = 0
    linked_count = 0

    for json_file in tracker.get_all_data_files():
        folder_name = json_file.stem
        notebook_data = tracker.load_notebook_data(json_file)

        for note_id, note_info in notebook_data.items():
            if "deletedDate" in note_info or note_id not in by_note:
                continue

            filename = note_info.get("filename", f"note-{note_id}")
            md_file = tracker.get_output_path("md", folder_name, filename, ".md")
            if not md_file.exists():
                print(f"Skipping PDF links for {filename}: Markdown file not found")
                continue

            written_files = []
            for index, attachment in enumerate(by_note[note_id], start=1):
                written_files.append(_write_attachment(attachment, md_file, filename, index))
                exported_count += 1

            _append_links(md_file, written_files)
            linked_count += 1
            print(f"Linked {len(written_files)} PDF attachment(s): {md_file}")

    print(f"Exported {exported_count} PDF attachment(s) into {linked_count} Markdown note(s).")


if __name__ == "__main__":
    extract_pdf_attachments()
