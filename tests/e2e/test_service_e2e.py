"""End to end: the real ``notes-exporter serve`` on a free port, driven over HTTP
with an API key.

Two exporters: tests/service/fake_exporter.py (writes the fixture export), and
the real exportnotes.zsh with tests/fake_osascript.py first on the exporter's
PATH (plus a fake ``open``), the permission check skipped. Nothing reaches
Apple Notes, launchd or the real export folder: HOME, the state directory and
the export root are all under tmp_path.
"""

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
FAKE_EXPORTER = REPO / "tests" / "service" / "fake_exporter.py"
PASSWORD = "correct horse battery"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Http:
    def __init__(self, base, key=None):
        self.base, self.key = base, key

    def call(self, method, path, body=None, headers=None):
        h = dict(headers or {})
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["content-type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()

    def json(self, method, path, body=None, expect=200):
        code, _, data = self.call(method, path, body)
        assert code == expect, (code, data)
        return json.loads(data) if data else None


def cli(env, *args, stdin=None):
    r = subprocess.run([str(REPO / "notes-exporter"), *args], env=env, input=stdin, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def server(tmp_path):
    procs = []

    def start(extra_env=None):
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        port = free_port()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
               "NOTES_SERVICE_PYTHON": sys.executable, "NOTES_SERVICE_HOME": str(tmp_path / "state"),
               "NOTES_SERVICE_PORT": str(port), "NOTES_SERVICE_BCRYPT_ROUNDS": "4",
               "NOTES_SERVICE_SCHEDULER": "false", "NOTES_SERVICE_PERMISSION_CHECK": "false",
               "NOTES_SERVICE_CANCEL_GRACE_SECONDS": "2"}
        env.update(extra_env or {})
        cli(env, "user", "add", "simon", "--admin", "--password-stdin", stdin=PASSWORD + "\n")
        out = cli(env, "apikey", "create", "--name", "e2e", "--scopes", "read,run,admin")
        key = out.strip().splitlines()[-1]
        log = open(tmp_path / "server.log", "w")
        proc = subprocess.Popen([str(REPO / "notes-exporter"), "serve", "--log-level", "warning"], env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
                assert proc.poll() is None, (tmp_path / "server.log").read_text()
        else:
            raise AssertionError("server did not start")
        return Http(base, key), env
    yield start
    for p in procs:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def wait_run(http, run_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        run = http.json("GET", f"/api/runs/{run_id}")
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_e2e_fake_exporter(server, tmp_path):
    http, env = server({"NOTES_SERVICE_EXPORTER": str(FAKE_EXPORTER),
                        "NOTES_SERVICE_EXPORTER_PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"})
    root = tmp_path / "export"
    health = Http(http.base).json("GET", "/api/health")
    assert health["api_version"] == 1 and health["service"] == "notes-exporter"
    assert Http(http.base).call("GET", "/api/status")[0] == 401
    assert http.call("GET", f"/api/status?apikey={http.key}")[0] == 400
    http.json("PUT", "/api/admin/settings", {"export_root": str(root), "formats": ["html", "md"]})
    assert http.call("GET", "/api/manifest")[0] == 404

    run = http.json("POST", "/api/runs", {"mode": "incremental"}, expect=202)["run"]
    code, _, body = http.call("POST", "/api/runs", {})
    assert code in (202, 409)
    done = wait_run(http, run["id"])
    assert done["status"] == "ok" and done["counts"]["notes"] == 3

    code, headers, raw = http.call("GET", "/api/manifest")
    assert code == 200 and headers["etag"] == '"' + hashlib.sha256(raw).hexdigest() + '"'
    assert http.call("GET", "/api/manifest", headers={"If-None-Match": headers["etag"]})[0] == 304
    manifest = json.loads(raw)
    notes = http.json("GET", "/api/notes")
    assert notes["sequence"] == manifest["run"]["sequence"] and len(notes["notes"]) == 3
    scones = next(n for n in notes["notes"] if n["title"] == "Scones")
    assert http.json("GET", "/api/notes/" + quote(scones["id"], safe=""))["id"] == scones["id"]
    att = scones["attachments"][0]
    code, h, data = http.call("GET", "/api/files/" + quote(att["path"]))
    assert code == 200 and hashlib.sha256(data).hexdigest() == att["sha256"]
    assert h["etag"] == f'"sha256:{att["sha256"]}"'
    code, h, part = http.call("GET", "/api/files/" + quote(att["path"]), headers={"Range": "bytes=10-19"})
    assert code == 206 and part == data[10:20]
    assert http.call("GET", "/api/files/..%2F..%2Fstate%2Fauth.sqlite")[0] == 403

    events = http.call("GET", f"/api/runs/{run['id']}/events")[2].decode().splitlines()
    assert json.loads(events[-1])["type"] == "result"

    runs = http.json("GET", "/api/runs?limit=5")
    assert runs["total"] >= 1 and runs["runs"][0]["id"] in (run["id"], json.loads(body).get("run", {}).get("id"))


def _fake_bin(tmp_path):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    osa = bin_dir / "osascript"
    osa.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{REPO / 'tests' / 'fake_osascript.py'}' \"$@\"\n")
    opener = bin_dir / "open"
    opener.write_text("#!/bin/sh\necho \"fake open $*\" >&2\nexit 0\n")
    for p in (osa, opener):
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return bin_dir


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("zsh"), reason="exportnotes.zsh needs macOS")
def test_e2e_real_exportnotes_with_fake_osascript(server, tmp_path):
    bin_dir = _fake_bin(tmp_path)
    exporter_path = f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin"
    # Safety: the exporter must find the fake osascript and open, never the real ones.
    assert shutil.which("osascript", path=exporter_path) == str(bin_dir / "osascript")
    assert shutil.which("open", path=exporter_path) == str(bin_dir / "open")
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"fail": None, "notes": [
        {"account": "iCloud", "folder": ["Food", "Baking"], "folder_id": "F1", "id": 1, "title": "Scones",
         "modified": "2026-03-05T07:08:09", "html": "<div><h1>Scones</h1><div>Flour</div></div>",
         "text": "Scones\nFlour"},
        {"account": "iCloud", "folder": ["Notes"], "folder_id": "F2", "id": 2, "title": "Shopping (list)",
         "modified": "2026-03-06T07:08:09", "html": "<div><h1>Shopping</h1><div>Milk</div></div>",
         "text": "Shopping\nMilk"},
    ]}))
    http, env = server({
        "NOTES_SERVICE_EXPORTER_PATH": exporter_path,
        "FAKE_NOTES_LIBRARY": str(library), "NOTES_EXPORT_SKIP_PERMISSION_CHECK": "true",
        "NOTES_SERVICE_PASS_ENV": "FAKE_NOTES_LIBRARY,NOTES_EXPORT_SKIP_PERMISSION_CHECK",
    })
    root = tmp_path / "export"
    http.json("PUT", "/api/admin/settings", {"export_root": str(root), "formats": ["html", "md"],
                                             "folder_hierarchy": True})
    run = http.json("POST", "/api/runs", {}, expect=202)["run"]
    done = wait_run(http, run["id"], timeout=120)
    log = http.call("GET", f"/api/runs/{run['id']}/log")[2].decode()
    assert done["status"] == "ok", (done, log)
    assert done["exit_code"] == 0 and done["counts"]["notes"] == 2 and done["manifest_sequence"] == 1
    assert done["formats"] == ["raw", "text", "html", "md"]
    notes = http.json("GET", "/api/notes")["notes"]
    assert sorted(n["title"] for n in notes) == ["Scones", "Shopping (list)"]
    scones = next(n for n in notes if n["title"] == "Scones")
    assert scones["folder_path"] == ["Food", "Baking"]
    md = scones["outputs"]["md"]
    code, h, data = http.call("GET", "/api/files/" + quote(md["path"]))
    assert code == 200 and hashlib.sha256(data).hexdigest() == md["sha256"]
    assert h["content-type"].startswith("text/markdown")
    # a second, incremental run changes nothing
    run2 = http.json("POST", "/api/runs", {}, expect=202)["run"]
    done2 = wait_run(http, run2["id"], timeout=120)
    assert done2["status"] == "ok" and done2["counts"]["changed"] == 0 and done2["manifest_sequence"] == 2
    assert http.json("GET", "/api/notes?changed_since_sequence=1")["notes"] == []
    # a client asks for EPUBs and folder books for one run
    run3 = http.json("POST", "/api/runs", {"formats": ["epub"], "epub_books": "folder", "mode": "full"}, expect=202)["run"]
    done3 = wait_run(http, run3["id"], timeout=120)
    assert done3["status"] == "ok", http.call("GET", f"/api/runs/{run3['id']}/log")[2].decode()
    manifest = http.json("GET", "/api/manifest")
    epub = next(n for n in manifest["notes"] if n["title"] == "Scones")["outputs"]["epub"]
    code, h, data = http.call("GET", "/api/files/" + quote(epub["path"]))
    assert code == 200 and h["content-type"] == "application/epub+zip" and data[30:38] == b"mimetype"
    assert hashlib.sha256(data).hexdigest() == epub["sha256"]
    assert {"/".join(b["folder_path"]) for b in manifest["books"]} == {"Food/Baking", "Notes"}
    book = manifest["books"][0]
    assert http.call("GET", "/api/files/" + quote(book["path"]))[0] == 200


def test_e2e_cancel_and_busy(server, tmp_path):
    http, _ = server({"NOTES_SERVICE_EXPORTER": str(FAKE_EXPORTER),
                      "NOTES_SERVICE_EXPORTER_PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
                      "FAKE_EXPORTER_MODE": "slow", "NOTES_SERVICE_PASS_ENV": "FAKE_EXPORTER_MODE"})
    http.json("PUT", "/api/admin/settings", {"export_root": str(tmp_path / "export")})
    run = http.json("POST", "/api/runs", {}, expect=202)["run"]
    code, _, body = http.call("POST", "/api/runs", {})
    assert code == 409 and json.loads(body)["running_run_id"] == run["id"]
    time.sleep(0.5)
    events = http.call("GET", f"/api/runs/{run['id']}/events?after=0")
    assert events[1]["x-run-status"] == "running" and int(events[1]["x-next-after"]) > 0
    http.json("POST", f"/api/runs/{run['id']}/cancel")
    done = wait_run(http, run["id"], timeout=20)
    assert done["status"] == "cancelled"
    assert http.json("GET", "/api/status")["running_run_id"] is None
