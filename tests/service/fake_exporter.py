#!/usr/bin/env python3
"""Stand-in for exportnotes.zsh in service tests: never touches Apple Notes.

Honours the parts of the contract the service relies on: ``--root-dir``,
``--json-log FILE`` (events appended), the exit codes, and a manifest.json in
the root. Behaviour comes from $FAKE_EXPORTER_MODE:

    ok (default) | partial | permission | locked | crash | slow | stubborn

``slow`` emits progress for $FAKE_EXPORTER_SECONDS (default 30) and handles
SIGTERM by exiting 130; ``stubborn`` ignores SIGTERM (so the service has to
SIGKILL it). Every invocation's argv and environment are appended to $FAKE_EXPORTER_ARGS_FILE.
"""

import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_export import build_export  # noqa: E402


def opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def main(argv):
    if os.environ.get("FAKE_EXPORTER_ARGS_FILE"):
        with open(os.environ["FAKE_EXPORTER_ARGS_FILE"], "a") as f:
            f.write(json.dumps({"argv": argv, "env": dict(os.environ)}) + "\n")
    mode = os.environ.get("FAKE_EXPORTER_MODE", "ok")
    root = Path(opt(argv, "--root-dir"))
    log = open(opt(argv, "--json-log"), "a")
    run_id = str(uuid.uuid4())

    def emit(t, **kw):
        log.write(json.dumps({"type": t, "time": datetime.now().astimezone().isoformat(timespec="seconds"), **kw}) + "\n")
        log.flush()

    print("fake exporter starting")
    emit("start", version="test", run_id=run_id, root_dir=str(root), mode="incremental",
         formats=["raw", "text", "html"], manifest_version=1)
    if mode == "permission":
        emit("permission", state="prompt")
        emit("result", status="failed", exit_code=3, run_id=run_id,
             message="macOS would ask for permission to control Notes")
        return 3
    emit("permission", state="allowed")
    if mode == "locked":
        return 4
    if mode == "crash":
        emit("message", level="error", message="AppleScript error: boom", stage="export")
        emit("result", status="failed", exit_code=5, run_id=run_id, message="export failed")
        return 5
    if mode in ("slow", "stubborn"):
        if mode == "slow":
            signal.signal(signal.SIGTERM, lambda *a: sys.exit(130))
        else:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        end = time.time() + float(os.environ.get("FAKE_EXPORTER_SECONDS", "30"))
        i = 0
        while time.time() < end:
            i += 1
            emit("progress", stage="export", done=i, total=1000, unit="notes")
            time.sleep(0.1)
    emit("plan", stage="export", folders=2)
    emit("progress", stage="export", done=3, total=3, unit="notes")
    manifest = build_export(root, status="partial" if mode == "partial" else "ok")
    c = manifest["run"]["counts"]
    emit("manifest", path=str(root / "manifest.json"), **c)
    code = 2 if mode == "partial" else 0
    emit("result", status="partial" if code else "ok", exit_code=code, run_id=run_id, manifest=str(root / "manifest.json"),
         elapsed_seconds=0.1)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
