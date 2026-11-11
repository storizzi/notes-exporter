"""A small fake export (manifest v1, HTML, Markdown, an attachment) for service tests.

Nothing here comes from Apple Notes: the notes are made up.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8   # 2 KiB of predictable bytes

NOTE_FILES = {
    "x-coredata://TEST/ICNote/p1": {
        "title": "Scones", "folder_path": ["Food", "Baking"], "filename": "Scones-p1",
        "files": {"html": ("html/iCloud-Baking/Scones-p1.html",
                           '<html><body><h1>Scones</h1><img src="attachments/Scones-p1-attachment-001.png"></body></html>'),
                  "md": ("md/iCloud-Baking/Scones-p1.md", "# Scones\n\n![](attachments/Scones-p1-attachment-001.png)\n")},
        "attachments": [("html/iCloud-Baking/attachments/Scones-p1-attachment-001.png", PNG)],
    },
    "x-coredata://TEST/ICNote/p2": {
        "title": "My Note (draft)", "folder_path": ["Notes"], "filename": "My-Note-draft-p2",
        "files": {"html": ("html/iCloud-Notes/My Note (draft)-p2.html", "<html><body><p>Draft café</p></body></html>")},
        "attachments": [],
    },
    "x-coredata://TEST/ICNote/p3": {
        "title": "Shopping", "folder_path": ["Notes"], "filename": "Shopping-p3",
        "files": {"html": ("html/iCloud-Notes/Shopping-p3.html", "<html><body><p>Milk</p></body></html>")},
        "attachments": [],
    },
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_export(root: Path, status: str = "ok") -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    previous = {}
    mpath = root / "manifest.json"
    if mpath.exists():
        previous = json.loads(mpath.read_text())
    seq = int(previous.get("run", {}).get("sequence", 0)) + 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev_notes = {n["id"]: n for n in previous.get("notes", [])}
    notes = []
    for nid, spec in NOTE_FILES.items():
        outputs = {}
        for fmt, (rel, text) in spec["files"].items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            data = text.encode("utf-8")
            p.write_bytes(data)
            outputs[fmt] = {"path": rel, "sha256": _sha(data), "bytes": len(data)}
        atts = []
        for rel, data in spec["attachments"]:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            name = Path(rel).name
            atts.append({"id": f"{nid.rsplit('/', 1)[1]}:{name}", "name": name, "kind": "image",
                         "media_type": "image/png", "path": rel, "sha256": _sha(data), "bytes": len(data)})
        prev = prev_notes.get(nid)
        notes.append({
            "id": nid, "short_id": nid.rsplit("/", 1)[1], "account_id": "x-coredata://TEST/ICAccount/p1",
            "account": "iCloud", "folder_id": "F-" + "/".join(spec["folder_path"]),
            "folder_path": spec["folder_path"], "title": spec["title"],
            "created": "2026-01-01T10:00:00+00:00", "modified": "2026-01-02T10:00:00+00:00",
            "tags": [], "tags_source": None, "locked": False, "shared": False, "pinned": None, "checklist": None,
            "filename": spec["filename"], "tracker": "iCloud-Notes.json", "outputs": outputs,
            "previous_outputs": {}, "attachments": atts, "changed_this_run": prev is None,
            "changed_in_run": prev["changed_in_run"] if prev else seq, "fingerprint": "f" + nid[-1],
            "last_exported": now,
        })
    deleted = [{"id": "x-coredata://TEST/ICNote/p9", "short_id": "p9", "account_id": "x-coredata://TEST/ICAccount/p1",
                "folder_path": ["Notes"], "title": "Old", "deleted_at": "2026-01-03T10:00:00+00:00",
                "removed_outputs": [], "remaining_outputs": [], "deleted_this_run": seq == 1,
                "deleted_in_run": 1}]
    manifest = {
        "format": "notes-exporter.manifest", "version": 1,
        "run": {"id": "fake", "sequence": seq, "started_at": now, "finished_at": now, "mode": "incremental",
                "status": status, "exit_code": 0 if status == "ok" else 2, "tool_version": "test",
                "root_dir": str(root), "formats": ["raw", "text", "html", "md"],
                "counts": {"notes": len(notes), "changed": sum(n["changed_this_run"] for n in notes),
                           "deleted": 1, "deleted_this_run": int(seq == 1), "skipped": 0}},
        "accounts": [{"id": "x-coredata://TEST/ICAccount/p1", "name": "iCloud"}],
        "notes": notes, "deleted": deleted, "skipped": [],
    }
    tmp = root / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(mpath)
    return manifest
