#!/usr/bin/env python3
"""Stand-in for notes_write_helper.py in the service tests: never runs osascript.

State in $FAKE_WRITER_STATE (JSON): ``{"modified": {note id: iso}, "fail": null | code,
"calls": [request without the markdown, plus its length]}``. A write sets the note's
modified to ``$FAKE_WRITER_NOW`` (default 2026-02-01T09:00:00+00:00); a create returns
``x-coredata://TEST/ICNote/new1``, a backup ``x-coredata://TEST/ICNote/backup<n>`` (recorded in
``backups``), a delete records the id in ``deleted``. ``fail_op`` limits ``fail`` to one operation."""
import json
import os
import sys
from pathlib import Path


def main():
    path = Path(os.environ["FAKE_WRITER_STATE"])
    state = json.loads(path.read_text()) if path.exists() else {}
    req = json.loads(sys.stdin.read())
    call = {k: v for k, v in req.items() if k != "markdown"}
    if "markdown" in req:
        call["markdown_chars"] = len(req["markdown"])
    state.setdefault("calls", []).append(call)
    now = os.environ.get("FAKE_WRITER_NOW", "2026-02-01T09:00:00+00:00")
    modified = state.setdefault("modified", {})
    op = req.get("operation")
    if state.get("fail") and op != "modified" and state.get("fail_op") in (None, op):
        out = {"ok": False, "error": "fake failure", "code": state["fail"]}
    elif op == "modified":
        nid = req["note_id"]
        out = {"ok": True, "note_id": nid, "modified": modified.get(nid, "2026-01-02T10:00:00+00:00")}
    elif op == "update":
        modified[req["note_id"]] = now
        out = {"ok": True, "note_id": req["note_id"], "modified": now}
    elif op == "create":
        nid = "x-coredata://TEST/ICNote/new1"
        modified[nid] = now
        out = {"ok": True, "note_id": nid, "modified": now}
    elif op == "backup":
        backups = state.setdefault("backups", [])
        nid = f"x-coredata://TEST/ICNote/backup{len(backups) + 1}"
        backups.append({"of": req["note_id"], "id": nid, "folder": [req["backup_folder"], *req["folder_path"]],
                        "suffix": req["suffix"]})
        out = {"ok": True, "note_id": nid, "modified": now}
    elif op == "delete":
        state.setdefault("deleted", []).append(req["note_id"])
        out = {"ok": True, "note_id": req["note_id"], "modified": modified.get(req["note_id"], "")}
    else:
        out = {"ok": False, "error": "unknown", "code": "bad_request"}
    path.write_text(json.dumps(state))
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
