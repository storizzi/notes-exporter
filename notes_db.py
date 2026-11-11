#!/usr/bin/env python3
"""Read what AppleScript cannot see from the Notes database: #tags, pinned, checklists.

Apple Notes keeps #tags as inline attachments, so the HTML and plain text
AppleScript returns do not contain them (#16). They are in Notes' own
database, ``~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite``.

This module never opens the live database: it copies it (with its -wal and
-shm files) to a temporary folder and reads the copy. Reading that folder
needs **Full Disk Access** for the app that runs the export (System Settings
> Privacy & Security > Full Disk Access).

The schema is undocumented and differs between macOS versions, so columns
are found by name (ZTYPEUTI / ZTYPEUTI1, ZNOTE / ZNOTE1 ...). Anything it
cannot read is skipped; the export works without it.

Usage:
    notes_db.py tags [--root DIR] [--db PATH]   # write tags/pinned/checklist into data/*.json
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

import events
from export_layout import iter_trackers
from tracker_io import write_json_atomic

DEFAULT_DB = Path.home() / "Library" / "Group Containers" / "group.com.apple.notes" / "NoteStore.sqlite"
HASHTAG_UTI = "com.apple.notes.inlinetextattachment.hashtag"
TABLE = "ZICCLOUDSYNCINGOBJECT"
NOTE_ID_RE = re.compile(r"^x-coredata://([^/]+)/ICNote/p(\d+)$")


class NotesDbError(Exception):
    pass


@contextmanager
def database_copy(db_path: Path):
    """Yield a read-only connection to a temporary copy of the database."""
    try:
        present = db_path.exists()
    except PermissionError:
        present = False
    if not present:
        # On a Mac without Full Disk Access the folder is unreadable rather than missing
        try:
            os.listdir(db_path.parent)
        except PermissionError:
            raise NotesDbError("no access to the Notes database: give Full Disk Access to the app "
                               "running the export (System Settings > Privacy & Security)")
        except FileNotFoundError:
            pass
        raise NotesDbError(f"Notes database not found: {db_path}")
    tmp = Path(tempfile.mkdtemp(prefix="notes-exporter-db-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if src.exists():
                try:
                    shutil.copy2(src, tmp / (db_path.name + suffix))
                except PermissionError:
                    raise NotesDbError("no access to the Notes database: give Full Disk Access to "
                                       "the app running the export")
        conn = sqlite3.connect(str(tmp / db_path.name))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _columns(conn) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({TABLE})")]


def _entity(conn, name: str) -> Optional[int]:
    row = conn.execute("SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = ?", (name,)).fetchone()
    return row["Z_ENT"] if row else None


def store_uuid(conn) -> Optional[str]:
    try:
        row = conn.execute("SELECT Z_UUID FROM Z_METADATA").fetchone()
        return row["Z_UUID"] if row else None
    except sqlite3.Error:
        return None


def read_note_facts(conn) -> Dict[int, dict]:
    """{note primary key: {"tags": [...], "pinned": bool|None, "checklist": bool|None}}."""
    cols = set(_columns(conn))
    note_ent = _entity(conn, "ICNote")
    facts: Dict[int, dict] = {}

    # Pinned / checklist flags live on the note rows themselves
    flag_cols = [c for c in ("ZISPINNED", "ZHASCHECKLIST") if c in cols]
    if note_ent is not None and flag_cols:
        for row in conn.execute(f"SELECT Z_PK, {', '.join(flag_cols)} FROM {TABLE} WHERE Z_ENT = ?",
                                (note_ent,)):
            f = facts.setdefault(row["Z_PK"], {"tags": []})
            if "ZISPINNED" in flag_cols:
                f["pinned"] = bool(row["ZISPINNED"])
            if "ZHASCHECKLIST" in flag_cols:
                f["checklist"] = bool(row["ZHASCHECKLIST"])

    # Hashtags: inline attachment rows pointing at their note
    uti_cols = [c for c in sorted(cols) if re.fullmatch(r"ZTYPEUTI\d*", c)]
    note_cols = [c for c in sorted(cols) if re.fullmatch(r"ZNOTE\d*", c)]
    if uti_cols and note_cols and "ZALTTEXT" in cols:
        where = " OR ".join(f"{c} = ?" for c in uti_cols)
        deleted = " AND (ZMARKEDFORDELETION IS NULL OR ZMARKEDFORDELETION = 0)" \
            if "ZMARKEDFORDELETION" in cols else ""
        sql = (f"SELECT ZALTTEXT, {', '.join(note_cols)} FROM {TABLE} "
               f"WHERE ({where}){deleted}")
        for row in conn.execute(sql, [HASHTAG_UTI] * len(uti_cols)):
            note_pk = next((row[c] for c in note_cols if row[c] is not None), None)
            text = (row["ZALTTEXT"] or "").strip()
            if note_pk is None or not text:
                continue
            tag = text[1:] if text.startswith("#") else text
            tags = facts.setdefault(note_pk, {"tags": []})["tags"]
            if tag and tag not in tags:
                tags.append(tag)
    for f in facts.values():
        f["tags"].sort(key=str.lower)
    return facts


def apply_to_export(root: Path, facts: Dict[int, dict], uuid: Optional[str]) -> int:
    """Write tags / pinned / checklist into the tracking records. Returns records changed."""
    changed_total = 0
    for json_file, data in iter_trackers(root):
        changed = False
        for rec in data.values():
            m = NOTE_ID_RE.match(rec.get("fullNoteId", ""))
            if not m or "deletedDate" in rec:
                continue
            if uuid and m.group(1) != uuid:
                continue  # a note from another store
            f = facts.get(int(m.group(2)), {"tags": []})
            new = {"tags": f["tags"], "tagsSource": "database"}
            for key in ("pinned", "checklist"):
                if key in f:
                    new[key] = f[key]
            if any(rec.get(k) != v for k, v in new.items()):
                rec.update(new)
                changed = True
                changed_total += 1
        if changed:
            write_json_atomic(json_file, data)
    return changed_total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["tags"])
    ap.add_argument("--root", default=os.getenv("NOTES_EXPORT_ROOT_DIR",
                                                os.path.expanduser("~/Downloads/AppleNotesExport")))
    ap.add_argument("--db", default=os.getenv("NOTES_EXPORT_NOTES_DB", str(DEFAULT_DB)))
    args = ap.parse_args(argv)
    try:
        with database_copy(Path(args.db).expanduser()) as conn:
            facts = read_note_facts(conn)
            uuid = store_uuid(conn)
    except (NotesDbError, sqlite3.Error) as e:
        print(f"Tags not read: {e}")
        events.message("warning", f"tags not read: {e}", stage="tags")
        return 1
    changed = apply_to_export(Path(args.root).expanduser(), facts, uuid)
    tagged = sum(1 for f in facts.values() if f["tags"])
    print(f"Tags: {tagged} notes have tags in the Notes database; {changed} records updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
