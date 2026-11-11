#!/usr/bin/env python3
"""JSON Lines events for ``exportnotes.zsh --json-log`` (see INTEGRATION.md).

When exportnotes.zsh runs with --json-log it opens file descriptor 3 on the
event stream (stdout, or the --json-log FILE) and sets
``NOTES_EXPORT_EVENT_FD=3``; human-readable output goes to stderr (or stays
on stdout when events go to a file). Every pipeline step writes its events
through :func:`emit`, so callers read one ordered stream.

Each event is one JSON object per line with at least ``type`` and ``time``.

Command line::

    events.py emit TYPE key=value key:=<json> ...
    events.py relay          # filter osascript stderr: @@ lines -> events
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Optional

_last_progress = {}
PROGRESS_INTERVAL = 0.25  # seconds between progress events of one stage


def _target_fd() -> Optional[int]:
    value = os.getenv("NOTES_EXPORT_EVENT_FD", "")
    return int(value) if value.isdigit() else None


def enabled() -> bool:
    return _target_fd() is not None


def emit(event_type: str, **data: Any) -> None:
    fd = _target_fd()
    if fd is None:
        return
    record = {"type": event_type,
              "time": datetime.now().astimezone().isoformat(timespec="seconds")}
    record.update(data)
    line = (json.dumps(record, default=str, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        os.write(fd, line)
    except OSError:
        pass


def progress(stage: str, done: int, total: int, force: bool = False, **extra: Any) -> None:
    """Throttled progress event; the first and last of a stage always go out."""
    now = time.monotonic()
    last = _last_progress.get(stage)
    if not force and last is not None and done < total and now - last < PROGRESS_INTERVAL:
        return
    _last_progress[stage] = now
    emit("progress", stage=stage, done=done, total=total, **extra)


def message(level: str, text: str, **extra: Any) -> None:
    emit("message", level=level, message=text, **extra)


# ── relay of the AppleScript's stderr ───────────────────────────────────

def _unescape(value: str) -> str:
    from tracker_io import unescape
    return unescape(value)


def relay(stream=sys.stdin, human=sys.stderr) -> int:
    """Turn the AppleScript's @@ lines into events; pass other lines through.

    Returns 0, or 3 when the output shows Notes refused automation (-1743).
    """
    total_folders = 0
    exported = 0
    refused = False
    for raw_line in stream:
        line = raw_line.rstrip("\n")
        if "-1743" in line or "Not authorized to send Apple events" in line:
            refused = True
        if not line.startswith("@@"):
            human.write(raw_line)
            continue
        parts = line.split("\t")
        tag = parts[0]
        if tag == "@@PLAN" and len(parts) >= 2:
            total_folders = int(parts[1] or 0)
            emit("plan", stage="export", folders=total_folders)
            progress("export", 0, total_folders, force=True, unit="folders")
            human.write(f"Folders to export: {total_folders}\n")
        elif tag == "@@FOLDER" and len(parts) >= 6:
            index, total = int(parts[1]), int(parts[2])
            account, path, notes = _unescape(parts[3]), _unescape(parts[4]), int(parts[5] or 0)
            progress("export", index - 1, total, force=True, unit="folders",
                     account=account, folder=path, notes_in_folder=notes,
                     notes_exported=exported)
            human.write(f"Folder {index}/{total}: {account} / {path} ({notes} notes)\n")
        elif tag == "@@NOTE" and len(parts) >= 2:
            exported = int(parts[1] or 0)
        elif tag == "@@NOTE_ERROR" and len(parts) >= 3:
            msg = _unescape(parts[2])
            emit("note_error", stage="export", note_id=parts[1], message=msg)
            human.write(f"  Error exporting note {parts[1]}: {msg}\n")
        elif tag == "@@SAVE_ERROR" and len(parts) >= 3:
            msg = _unescape(parts[2])
            emit("message", level="error", stage="export",
                 message=f"could not save tracking data for {_unescape(parts[1])}: {msg}")
            human.write(f"  Error saving tracking data for {_unescape(parts[1])}: {msg}\n")
        human.flush()
    if total_folders:
        progress("export", total_folders, total_folders, force=True, unit="folders",
                 notes_exported=exported)
    return 3 if refused else 0


def _parse_pairs(pairs):
    data = {}
    for pair in pairs:
        if ":=" in pair:
            key, value = pair.split(":=", 1)
            try:
                data[key] = json.loads(value)
            except json.JSONDecodeError:
                data[key] = value
        elif "=" in pair:
            key, value = pair.split("=", 1)
            data[key] = value
    return data


def main(argv) -> int:
    if len(argv) >= 3 and argv[1] == "emit":
        emit(argv[2], **_parse_pairs(argv[3:]))
        return 0
    if len(argv) >= 2 and argv[1] == "relay":
        return relay()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
