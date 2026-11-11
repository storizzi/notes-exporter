#!/usr/bin/env python3
"""Write manifest.json: the machine-readable state of an export.

The schema is documented (and versioned) in INTEGRATION.md. In short::

    {"format": "notes-exporter.manifest", "version": 1,
     "run": {...}, "accounts": [...], "notes": [...],
     "deleted": [...], "skipped": [...]}

exportnotes.zsh runs this at the end of every run, including a failed or
partial one. The file is replaced atomically, so a reader never sees half a
manifest. The previous manifest is read to work out ``changed_this_run`` and
``previous_outputs``; a private cache (data/.manifest_cache.json) avoids
re-hashing unchanged files.

Usage:
    build_manifest.py --root DIR [--run-info FILE] [--live FILE] [--json]
"""

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

import events
from export_layout import FORMATS, attachment_files, iter_trackers, output_paths, rel
from tracker_io import read_json, read_live, write_json_atomic

FORMAT_NAME = "notes-exporter.manifest"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CACHE_NAME = ".manifest_cache.json"

TOOL_VERSION_FILE = Path(__file__).parent / "VERSION"

# Notes' hashtag rule (approximate): '#', then letters, digits, '_' or '-',
# not preceded by a word character, and not made of digits only.
HASHTAG_RE = re.compile(r"(?<![\w#&/])#([^\W_][\w-]*)", re.UNICODE)


def tool_version() -> str:
    try:
        return TOOL_VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ── hashing with a (size, mtime) cache ───────────────────────────────────

class HashCache:
    def __init__(self, path: Path):
        self.path = path
        self.old = read_json(path) if path.exists() else {}
        self.new: Dict[str, list] = {}

    def file_info(self, root: Path, path: Path) -> dict:
        st = path.stat()
        key = rel(root, path)
        cached = self.old.get(key)
        if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
            digest = cached[2]
        else:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        self.new[key] = [st.st_size, st.st_mtime_ns, digest]
        return {"path": key, "sha256": digest, "bytes": st.st_size}

    def save(self):
        write_json_atomic(self.path, self.new)


# ── per-note pieces ──────────────────────────────────────────────────────

def legacy_date_to_iso(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        from set_file_dates import parse_apple_date
        dt = parse_apple_date(value)
    except Exception:
        dt = None
    return dt.astimezone().isoformat() if dt else None


def kind_of(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or ""
    if media_type.startswith("image/") or path.suffix.lower() in (".heic", ".heif", ".webp"):
        return "image"
    if media_type == "application/pdf":
        return "pdf"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type.startswith("video/"):
        return "video"
    return "file"


def linked_local_files(html_path: Path, root: Path) -> List[Path]:
    """Local files referenced by <img src> / <a href> in an HTML output."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    except Exception:
        return []
    found = []
    for tag, attr in (("img", "src"), ("a", "href"), ("source", "src")):
        for el in soup.find_all(tag):
            ref = el.get(attr) or ""
            if not ref or ref.startswith(("data:", "#", "mailto:")) or urlparse(ref).scheme:
                continue
            target = (html_path.parent / unquote(ref.split("#")[0])).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                continue
            if target.is_file() and target not in found:
                found.append(target)
    return found


def tags_for(rec: dict, text_path: Path) -> (List[str], Optional[str]):
    if isinstance(rec.get("tags"), list):
        return rec["tags"], rec.get("tagsSource", "database")
    if text_path.is_file():
        try:
            text = text_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], None
        tags = []
        for match in HASHTAG_RE.finditer(text):
            tag = match.group(1).rstrip("-")
            if tag and not tag.isdigit() and tag not in tags:
                tags.append(tag)
        return tags, "text"
    return [], None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


# ── manifest ─────────────────────────────────────────────────────────────

def build(root: Path, run_info: dict, live_path: Optional[Path] = None) -> dict:
    root = root.resolve()
    previous = read_json(root / MANIFEST_NAME) if (root / MANIFEST_NAME).exists() else {}
    if previous.get("format") != FORMAT_NAME:
        previous = {}
    prev_notes = {n["id"]: n for n in previous.get("notes", []) if n.get("id")}
    prev_deleted = {d["id"]: d for d in previous.get("deleted", []) if d.get("id")}
    sequence = int(previous.get("run", {}).get("sequence", 0) or 0) + 1

    cache = HashCache(root / "data" / CACHE_NAME)
    accounts: Dict[str, str] = {}
    active: Dict[str, dict] = {}
    gone: Dict[str, dict] = {}

    for json_file, data in iter_trackers(root):
        tracker = json_file.stem
        for note_id, rec in data.items():
            if not isinstance(rec, dict):
                continue
            full_id = rec.get("fullNoteId") or f"legacy:{tracker}/{note_id}"
            if rec.get("accountId"):
                accounts[rec["accountId"]] = rec.get("account", "")
            if "deletedDate" in rec:
                if rec.get("movedTo"):
                    continue  # lives on elsewhere; its old files were tidied
                gone.setdefault(full_id, (tracker, note_id, rec))
                continue
            current = active.get(full_id)
            if current and (current[2].get("lastExported", "") >= rec.get("lastExported", "")):
                continue
            active[full_id] = (tracker, note_id, rec)

    notes = []
    for full_id, (tracker, note_id, rec) in sorted(active.items()):
        paths = output_paths(root, tracker, rec)
        outputs = {fmt: cache.file_info(root, p) for fmt, p in paths.items() if p.is_file()}
        attachments = []
        html = paths.get("html")
        linked = linked_local_files(html, root) if html and html.is_file() else []
        for att in linked or attachment_files(root, tracker, rec):
            info = cache.file_info(root, att)
            attachments.append({
                "id": f"{note_id}:{att.name}",
                "name": att.name,
                "kind": kind_of(att),
                "media_type": mimetypes.guess_type(att.name)[0],
                **info,
            })
        tags, tags_source = tags_for(rec, paths.get("text", Path("/nonexistent")))
        entry = {
            "id": full_id,
            "short_id": note_id,
            "account_id": rec.get("accountId"),
            "account": rec.get("account"),
            "folder_id": rec.get("folderId"),
            "folder_path": rec.get("folderPath") or [],
            "title": rec.get("title") or rec.get("filename", "").replace("-", " "),
            "created": rec.get("createdAt") or legacy_date_to_iso(rec.get("created", "")),
            "modified": rec.get("modifiedAt") or legacy_date_to_iso(rec.get("modified", "")),
            "tags": tags,
            "tags_source": tags_source,
            "locked": bool(rec.get("locked", False)),
            "shared": bool(rec.get("shared", False)),
            "pinned": bool_or_none(rec.get("pinned")),
            "checklist": bool_or_none(rec.get("checklist")),
            "filename": rec.get("filename"),
            "tracker": tracker,
            "outputs": outputs,
            "attachments": attachments,
            "last_exported": rec.get("lastExported"),
        }
        prev = prev_notes.get(full_id)
        previous_outputs = {}
        if prev:
            for fmt, out in prev.get("outputs", {}).items():
                if fmt in outputs and out.get("path") != outputs[fmt]["path"]:
                    previous_outputs[fmt] = out.get("path")
        entry["previous_outputs"] = previous_outputs
        fingerprint = _fingerprint(entry)
        changed = prev is None or prev.get("fingerprint") != fingerprint
        entry["changed_this_run"] = changed
        entry["changed_in_run"] = sequence if changed else prev.get("changed_in_run", sequence)
        entry["fingerprint"] = fingerprint
        notes.append(entry)

    deleted = []
    for full_id, (tracker, note_id, rec) in sorted(gone.items()):
        if full_id in active:
            continue
        remaining = [rel(root, p) for p in output_paths(root, tracker, rec).values() if p.is_file()]
        remaining += [rel(root, p) for p in attachment_files(root, tracker, rec)]
        was = prev_deleted.get(full_id)
        deleted.append({
            "id": full_id,
            "short_id": note_id,
            "account_id": rec.get("accountId"),
            "folder_path": rec.get("folderPath") or [],
            "title": rec.get("title") or rec.get("filename", "").replace("-", " "),
            "deleted_at": rec.get("deletedAt") or legacy_date_to_iso(rec.get("deletedDate", "")),
            "removed_outputs": rec.get("prunedOutputs", []),
            "remaining_outputs": remaining,
            "deleted_this_run": was is None or was.get("removed_outputs") != rec.get("prunedOutputs", []),
        })

    skipped = []
    if live_path and live_path.exists():
        index = read_live(live_path)
        for (tracker, note_id), row in sorted(index.notes.items()):
            if row.get("locked") == "1":
                skipped.append({"id": row.get("fullNoteId"), "short_id": note_id,
                                "reason": "locked", "title": row.get("title"),
                                "message": "password-protected notes cannot be read by AppleScript"})
        for err in index.errors:
            skipped.append({"id": err.get("fullNoteId"), "short_id": err.get("noteId"),
                            "reason": "error", "message": err.get("message")})

    cache.save()
    run = dict(run_info)
    run.setdefault("id", str(uuid.uuid4()))
    run.setdefault("finished_at", now_iso())
    run.setdefault("tool_version", tool_version())
    run["root_dir"] = str(root)
    run["sequence"] = sequence
    run["counts"] = {
        "notes": len(notes),
        "changed": sum(1 for n in notes if n["changed_this_run"]),
        "deleted": len(deleted),
        "deleted_this_run": sum(1 for d in deleted if d["deleted_this_run"]),
        "skipped": len(skipped),
    }
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "run": run,
        "accounts": [{"id": k, "name": v} for k, v in sorted(accounts.items())],
        "notes": notes,
        "deleted": deleted,
        "skipped": skipped,
    }


def _fingerprint(entry: dict) -> str:
    keyed = {k: entry[k] for k in ("title", "folder_path", "account_id", "modified",
                                   "tags", "locked", "shared")}
    keyed["outputs"] = {f: (o["path"], o["sha256"]) for f, o in sorted(entry["outputs"].items())}
    keyed["attachments"] = sorted((a["path"], a["sha256"]) for a in entry["attachments"])
    return hashlib.sha256(json.dumps(keyed, sort_keys=True).encode()).hexdigest()[:16]


def write(root: Path, manifest: dict) -> Path:
    path = root / MANIFEST_NAME
    write_json_atomic(path, manifest)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.getenv("NOTES_EXPORT_ROOT_DIR",
                                                os.path.expanduser("~/Downloads/AppleNotesExport")))
    ap.add_argument("--run-info", help="JSON file with the run fields (id, started_at, mode, ...)")
    ap.add_argument("--live", help="live index of this run (data/.live_notes.tsv)")
    ap.add_argument("--json", action="store_true", help="print the run summary as JSON")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser()
    run_info = {}
    if args.run_info:
        with open(args.run_info, encoding="utf-8") as f:
            run_info = json.load(f)
    live = Path(args.live) if args.live else root / "data" / ".live_notes.tsv"
    manifest = build(root, run_info, live)
    path = write(root, manifest)
    events.emit("manifest", path=str(path), **manifest["run"]["counts"])
    if args.json:
        print(json.dumps({"manifest": str(path), **manifest["run"]["counts"]}))
    else:
        c = manifest["run"]["counts"]
        print(f"Manifest: {path} ({c['notes']} notes, {c['changed']} changed, "
              f"{c['deleted']} deleted, {c['skipped']} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
