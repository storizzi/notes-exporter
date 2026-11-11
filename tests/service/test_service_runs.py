"""Run lifecycle with the fake exporter: start, events, statuses, cancel, busy."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from notes_service.app import create_app
from notes_service.runs import RunStore, apply_event, read_events
from notes_service.settings import exporter_args, produced_formats

from .conftest import fake_permissions


def wait_done(client, run_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} still {run['status']}")


def calls(path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def argsfile(tmp_path, monkeypatch):
    p = tmp_path / "exporter-calls.ndjson"
    monkeypatch.setenv("FAKE_EXPORTER_ARGS_FILE", str(p))
    return p


def test_run_ok_lifecycle(service, export_root, argsfile, monkeypatch):
    client, ctx = service
    monkeypatch.setenv("SECRET_FROM_SHELL", "leak")
    monkeypatch.setenv("NOTES_EXPORT_SYNC", "true")  # must not reach the exporter
    r = client.post("/api/runs", json={})
    assert r.status_code == 202
    run = r.json()["run"]
    assert run["status"] in ("queued", "running") and run["trigger"] == "api"
    assert run["requested_by"] == "user:root"
    done = wait_done(client, run["id"])
    assert done["status"] == "ok" and done["exit_code"] == 0
    assert done["counts"]["notes"] == 3 and done["manifest_sequence"] == 1
    assert done["exporter_run_id"] and done["permission"] == "allowed"
    assert done["started_at"] and done["finished_at"]
    (call,) = calls(argsfile)
    argv, env = call["argv"], call["env"]
    assert "--non-interactive" in argv and argv[argv.index("--json-log") + 1].endswith(f"{run['id']}.ndjson")
    assert argv[argv.index("--root-dir") + 1] == str(export_root)
    assert argv[argv.index("--sync") + 1] == "false" and argv[argv.index("--sync-only") + 1] == "false"
    assert argv[argv.index("--exclude-folders") + 1] == "Recently Deleted"
    assert argv[argv.index("--update-all") + 1] == "false"
    assert "SECRET_FROM_SHELL" not in env and "NOTES_EXPORT_SYNC" not in env
    assert env["LANG"] == "en_US.UTF-8"
    # events and log
    ev = client.get(f"/api/runs/{run['id']}/events")
    assert ev.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(l) for l in ev.text.splitlines()]
    assert lines[0]["type"] == "start" and lines[-1]["type"] == "result"
    n = int(ev.headers["x-next-after"])
    assert n == len(lines) and ev.headers["x-run-status"] == "ok"
    later = client.get(f"/api/runs/{run['id']}/events?after=2")
    assert len(later.text.splitlines()) == n - 2
    assert client.get(f"/api/runs/{run['id']}/events?after={n}").text == ""
    assert "fake exporter starting" in client.get(f"/api/runs/{run['id']}/log").text
    # listing and status
    listing = client.get("/api/runs").json()
    assert listing["total"] == 1 and listing["runs"][0]["id"] == run["id"]
    status = client.get("/api/status").json()
    assert status["last_run"]["id"] == run["id"] and status["running_run_id"] is None
    assert client.get("/api/runs/nope").status_code == 404


def test_full_mode_and_filters(service, argsfile):
    client, _ = service
    run = client.post("/api/runs", json={"mode": "full", "folders": ["Food/Baking"], "accounts": ["iCloud"],
                                         "trigger": "cli"}).json()["run"]
    wait_done(client, run["id"])
    argv = calls(argsfile)[0]["argv"]
    assert argv[argv.index("--update-all") + 1] == "true"
    assert argv[argv.index("--filter-folders") + 1] == "Food/Baking"
    assert argv[argv.index("--filter-accounts") + 1] == "iCloud"
    assert client.get(f"/api/runs/{run['id']}").json()["trigger"] == "cli"
    assert client.post("/api/runs", json={"mode": "sometimes"}).status_code == 422
    assert client.post("/api/runs", json={"trigger": "schedule"}).status_code == 422


def test_bad_folder_names_refused(service):
    client, _ = service
    for bad in (["a,b"], ["-rf"], ["line\nbreak"]):
        r = client.post("/api/runs", json={"folders": bad})
        assert r.status_code == 400, bad
    assert client.get("/api/runs").json()["total"] == 0


def test_formats_union_recorded(service, argsfile):
    client, ctx = service
    ctx.settings.update({"formats": ["html", "md"]})
    run = client.post("/api/runs", json={"formats": ["pdf", "text"]}).json()["run"]
    assert run["formats"] == ["raw", "text", "html", "md", "pdf"]
    wait_done(client, run["id"])
    argv = calls(argsfile)[0]["argv"]
    assert argv[argv.index("--convert-pdf") + 1] == "true"
    assert argv[argv.index("--convert-markdown") + 1] == "true"
    assert argv[argv.index("--convert-word") + 1] == "false"
    assert argv[argv.index("--extract-images") + 1] == "true"
    # status still reports the settings' formats
    assert client.get("/api/status").json()["formats"] == ["html", "md"]


def test_unknown_run_format_is_422(service):
    client, _ = service
    assert client.post("/api/runs", json={"formats": ["rtf"]}).status_code == 422
    assert client.post("/api/runs", json={"formats": ["raw"]}).status_code == 422


def test_produced_formats_rules():
    assert produced_formats(["html"]) == ["raw", "text", "html"]
    assert produced_formats(["text"]) == ["raw", "text"]
    assert produced_formats(["text"], ["docx"]) == ["raw", "text", "html", "docx"]
    assert produced_formats(["html", "md"], ["md"]) == ["raw", "text", "html", "md"]


@pytest.mark.parametrize("mode,status,code,msg", [
    ("partial", "partial", 2, None),
    ("permission", "failed", 3, "macOS would ask"),
    ("locked", "failed", 4, "lock"),
    ("crash", "failed", 5, "export failed"),
])
def test_exit_codes_to_status(service, monkeypatch, mode, status, code, msg):
    client, _ = service
    monkeypatch.setenv("FAKE_EXPORTER_MODE", mode)
    run = client.post("/api/runs", json={}).json()["run"]
    done = wait_done(client, run["id"])
    assert done["status"] == status and done["exit_code"] == code
    if msg:
        assert msg in done["message"]


def test_busy_409_then_cancel(service, monkeypatch):
    client, ctx = service
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "slow")
    run = client.post("/api/runs", json={}).json()["run"]
    r = client.post("/api/runs", json={})
    assert r.status_code == 409 and r.json()["running_run_id"] == run["id"]
    assert client.get("/api/status").json()["running_run_id"] == run["id"]
    time.sleep(0.5)
    mid = client.get(f"/api/runs/{run['id']}").json()
    assert mid["status"] == "running" and mid["progress"].get("stage") == "export"
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    done = wait_done(client, run["id"], timeout=10)
    assert done["status"] == "cancelled"
    # a finished run can be "cancelled" again harmlessly, and a new run can start
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["run"]["status"] == "cancelled"
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "ok")
    assert client.post("/api/runs", json={}).status_code == 202


def test_cancel_escalates_to_sigkill(service, monkeypatch):
    client, ctx = service
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "stubborn")
    run = client.post("/api/runs", json={}).json()["run"]
    time.sleep(0.4)
    t0 = time.time()
    client.post(f"/api/runs/{run['id']}/cancel")
    done = wait_done(client, run["id"], timeout=10)
    assert done["status"] == "cancelled" and done["exit_code"] == -9
    assert time.time() - t0 >= ctx.config.cancel_grace_seconds * 0.8


def test_scope_run_needed_to_cancel(service, monkeypatch):
    client, ctx = service
    from .conftest import make_key
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "slow")
    monkeypatch.setenv("FAKE_EXPORTER_SECONDS", "3")
    run = client.post("/api/runs", json={}).json()["run"]
    read = make_key(ctx, ["read"])
    r = client.post(f"/api/runs/{run['id']}/cancel", headers={"Authorization": f"Bearer {read}"})
    assert r.status_code == 403
    client.post(f"/api/runs/{run['id']}/cancel")
    wait_done(client, run["id"])


def test_missing_exporter_fails_cleanly(make_config, export_root, tmp_path):
    config = make_config(exporter=tmp_path / "nope.py")
    app = create_app(config, fake_permissions(config))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        ctx = app.state.ctx
        ctx.settings.update({"export_root": str(export_root)})
        run = ctx.manager.start(trigger="api")
        assert run["status"] == "failed" and "could not start" in run["message"]
        assert ctx.manager.running_run_id is None


def test_recover_marks_interrupted_runs(make_config):
    config = make_config()
    store = RunStore(config)
    run = store.create(trigger="api", mode="incremental", folders=[], accounts=[], formats=[], requested_by="x")
    store.update(run["id"], status="running")
    app = create_app(config, fake_permissions(config))
    with TestClient(app):
        r = store.get(run["id"])
        assert r["status"] == "failed" and "interrupted" in r["message"]


def test_prune_keeps_newest(make_config):
    config = make_config(runs_keep=2)
    store = RunStore(config)
    ids = []
    for _ in range(4):
        r = store.create(trigger="api", mode="incremental", folders=[], accounts=[], formats=[], requested_by="x")
        store.update(r["id"], status="ok")
        store.events_path(r["id"]).write_text("{}\n")
        ids.append(r["id"])
    assert store.prune(2) == 2
    runs, total = store.list()
    assert total == 2 and [r["id"] for r in runs] == ids[:1:-1]
    assert not store.events_path(ids[0]).exists()


def test_apply_event_and_read_events(tmp_path):
    state = {}
    for ev in [{"type": "start", "run_id": "R", "formats": ["raw"]}, {"type": "permission", "state": "allowed"},
               {"type": "progress", "stage": "export", "done": 1, "total": 2, "unit": "notes"},
               {"type": "manifest", "notes": 5, "changed": 1, "deleted": 0, "deleted_this_run": 0, "skipped": 0},
               {"type": "result", "status": "ok", "exit_code": 0}, {"type": "future-thing", "x": 1}]:
        apply_event(state, ev)
    assert state["exporter_run_id"] == "R" and state["counts"]["notes"] == 5
    assert state["progress"]["done"] == 1 and state["result"]["status"] == "ok"
    p = tmp_path / "e.ndjson"
    p.write_text('{"a":1}\n{"b":2}\n{"c":')  # last line still being written
    assert read_events(p) == ['{"a":1}', '{"b":2}']
    assert read_events(p, 1) == ['{"b":2}']


def test_settings_api(service, tmp_path):
    client, ctx = service
    s = client.get("/api/admin/settings").json()
    assert s["formats"] == ["html"] and s["exclude_folders"] == ["Recently Deleted"] and s["prune_deleted"] is True
    r = client.put("/api/admin/settings", json={"formats": ["md", "pdf"], "schedule": {"enabled": True, "daily_at": "00:13"}})
    assert r.status_code == 200 and r.json()["formats"] == ["md", "pdf"] and r.json()["schedule"]["daily_at"] == "00:13"
    assert client.get("/api/status").json()["next_run_at"]
    bad = [
        {"formats": ["rtf"]}, {"schedule": {"enabled": True, "daily_at": "25:00"}},
        {"schedule": {"enabled": True, "daily_at": None, "interval_minutes": 1}},
        {"export_root": "relative/path"}, {"export_root": str(ctx.config.home / "x")},
        {"export_root": str(ctx.config.home.parent)}, {"nonsense": 1}, {"image_quality": 0},
        {"exclude_folders": ["a,b"]},
    ]
    for body in bad:
        assert client.put("/api/admin/settings", json=body).status_code == 422, body
    assert client.put("/api/admin/settings", content=b"[1]", headers={"Content-Type": "application/json"}).status_code == 400
    on_disk = json.loads(ctx.config.settings_file.read_text())
    assert on_disk["formats"] == ["md", "pdf"]


def test_exporter_args_options(make_config, tmp_path):
    from notes_service.settings import Settings
    config = make_config()
    s = Settings(export_root=str(tmp_path / "e"), folder_hierarchy=True, tags=True, image_format="jpeg",
                 image_format_from=["heic"], image_quality=80, exclude_folders=[])
    argv = exporter_args(config, s, json_log=tmp_path / "x.ndjson")
    assert "--folder-hierarchy" in argv and "--exclude-folders" not in argv
    assert argv[argv.index("--image-format") + 1] == "jpeg"
    assert argv[argv.index("--image-format-from") + 1] == "heic"
    assert argv[argv.index("--tags") + 1] == "true"
