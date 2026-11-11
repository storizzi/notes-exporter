#!/usr/bin/env python3
"""Copy an existing flat export into the real Apple Notes folder tree.

Exports made with the default ``--subdir-format '&account-&folder'`` put one
directory per folder *name* (``md/iCloud-Recipes``), so nested folders are
flattened and same-named folders are merged. New exports can use
``--folder-hierarchy`` instead; this script rebuilds the tree for an export
you already have, as an additional copy (the original is never changed)::

    md/iCloud-Recipes   ->   by-folder/iCloud/Archief/Food/Recipes
                             by-folder/iCloud/Archief/Fun/Recipes

Each note's folder comes from the ``folderPath`` that 1.4.0+ records in
``data/*.json``. For records made by older versions, pass ``--query-notes``
to read the folder tree from Notes.app (read-only, two AppleScript queries;
macOS asks for automation permission the first time).

Usage:
    python3 reorganize_by_folder.py --export-root DIR [--format md] [--dest by-folder]
                                    [--query-notes] [--dry-run]

Based on the post-processor contributed by @rnoblecodes in issue #36.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tracker_io import tracker_files

SEP = "\t"
EXTENSIONS = {"md": ".md", "html": ".html", "raw": ".html", "text": ".txt",
              "pdf": ".pdf", "docx": ".docx", "epub": ".epub"}

FOLDERS_SCRIPT = """
set out to ""
tell application "Notes"
    repeat with acc in accounts
        set accName to name of acc
        repeat with f in folders of acc
            set parentId to ""
            try
                set parentId to id of container of f
            end try
            set out to out & (id of f) & tab & parentId & tab & (name of f) & tab & accName & linefeed
        end repeat
    end repeat
end tell
return out
"""

NOTES_SCRIPT = """
set out to ""
tell application "Notes"
    repeat with acc in accounts
        repeat with f in folders of acc
            set fid to id of f
            set noteIds to id of every note of f
            repeat with nid in noteIds
                set out to out & nid & tab & fid & linefeed
            end repeat
        end repeat
    end repeat
end tell
return out
"""


def sanitize(name: str) -> str:
    """Folder name -> safe, readable directory name."""
    name = (name or "Untitled").replace("/", "-").replace(":", "-").strip()
    return name or "Untitled"


def query_notes_tree() -> Dict[str, Tuple[str, List[str]]]:
    """{full note id: (account, [folder names root first])} read from Notes.app."""
    def osa(script):
        return subprocess.run(["osascript", "-e", script], capture_output=True,
                              text=True, check=True).stdout

    folders = {}
    for line in osa(FOLDERS_SCRIPT).splitlines():
        parts = line.split(SEP)
        if len(parts) >= 4:
            fid, parent, name, account = parts[0], parts[1], parts[2], parts[3]
            folders[fid] = (parent if "/ICFolder/" in parent else None, name, account)

    def path_of(fid):
        parts, seen = [], set()
        account = folders[fid][2]
        while fid in folders and fid not in seen:
            seen.add(fid)
            parent, name, _ = folders[fid]
            parts.append(name)
            fid = parent
        return account, list(reversed(parts))

    tree = {}
    for line in osa(NOTES_SCRIPT).splitlines():
        parts = line.split(SEP)
        if len(parts) >= 2 and parts[1] in folders:
            tree[parts[0]] = path_of(parts[1])
    return tree


def plan_copies(root: Path, fmt: str, dest: Path,
                tree: Optional[Dict[str, Tuple[str, List[str]]]] = None):
    """Return (copies [(src, dst, [attachment srcs])], unmapped [(tracker, name)])."""
    ext = EXTENSIONS[fmt]
    copies, unmapped, seen = [], [], set()
    for json_path in tracker_files(root / "data"):
        try:
            records = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for note_key, rec in records.items():
            if not isinstance(rec, dict) or "deletedDate" in rec:
                continue
            filename = rec.get("filename", "")
            subdir = rec.get("subdir") if isinstance(rec.get("subdir"), str) else json_path.stem
            account, folder_path = rec.get("account"), rec.get("folderPath")
            if not folder_path and tree is not None:
                found = tree.get(rec.get("fullNoteId", ""))
                if found:
                    account, folder_path = found
            if not folder_path or not filename:
                unmapped.append((json_path.stem, filename or note_key))
                continue
            src = root / fmt / subdir / f"{filename}{ext}"
            if not src.is_file():
                unmapped.append((json_path.stem, f"{filename}{ext} (file missing)"))
                continue
            dst_dir = dest / sanitize(account or "Notes") / Path(*[sanitize(p) for p in folder_path])
            dst = dst_dir / src.name
            if dst in seen:
                print(f"  warning: duplicate {dst}, skipped", file=sys.stderr)
                continue
            seen.add(dst)
            pattern = glob.escape(filename) + "-attachment-*"
            attachments = sorted(src.parent.glob("attachments/" + pattern)) + \
                sorted(p for p in src.parent.glob(pattern) if p.is_file())
            copies.append((src, dst, attachments))
    return copies, unmapped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--export-root", default=os.getenv("NOTES_EXPORT_ROOT_DIR"),
                    help="Export root containing data/ and the format folders")
    ap.add_argument("--format", default="md", choices=sorted(EXTENSIONS),
                    help="Which format folder to reorganise (default: md)")
    ap.add_argument("--dest", default="by-folder",
                    help="Destination (relative to the export root unless absolute)")
    ap.add_argument("--query-notes", action="store_true",
                    help="Read folders from Notes.app for records without folderPath")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, copy nothing")
    args = ap.parse_args(argv)

    if not args.export_root:
        ap.error("--export-root is required (or set NOTES_EXPORT_ROOT_DIR)")
    root = Path(args.export_root).expanduser().resolve()
    dest = Path(args.dest) if os.path.isabs(args.dest) else root / args.dest
    if not (root / "data").is_dir() or not (root / args.format).is_dir():
        print(f"error: {root} has no data/ or {args.format}/ folder", file=sys.stderr)
        return 1
    if dest.exists() and not args.dry_run:
        print(f"error: {dest} already exists; remove it or choose another --dest", file=sys.stderr)
        return 1

    tree = query_notes_tree() if args.query_notes else None
    copies, unmapped = plan_copies(root, args.format, dest, tree)
    attachment_count = 0
    for src, dst, attachments in copies:
        if args.dry_run:
            print(f"  {src.relative_to(root)} -> {dst.relative_to(dest)} (+{len(attachments)} attachments)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        for att in attachments:
            target_dir = dst.parent / ("attachments" if att.parent.name == "attachments" else "")
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(att, target_dir / att.name)
            attachment_count += 1
    verb = "Would copy" if args.dry_run else "Copied"
    print(f"{verb} {len(copies)} notes and {attachment_count} attachments to {dest}")
    if unmapped:
        print(f"{len(unmapped)} notes had no folder path (exported before 1.4.0? "
              f"try --query-notes, or re-export):")
        for tracker, name in unmapped[:20]:
            print(f"  {tracker}/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
