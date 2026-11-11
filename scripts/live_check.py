#!/usr/bin/env python3
"""The opt-in ``live`` test: one real export through the running service.

This reads the real Apple Notes (through the service, which must already be
running and allowed to automate Notes), so it only runs with
NOTES_EXPORTER_LIVE=1, and it prints counts only — never a title, folder,
path or any other part of a note.

    NOTES_EXPORTER_LIVE=1                 required
    NOTES_EXPORTER_LIVE_URL               default http://127.0.0.1:8790
    NOTES_EXPORTER_API_KEY                the key (scopes read,run; add admin to let it ask macOS)
    NOTES_EXPORTER_LIVE_ENV_FILE          else: an env file to read NOTES_EXPORTER_API_KEY from
                                          (only that line is read)
    NOTES_EXPORTER_LIVE_MODE              incremental (default) or full
    NOTES_EXPORTER_LIVE_TIMEOUT_SECONDS   how long the run may take (default 3600)
    NOTES_EXPORTER_LIVE_POLL_SECONDS      how often to follow it (default 2)

Steps: /api/health; the Notes permission (asked for, if the key has the admin
scope: macOS shows its dialog on the Mac); a run started with trigger "cli" and
followed to the end; the run ok or partial; the manifest's format and version;
every output and book downloaded and checked against its sha256 and size, and
every attachment checked to exist with its size.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

import httpx

KEY_VAR = "NOTES_EXPORTER_API_KEY"
_LINE = re.compile(r"^[ \t]*(?:export[ \t]+)?" + KEY_VAR + r"[ \t]*=[ \t]*(.*?)[ \t]*$")


class LiveCheckFailed(RuntimeError):
    pass


def load_key(env=os.environ) -> Optional[str]:
    key = env.get(KEY_VAR)
    if key:
        return key
    path = env.get("NOTES_EXPORTER_LIVE_ENV_FILE")
    if not path:
        return None
    for line in Path(path).expanduser().read_text().splitlines():
        m = _LINE.match(line)
        if m:
            value = m.group(1)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value or None
    return None


def _check(cond, message):
    if not cond:
        raise LiveCheckFailed(message)


def run_live_check(base: str, key: str, out: Callable[[str], None] = print, mode: str = "incremental",
                   timeout: float = 3600.0, poll: float = 2.0, client: Optional[httpx.Client] = None) -> dict:
    """Run the check; returns the counts. Raises LiveCheckFailed with a message holding no note data."""
    http = client or httpx.Client(base_url=base, headers={"Authorization": f"Bearer {key}"}, timeout=120)

    def get_json(path, **kw):
        r = http.get(path, **kw)
        _check(r.status_code == 200, f"GET {path.split('?')[0]} answered {r.status_code}")
        return r.json()

    health = http.get("/api/health")
    _check(health.status_code == 200, f"/api/health answered {health.status_code}")
    h = health.json()
    _check(h.get("service") == "notes-exporter" and h.get("api_version") == 1, "not a notes-exporter service (API 1)")
    out(f"service {h.get('version')} at {base}")

    me = get_json("/api/auth/me")
    scopes = set(me.get("scopes") or [])
    _check({"read", "run"} <= scopes, "the key needs the read and run scopes")

    status = get_json("/api/status")
    automation = (status.get("permission") or {}).get("automation")
    if automation not in ("allowed", "unchecked"):
        _check("admin" in scopes, f"Notes automation is {automation!r}. Allow it first: the web page's 'Ask macOS "
               "for access to Notes', `notes-exporter permission request`, or a key made with --scopes read,run,admin")
        out("macOS is asking on this Mac — click Allow")
        r = http.post("/api/admin/permission/request", timeout=600)
        _check(r.status_code == 200, f"the permission request answered {r.status_code}")
        automation = r.json().get("automation")
        _check(automation == "allowed", f"Notes automation is still {automation!r}")
    out(f"notes automation: {automation}")

    end = time.monotonic() + timeout
    while status.get("running_run_id"):
        out("a run is already going; waiting for it")
        _check(time.monotonic() < end, "the earlier run didn't finish in time")
        time.sleep(poll)
        status = get_json("/api/status")
    r = http.post("/api/runs", json={"mode": mode, "trigger": "cli"})
    _check(r.status_code == 202, f"starting the run answered {r.status_code}")
    run = r.json()["run"]
    out(f"run {run['id'][:8]} started ({mode})")

    after, last_stage = 0, None
    while True:
        r = http.get(f"/api/runs/{run['id']}/events", params={"after": after})
        _check(r.status_code == 200, f"the run's events answered {r.status_code}")
        after = int(r.headers.get("X-Next-After") or after)
        for line in r.text.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            stage = ev.get("stage")
            if ev.get("type") in ("stage", "progress") and stage and stage != last_stage:
                out(f"  stage {stage}")
                last_stage = stage
        state = r.headers.get("X-Run-Status")
        if state and state not in ("queued", "running"):
            break
        _check(time.monotonic() < end, "the run didn't finish in time")
        time.sleep(poll)
    run = get_json(f"/api/runs/{run['id']}")
    _check(run["status"] in ("ok", "partial"), f"the run ended {run['status']} (exit {run.get('exit_code')})")

    manifest = get_json("/api/manifest")
    _check(manifest.get("format") == "notes-exporter.manifest" and manifest.get("version") == 1,
           "the manifest isn't notes-exporter.manifest version 1")

    checked = {"outputs": 0, "attachments": 0, "books": 0}
    bad = {"outputs": 0, "attachments": 0, "books": 0}

    def fetch_ok(entry) -> bool:
        digest, size = hashlib.sha256(), 0
        with http.stream("GET", "/api/files/" + quote(entry["path"])) as resp:
            if resp.status_code != 200:
                return False
            for chunk in resp.iter_bytes():
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest() == entry.get("sha256") and size == entry.get("bytes")

    def exists_ok(entry) -> bool:
        resp = http.head("/api/files/" + quote(entry["path"]))
        return resp.status_code == 200 and int(resp.headers.get("content-length", -1)) == entry.get("bytes")

    for note in manifest.get("notes", []):
        for entry in (note.get("outputs") or {}).values():
            checked["outputs"] += 1
            bad["outputs"] += not fetch_ok(entry)
        for att in note.get("attachments") or []:
            checked["attachments"] += 1
            bad["attachments"] += not exists_ok(att)
    for book in manifest.get("books") or []:
        checked["books"] += 1
        bad["books"] += not fetch_ok(book)

    c = (manifest.get("run") or {}).get("counts") or {}
    counts = {"notes": c.get("notes", len(manifest.get("notes", []))), "changed": c.get("changed", 0),
              "deleted": c.get("deleted_this_run", 0), "skipped": c.get("skipped", 0),
              "books": len(manifest.get("books") or [])}
    out(f"run {run['status']}: notes {counts['notes']}, changed {counts['changed']}, deleted {counts['deleted']}, "
        f"skipped {counts['skipped']}, books {counts['books']}")
    out("checked: " + ", ".join(f"{checked[k]} {k} ({bad[k]} bad)" for k in checked))
    _check(not any(bad.values()), "some exported files don't match the manifest")
    return {**counts, "checked": checked, "status": run["status"]}


def main() -> int:
    if os.environ.get("NOTES_EXPORTER_LIVE") != "1":
        print("skipped: set NOTES_EXPORTER_LIVE=1 to export the real Notes through the running service")
        return 0
    base = os.environ.get("NOTES_EXPORTER_LIVE_URL") or "http://127.0.0.1:8790"
    try:
        key = load_key()
    except OSError as e:
        print(f"FAILED: couldn't read NOTES_EXPORTER_LIVE_ENV_FILE ({e.__class__.__name__})")
        return 1
    if not key:
        print(f"FAILED: no API key: set {KEY_VAR}, or NOTES_EXPORTER_LIVE_ENV_FILE to a file that sets it")
        return 1
    try:
        run_live_check(base.rstrip("/"), key, mode=os.environ.get("NOTES_EXPORTER_LIVE_MODE") or "incremental",
                       timeout=float(os.environ.get("NOTES_EXPORTER_LIVE_TIMEOUT_SECONDS") or 3600),
                       poll=float(os.environ.get("NOTES_EXPORTER_LIVE_POLL_SECONDS") or 2))
    except LiveCheckFailed as e:
        print(f"FAILED: {e}")
        return 1
    except httpx.ConnectError:
        print(f"FAILED: no service at {base} (notes-exporter serve, or notes-exporter service install)")
        return 1
    except httpx.HTTPError as e:
        print(f"FAILED: {e.__class__.__name__} talking to {base}")
        return 1
    print("live check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
