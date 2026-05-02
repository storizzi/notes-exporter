import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from notes_export_utils import get_tracker


NOTE_FILE_EXTENSIONS = {".md", ".html", ".txt"}


def _copy_if_exists(source: Path, target: Path) -> Optional[str]:
    if not source.exists() or not source.is_file():
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.name


def _output_path(root: Path, export_type: str, notebook: str, filename: str, extension: str) -> Path:
    if os.getenv("NOTES_EXPORT_USE_SUBDIRS", "true").lower() == "true":
        return root / export_type / notebook / f"{filename}{extension}"
    return root / export_type / f"{filename}{extension}"


def _markdown_path(root: Path, notebook: str, filename: str) -> Path:
    candidates = []
    if os.getenv("NOTES_EXPORT_USE_SUBDIRS", "true").lower() == "true":
        candidates.extend(
            [
                root / "md" / notebook / filename / f"{filename}.md",
                root / "md" / notebook / f"{filename}.md",
            ]
        )
    else:
        candidates.extend(
            [
                root / "md" / filename / f"{filename}.md",
                root / "md" / f"{filename}.md",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _note_folder(root: Path, notebook: str, filename: str) -> Path:
    if os.getenv("NOTES_EXPORT_NOTE_FOLDERS", "false").lower() == "true":
        return _markdown_path(root, notebook, filename).parent
    return _markdown_path(root, notebook, filename).parent


def _iter_attachment_files(note_folder: Path, filename: str) -> Iterable[Path]:
    if not note_folder.exists():
        return []

    files: List[Path] = []
    for candidate in note_folder.iterdir():
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in NOTE_FILE_EXTENSIONS:
            continue
        if candidate.name.startswith(f"{filename}-attachment-") or candidate.name.startswith(f"{filename}-pdf-"):
            files.append(candidate)
    return sorted(files)


def _note_metadata(note_id: str, notebook: str, note_info: Dict[str, Any], files: Dict[str, Any]) -> Dict[str, Any]:
    filename = note_info.get("filename", f"note-{note_id}")
    metadata = {
        "noteId": note_id,
        "fullNoteId": note_info.get("fullNoteId"),
        "notebook": notebook,
        "filename": filename,
        "created": note_info.get("created"),
        "modified": note_info.get("modified"),
        "firstExported": note_info.get("firstExported"),
        "lastExported": note_info.get("lastExported"),
        "exportCount": note_info.get("exportCount"),
        "deletedDate": note_info.get("deletedDate"),
        "files": files,
    }
    return {key: value for key, value in metadata.items() if value not in (None, {}, [])}


def consolidate_export():
    tracker = get_tracker()
    root = Path(tracker.root_directory)
    consolidated_dir = os.getenv("NOTES_EXPORT_CONSOLIDATED_DIR", "")
    consolidated_root = Path(consolidated_dir).expanduser() if consolidated_dir else root / "notes"

    if consolidated_root.exists():
        shutil.rmtree(consolidated_root)
    consolidated_root.mkdir(parents=True, exist_ok=True)

    index = {
        "root": str(consolidated_root),
        "sourceRoot": str(root),
        "notes": [],
    }

    note_count = 0
    attachment_count = 0

    for json_file in tracker.get_all_data_files():
        notebook = tracker.notebook_name_from_data_file(json_file)
        notebook_data = tracker.load_notebook_data(json_file)

        for note_id, note_info in sorted(notebook_data.items(), key=lambda item: item[1].get("filename", "")):
            if "deletedDate" in note_info and os.getenv("NOTES_EXPORT_INCLUDE_DELETED", "false").lower() != "true":
                continue

            filename = note_info.get("filename", f"note-{note_id}")
            target_dir = consolidated_root / notebook / filename
            files: Dict[str, Any] = {}

            md_file = _markdown_path(root, notebook, filename)
            md_copied = _copy_if_exists(md_file, target_dir / f"{filename}.md")
            if md_copied:
                files["markdown"] = md_copied

            html_file = _output_path(root, "html", notebook, filename, ".html")
            html_copied = _copy_if_exists(html_file, target_dir / f"{filename}.html")
            if html_copied:
                files["html"] = html_copied

            raw_file = _output_path(root, "raw", notebook, filename, ".html")
            raw_copied = _copy_if_exists(raw_file, target_dir / f"{filename}.raw.html")
            if raw_copied:
                files["rawHtml"] = raw_copied

            text_file = _output_path(root, "text", notebook, filename, ".txt")
            text_copied = _copy_if_exists(text_file, target_dir / f"{filename}.txt")
            if text_copied:
                files["text"] = text_copied

            converted_pdf = _output_path(root, "pdf", notebook, filename, ".pdf")
            pdf_copied = _copy_if_exists(converted_pdf, target_dir / f"{filename}.export.pdf")
            if pdf_copied:
                files["exportPdf"] = pdf_copied

            converted_docx = _output_path(root, "docx", notebook, filename, ".docx")
            docx_copied = _copy_if_exists(converted_docx, target_dir / f"{filename}.docx")
            if docx_copied:
                files["word"] = docx_copied

            attachments = []
            for attachment in _iter_attachment_files(_note_folder(root, notebook, filename), filename):
                copied = _copy_if_exists(attachment, target_dir / attachment.name)
                if copied:
                    attachments.append(copied)

            if attachments:
                files["attachments"] = attachments
                attachment_count += len(attachments)

            metadata = _note_metadata(note_id, notebook, note_info, files)
            (target_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            index["notes"].append(
                {
                    "noteId": note_id,
                    "notebook": notebook,
                    "filename": filename,
                    "path": str(target_dir.relative_to(consolidated_root)),
                    "fileCount": sum(1 if not isinstance(value, list) else len(value) for value in files.values()),
                    "attachmentCount": len(attachments),
                }
            )
            note_count += 1

    (consolidated_root / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Consolidated {note_count} note(s) into {consolidated_root}")
    print(f"Copied {attachment_count} attachment(s)")


if __name__ == "__main__":
    consolidate_export()
