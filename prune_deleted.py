#!/usr/bin/env python3
"""Remove exported files that no longer belong to a note in Apple Notes.

Two jobs, both only ever delete files this exporter wrote:

* ``--moved`` (always run by exportnotes.zsh): a note that moved to another
  folder is exported again in its new folder; the copy left in the old folder
  is removed, like a renamed note's old files already were.
* ``--deleted`` (``exportnotes.zsh --prune-deleted``, #26): the files of notes
  deleted from Apple Notes are removed. The tracking record stays, marked
  ``prunedDate`` with the removed paths, so the manifest can report them.

A Markdown file that was edited locally since it was exported (its hash no
longer matches ``markdownHash``) is kept, so local edits are never lost.

Usage:
    prune_deleted.py [--root DIR] [--moved] [--deleted] [--dry-run] [--json]
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import List

import events
from export_layout import attachment_files, iter_trackers, output_paths, rel
from tracker_io import now_stamp, write_json_atomic


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def locally_edited_markdown(path: Path, rec: dict) -> bool:
    baseline = rec.get("localFileHashAtLastSync") or rec.get("markdownHash")
    return bool(baseline) and path.exists() and file_sha256(path) != baseline


def _current_paths(root: Path) -> set:
    """Every output path of a live note (never delete one of these)."""
    keep = set()
    for json_file, data in iter_trackers(root):
        for rec in data.values():
            if "deletedDate" not in rec:
                keep.update(output_paths(root, json_file.stem, rec).values())
                keep.update(attachment_files(root, json_file.stem, rec))
    return keep


def prune(root: Path, moved: bool, deleted: bool, dry_run: bool = False) -> dict:
    summary = {"notes": 0, "files": 0, "kept_edited": 0, "removed": []}
    keep = _current_paths(root)
    stamp = now_stamp()
    for json_file, data in iter_trackers(root):
        changed = False
        for note_id, rec in data.items():
            if "deletedDate" not in rec or rec.get("prunedDate"):
                continue
            is_move = bool(rec.get("movedTo"))
            if not ((is_move and moved) or (not is_move and deleted)):
                continue
            removed: List[str] = []
            candidates = list(output_paths(root, json_file.stem, rec).items())
            candidates += [("attachment", p) for p in attachment_files(root, json_file.stem, rec)]
            for fmt, path in candidates:
                if path in keep or not path.is_file():
                    continue
                if fmt == "md" and locally_edited_markdown(path, rec):
                    summary["kept_edited"] += 1
                    print(f"  Kept locally edited {rel(root, path)}")
                    continue
                if not dry_run:
                    path.unlink()
                removed.append(rel(root, path))
            summary["notes"] += 1
            summary["files"] += len(removed)
            summary["removed"].extend(removed)
            if not dry_run:
                rec["prunedDate"] = stamp
                rec["prunedOutputs"] = removed
                changed = True
            for r in removed:
                print(f"  {'Would remove' if dry_run else 'Removed'} {r}")
        if changed:
            write_json_atomic(json_file, data)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.getenv("NOTES_EXPORT_ROOT_DIR",
                                                os.path.expanduser("~/Downloads/AppleNotesExport")))
    ap.add_argument("--moved", action="store_true", help="remove old copies of moved notes")
    ap.add_argument("--deleted", action="store_true", help="remove files of deleted notes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args(argv)
    if not (args.moved or args.deleted):
        ap.error("choose --moved and/or --deleted")
    summary = prune(Path(args.root).expanduser(), args.moved, args.deleted, args.dry_run)
    events.emit("stage", stage="prune", status="finished", notes=summary["notes"],
                files=summary["files"], kept_edited=summary["kept_edited"])
    if args.json:
        print(json.dumps(summary))
    elif summary["files"] or summary["kept_edited"]:
        print(f"Pruned {summary['files']} files of {summary['notes']} notes"
              + (f"; kept {summary['kept_edited']} locally edited" if summary["kept_edited"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
