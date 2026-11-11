#!/usr/bin/env python3
"""Can this process send Apple Events to Notes, without asking the user?

Uses AEDeterminePermissionToAutomateTarget with askUserIfNeeded=false, so it
never shows the macOS "wants to control Notes" prompt.

With ``--ask`` it asks instead (askUserIfNeeded=true): macOS shows its
"wants to control Notes" dialog on this Mac and the call waits for the answer.
If Notes isn't running it is opened in the background (``open -g -j -b
com.apple.Notes``) and the question repeated for up to ``--wait`` seconds
(NOTES_PERMISSION_LAUNCH_WAIT_SECONDS, default 20). Only run --ask when
someone is at the Mac to click Allow. The answer applies to
the app responsible for this process (Terminal, iTerm, a launchd job, the
app that started the exporter...), which is the same one osascript runs as.

Prints one word and exits with:
    0 allowed       - automation of Notes is permitted
    3 prompt        - macOS would ask the user first
    3 denied        - the user (or a profile) refused it
    4 not-running   - Notes is not running, so macOS cannot tell yet
    5 unknown       - the check itself failed (not macOS, API missing)
"""

import argparse
import ctypes
import ctypes.util
import os
import subprocess
import sys
import time

NOTES_BUNDLE_ID = b"com.apple.Notes"

NO_ERR = 0
ERR_WOULD_REQUIRE_CONSENT = -1744
ERR_NOT_PERMITTED = -1743
PROC_NOT_FOUND = -600

RESULTS = {
    NO_ERR: ("allowed", 0),
    ERR_WOULD_REQUIRE_CONSENT: ("prompt", 3),
    ERR_NOT_PERMITTED: ("denied", 3),
    PROC_NOT_FOUND: ("not-running", 4),
}


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


class _AEDesc(ctypes.Structure):
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


def check(bundle_id: bytes = NOTES_BUNDLE_ID, ask: bool = False) -> int:
    """Return the OSStatus of the permission check (see RESULTS)."""
    path = ctypes.util.find_library("CoreServices")
    if not path:
        raise OSError("CoreServices not found (not macOS?)")
    cs = ctypes.CDLL(path)
    desc = _AEDesc()
    err = cs.AECreateDesc(_fourcc("bund"), bundle_id, len(bundle_id), ctypes.byref(desc))
    if err:
        raise OSError(f"AECreateDesc failed: {err}")
    try:
        fn = cs.AEDeterminePermissionToAutomateTarget
        fn.restype = ctypes.c_int32
        return fn(ctypes.byref(desc), _fourcc("****"), _fourcc("****"), ctypes.c_bool(ask))
    finally:
        cs.AEDisposeDesc(ctypes.byref(desc))


def describe(status: int):
    return RESULTS.get(status, (f"unknown({status})", 5))


def launch_notes() -> None:
    """Open Notes in the background, without bringing it forward."""
    opener = os.environ.get("NOTES_PERMISSION_OPEN", "/usr/bin/open")
    subprocess.run([opener, "-g", "-j", "-b", NOTES_BUNDLE_ID.decode()], capture_output=True, timeout=30,
                   stdin=subprocess.DEVNULL)


def ask(wait_seconds: float, poll_seconds: float, checker=check, launcher=launch_notes,
        clock=time.monotonic, sleep=time.sleep) -> int:
    """Ask (showing the macOS dialog if needed); open Notes first if it isn't running."""
    status = checker(ask=True)
    if status != PROC_NOT_FOUND:
        return status
    launcher()
    end = clock() + wait_seconds
    while clock() < end:
        sleep(poll_seconds)
        status = checker(ask=True)
        if status != PROC_NOT_FOUND:
            break
    return status


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check (or with --ask, request) permission to automate Notes")
    p.add_argument("--ask", action="store_true", help="let macOS show its dialog (someone must click Allow)")
    p.add_argument("--wait", type=float, default=float(os.environ.get("NOTES_PERMISSION_LAUNCH_WAIT_SECONDS") or 20),
                   help="with --ask: seconds to wait for Notes to start")
    p.add_argument("--poll", type=float, default=float(os.environ.get("NOTES_PERMISSION_POLL_SECONDS") or 0.5))
    args = p.parse_args(argv)
    try:
        status = ask(args.wait, args.poll) if args.ask else check()
        word, code = describe(status)
    except Exception as e:  # not macOS, or the API is unavailable
        print(f"unknown ({e})")
        return 5
    print(word)
    return code


if __name__ == "__main__":
    sys.exit(main())
