#!/usr/bin/env python3
"""Stands in for notes_permission.py in tests: never touches Apple Events.

FAKE_PERMISSION_STATE   a file holding the current answer (default: "allowed")
FAKE_PERMISSION_GRANT   what --ask turns it into (default: "allowed")
FAKE_PERMISSION_LOG     appended one JSON line per call: {"argv": [...]}
FAKE_PERMISSION_SLEEP   seconds --ask takes (someone reading the dialog)
"""

import json
import os
import sys
import time


def main():
    args = sys.argv[1:]
    log = os.environ.get("FAKE_PERMISSION_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"argv": args}) + "\n")
    state_file = os.environ.get("FAKE_PERMISSION_STATE")
    state = "allowed"
    if state_file and os.path.exists(state_file):
        state = open(state_file).read().strip() or "allowed"
    if "--ask" in args:
        time.sleep(float(os.environ.get("FAKE_PERMISSION_SLEEP") or 0))
        state = os.environ.get("FAKE_PERMISSION_GRANT", "allowed")
        if state_file:
            with open(state_file, "w") as f:
                f.write(state)
    print(state)
    return 0 if state == "allowed" else 3


if __name__ == "__main__":
    sys.exit(main())
