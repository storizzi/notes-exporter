#!/usr/bin/env python3
"""Stands in for /usr/bin/security in tests: a JSON file instead of the Keychain.

FAKE_SECURITY_STORE  the JSON file of {"account|service": {"password", "label"}}
FAKE_SECURITY_LOG    appended one JSON line per call: {"argv": [...], "stdin": "..."}
FAKE_SECURITY_FAIL   set: every command fails (as a locked Keychain would)
Understands `-i` with add-generic-password lines, and find-generic-password -a -s -w.
"""

import json
import os
import shlex
import sys


def opts(words, valued=("-a", "-s", "-l", "-w")):
    out, i = {}, 0
    while i < len(words):
        w = words[i]
        if w in valued:
            out[w] = words[i + 1]
            i += 2
        else:
            out[w] = True
            i += 1
    return out


def main():
    argv = sys.argv[1:]
    stdin = sys.stdin.read() if argv[:1] == ["-i"] else ""
    with open(os.environ["FAKE_SECURITY_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")
    if os.environ.get("FAKE_SECURITY_FAIL"):
        print("security: SecKeychainItemCreateFromContent: User interaction is not allowed.", file=sys.stderr)
        return 1
    path = os.environ["FAKE_SECURITY_STORE"]
    store = json.load(open(path)) if os.path.exists(path) else {}
    if argv[:1] == ["-i"]:
        for line in stdin.splitlines():
            words = shlex.split(line)
            if not words:
                continue
            if words[0] != "add-generic-password":
                print(f"unknown command {words[0]}", file=sys.stderr)
                return 1
            o = opts(words[1:])
            key = f"{o['-a']}|{o['-s']}"
            if key in store and "-U" not in o:
                print("security: The specified item already exists in the keychain.", file=sys.stderr)
                continue
            store[key] = {"password": o["-w"], "label": o.get("-l")}
        json.dump(store, open(path, "w"))
        return 0
    if argv[:1] == ["find-generic-password"]:
        o = opts(argv[1:], valued=("-a", "-s", "-l"))
        item = store.get(f"{o['-a']}|{o['-s']}")
        if not item:
            print("security: The specified item could not be found in the keychain.", file=sys.stderr)
            return 44
        print(item["password"] if o.get("-w") else f'"svce"<blob>="{o["-s"]}"')
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
