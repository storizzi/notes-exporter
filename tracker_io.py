#!/usr/bin/env python3
"""Read and write the per-folder tracking JSON for export_notes.scpt.

export_notes.scpt used to build ``python3 -c "..."`` commands with note
titles and paths pasted into the source, so a title holding a back-tick,
quote or ``$`` broke the shell or the Python literal and the whole folder's
records were silently dropped (issue #33). Now the AppleScript writes the
data to a file with its own file I/O and calls this static script with
nothing but file paths as (quoted) arguments.

Data files are tab-separated, one record per line. Fields are escaped with
:func:`escape` (backslash, tab, newline, carriage return); list fields such
as a folder path are joined with the unit separator U+001F before escaping.

Sub-commands::

    tracker_io.py load JSON_PATH INCLUDE_DELETED
        Print one line per record: id, filename, modified key (local ISO
        time), legacy modified string, deleted flag.

    tracker_io.py save JSON_PATH TSV_PATH
        Merge the processed notes in TSV_PATH into JSON_PATH.

    tracker_io.py finalize DATA_DIR LIVE_TSV [--json]
        After a run: mark notes deleted or moved, restore notes that came
        back, refresh descriptive metadata, for every tracker the run saw.

All writes are atomic (temp file + rename).
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

UNIT_SEP = "\x1f"

# Fields written by this module; everything else in a record is preserved.
LIFECYCLE_FIELDS = ("deletedDate", "deletedAt", "movedTo", "prunedDate")


# ── escaping ──────────────────────────────────────────────────────────────

def escape(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\t", "\\t")
            .replace("\n", "\\n").replace("\r", "\\r"))


def unescape(value: str) -> str:
    out = []
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            nxt = value[i + 1]
            out.append({"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_line(line: str) -> List[str]:
    return [unescape(f) for f in line.rstrip("\r\n").split("\t")]


def split_list(value: str) -> List[str]:
    return [p for p in value.split(UNIT_SEP)] if value else []


# ── time helpers ──────────────────────────────────────────────────────────

def local_to_aware(local_iso: str) -> str:
    """'2026-03-05T07:08:09' (wall clock from AppleScript) -> aware ISO 8601.

    The offset is the one in force on that date in the Mac's time zone, so
    DST is handled.
    """
    if not local_iso:
        return ""
    try:
        dt = datetime.fromisoformat(local_iso)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def aware_to_local(aware_iso: str) -> str:
    """Inverse of :func:`local_to_aware` - the wall-clock key AppleScript compares."""
    if not aware_iso:
        return ""
    try:
        dt = datetime.fromisoformat(aware_iso)
    except ValueError:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def now_stamp() -> str:
    """Export stamp. Microseconds so two runs in one second still differ."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


# ── JSON file IO ──────────────────────────────────────────────────────────

def read_json(path: Path) -> Dict[str, dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Never silently replace a damaged tracker: keep a copy aside.
        backup = path.with_suffix(path.suffix + ".corrupt")
        try:
            os.replace(path, backup)
            print(f"Warning: {path} was unreadable ({e}); moved to {backup}", file=sys.stderr)
        except OSError:
            pass
        return {}


def write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── load ──────────────────────────────────────────────────────────────────

def load_lines(json_path: Path, include_deleted: bool) -> List[str]:
    data = read_json(json_path)
    lines = []
    for note_id, rec in data.items():
        deleted = "deletedDate" in rec
        if deleted and not include_deleted:
            continue
        fields = [
            note_id,
            rec.get("filename", ""),
            aware_to_local(rec.get("modifiedAt", "")),
            rec.get("modified", ""),
            "1" if deleted else "0",
        ]
        lines.append("\t".join(escape(str(f)) for f in fields))
    return lines


# ── save ──────────────────────────────────────────────────────────────────

# Column order of the TSV written by export_notes.scpt saveNotebookData.
SAVE_COLUMNS = ("noteId", "fullNoteId", "filename", "title", "createdLocal",
                "modifiedLocal", "created", "modified", "account", "accountId",
                "folderId", "folderPath", "subdir")


def parse_save_line(line: str) -> Optional[dict]:
    parts = split_line(line)
    if len(parts) < 8 or not parts[0]:
        return None
    parts += [""] * (len(SAVE_COLUMNS) - len(parts))
    return dict(zip(SAVE_COLUMNS, parts))


def apply_note_metadata(rec: dict, row: dict) -> None:
    """Descriptive fields shared by save and finalize (never the dates)."""
    for key in ("fullNoteId", "title", "account", "accountId", "folderId", "subdir"):
        if row.get(key) or key == "subdir" and key in row:
            rec[key] = row[key]
    if row.get("folderPath"):
        rec["folderPath"] = split_list(row["folderPath"])


def merge_saved(data: Dict[str, dict], rows: List[dict], stamp: str) -> Dict[str, dict]:
    for row in rows:
        note_id = row["noteId"]
        rec = dict(data.get(note_id, {}))
        rec["filename"] = row["filename"]
        rec["created"] = row["created"]
        rec["modified"] = row["modified"]
        if row.get("createdLocal"):
            rec["createdAt"] = local_to_aware(row["createdLocal"])
        if row.get("modifiedLocal"):
            rec["modifiedAt"] = local_to_aware(row["modifiedLocal"])
        apply_note_metadata(rec, row)
        rec.setdefault("firstExported", stamp)
        rec["lastExported"] = stamp
        rec["exportCount"] = int(rec.get("exportCount", 0) or 0) + 1
        for key in LIFECYCLE_FIELDS:
            rec.pop(key, None)
        data[note_id] = rec
    return data


def save(json_path: Path, tsv_path: Path) -> int:
    with open(tsv_path, "r", encoding="utf-8") as f:
        rows = [r for r in (parse_save_line(l) for l in f if l.strip()) if r]
    data = read_json(json_path)
    merge_saved(data, rows, now_stamp())
    write_json_atomic(json_path, data)
    return len(rows)


# ── finalize ──────────────────────────────────────────────────────────────

LIVE_NOTE_COLUMNS = ("tracker", "noteId", "fullNoteId", "title", "createdLocal",
                     "modifiedLocal", "account", "accountId", "folderId",
                     "folderPath", "subdir", "locked", "shared")


class LiveIndex:
    """The live index written by export_notes.scpt for one run."""

    def __init__(self):
        self.folders: Dict[str, dict] = {}
        self.notes: Dict[Tuple[str, str], dict] = {}
        self.errors: List[dict] = []
        self.complete = False


def read_live(path: Path) -> LiveIndex:
    folders, notes, complete, errors = _parse_live(path)
    index = LiveIndex()
    index.folders, index.notes, index.complete, index.errors = folders, notes, complete, errors
    return index


def parse_live(path: Path) -> Tuple[Dict[str, dict], Dict[Tuple[str, str], dict], bool]:
    """Return (folders by tracker, live notes by (tracker, noteId), complete)."""
    folders, notes, complete, _ = _parse_live(path)
    return folders, notes, complete


def _parse_live(path: Path):
    folders: Dict[str, dict] = {}
    notes: Dict[Tuple[str, str], dict] = {}
    errors: List[dict] = []
    complete = False
    if not path.exists():
        return folders, notes, complete, errors
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            parts = split_line(line)
            kind, rest = parts[0], parts[1:]
            if kind == "N" and len(rest) >= 3:
                rest += [""] * (len(LIVE_NOTE_COLUMNS) - len(rest))
                row = dict(zip(LIVE_NOTE_COLUMNS, rest))
                notes[(row["tracker"], row["noteId"])] = row
            elif kind == "F" and len(rest) >= 2:
                folders.setdefault(rest[0], {"folderIds": set()})["folderIds"].add(rest[1])
            elif kind == "E" and len(rest) >= 3:
                rest += [""] * 4
                errors.append({"tracker": rest[0], "noteId": rest[1],
                               "fullNoteId": rest[2], "message": rest[3]})
            elif kind == "END":
                complete = True
    return folders, notes, complete, errors


def finalize(data_dir: Path, live_path: Path) -> dict:
    folders, live, complete = parse_live(live_path)
    live_by_full: Dict[str, str] = {}
    for (tracker, _), row in live.items():
        if row.get("fullNoteId"):
            live_by_full[row["fullNoteId"]] = tracker

    stamp = now_stamp()
    summary = {"trackers": 0, "updated": 0, "deleted": 0, "moved": 0,
               "restored": 0, "complete": complete}

    for json_file in sorted(data_dir.glob("*.json")):
        tracker = json_file.stem
        data = read_json(json_file)
        if not data:
            continue
        changed = False
        enumerated = folders.get(tracker)
        for note_id, rec in data.items():
            before = json.dumps(rec, sort_keys=True)
            row = live.get((tracker, note_id))
            if row is not None:
                apply_note_metadata(rec, row)
                if not rec.get("createdAt") and row.get("createdLocal"):
                    rec["createdAt"] = local_to_aware(row["createdLocal"])
                rec["locked"] = row.get("locked") == "1"
                rec["shared"] = row.get("shared") == "1"
                if "deletedDate" in rec:
                    for key in ("deletedDate", "deletedAt", "movedTo"):
                        rec.pop(key, None)
                    summary["restored"] += 1
            elif "deletedDate" not in rec:
                full_id = rec.get("fullNoteId", "")
                moved_to = live_by_full.get(full_id) if full_id else None
                if moved_to and moved_to != tracker:
                    rec["deletedDate"] = stamp
                    rec["deletedAt"] = stamp
                    rec["movedTo"] = moved_to
                    summary["moved"] += 1
                elif (complete and enumerated is not None
                      and (not rec.get("folderId")
                           or rec["folderId"] in enumerated["folderIds"])):
                    rec["deletedDate"] = stamp
                    rec["deletedAt"] = stamp
                    summary["deleted"] += 1
            if json.dumps(rec, sort_keys=True) != before:
                changed = True
                summary["updated"] += 1
        if changed:
            write_json_atomic(json_file, data)
            summary["trackers"] += 1
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    try:
        if cmd == "load" and len(argv) >= 4:
            for line in load_lines(Path(argv[2]), argv[3].lower() in ("1", "true", "yes")):
                sys.stdout.write(line + "\n")
            return 0
        if cmd == "save" and len(argv) >= 4:
            count = save(Path(argv[2]), Path(argv[3]))
            print(f"saved {count} records")
            return 0
        if cmd == "finalize" and len(argv) >= 4:
            summary = finalize(Path(argv[2]), Path(argv[3]))
            if "--json" in argv:
                print(json.dumps(summary))
            else:
                print("Tracking data: {updated} records updated, {deleted} deleted, "
                      "{moved} moved, {restored} restored".format(**summary))
                if not summary["complete"]:
                    print("Export did not finish; deletions were not recorded this run.")
            return 0
    except Exception as e:  # report and fail loudly; the caller logs it
        print(f"tracker_io {cmd} failed: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
