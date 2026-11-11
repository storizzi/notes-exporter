#!/usr/bin/env python3
"""Can this process send Apple Events to Notes, without asking the user?

Uses AEDeterminePermissionToAutomateTarget with askUserIfNeeded=false, so it
never shows the macOS "wants to control Notes" prompt. The answer applies to
the app responsible for this process (Terminal, iTerm, a launchd job, the
app that started the exporter...), which is the same one osascript runs as.

Prints one word and exits with:
    0 allowed       - automation of Notes is permitted
    3 prompt        - macOS would ask the user first
    3 denied        - the user (or a profile) refused it
    4 not-running   - Notes is not running, so macOS cannot tell yet
    5 unknown       - the check itself failed (not macOS, API missing)
"""

import ctypes
import ctypes.util
import sys

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


def check(bundle_id: bytes = NOTES_BUNDLE_ID) -> int:
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
        return fn(ctypes.byref(desc), _fourcc("****"), _fourcc("****"), ctypes.c_bool(False))
    finally:
        cs.AEDisposeDesc(ctypes.byref(desc))


def describe(status: int):
    return RESULTS.get(status, (f"unknown({status})", 5))


def main() -> int:
    try:
        word, code = describe(check())
    except Exception as e:  # not macOS, or the API is unavailable
        print(f"unknown ({e})")
        return 5
    print(word)
    return code


if __name__ == "__main__":
    sys.exit(main())
