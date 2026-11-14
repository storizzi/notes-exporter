"""Writing notes (writes.py): every fence, through the API, with a fake writer — nothing
here reaches Apple Notes (the writer is tests/service/fake_writer.py)."""

import json
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from notes_service.app import create_app

from .conftest import PASSWORD, fake_permissions, make_key
from .fixture_export import build_export

HERE = Path(__file__).resolve().parent
NOTE = "x-coredata://TEST/ICNote/p1"
URL = "/api/notes/" + quote(NOTE, safe="")


@pytest.fixture
def writer(tmp_path, monkeypatch):
    state = tmp_path / "writer.json"
    monkeypatch.setenv("FAKE_WRITER_STATE", str(state))
    return state


@pytest.fixture
def svc(make_config, export_root, writer):
    config = make_config(writer_helper=HERE / "fake_writer.py",
                         pass_env=["FAKE_EXPORTER_MODE", "FAKE_EXPORTER_SECONDS", "FAKE_WRITER_STATE"])
    app = create_app(config, fake_permissions(config))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        ctx.settings.update({"export_root": str(export_root)})
        build_export(export_root)
        key = make_key(ctx, ["read", "write"])
        client.headers["Authorization"] = f"Bearer {key}"
        yield client, ctx
        ctx.manager.shutdown()


def calls(writer):
    return json.loads(writer.read_text()).get("calls", []) if writer.exists() else []


def allow(ctx):
    ctx.settings.update({"allow_writes": True})


def body(**kw):
    return {"markdown": "# Scones\n\nMore butter.\n", "base_modified": "2026-01-02T10:00:00+00:00",
            "export": False, **kw}


def test_writes_are_off_until_allowed(svc, writer):
    client, ctx = svc
    r = client.put(URL, json=body())
    assert r.status_code == 403 and r.json()["reason"] == "off"
    assert calls(writer) == []
    assert client.get("/api/writes").json() == {"allowed": False, "busy": False, "running_run_id": None,
                                                "can_write": True}


def test_write_needs_the_write_scope(svc, writer):
    client, ctx = svc
    allow(ctx)
    other = make_key(ctx, ["read", "run", "settings"])
    r = client.put(URL, json=body(), headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 403 and calls(writer) == []


def test_a_settings_key_cant_turn_writing_on(svc):
    client, ctx = svc
    key = make_key(ctx, ["read", "settings"])
    r = client.put("/api/settings", json={"allow_writes": True}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403
    assert ctx.settings.load().allow_writes is False
    got = client.get("/api/settings", headers={"Authorization": f"Bearer {key}"}).json()
    assert "allow_writes" in got["read_only"]


def test_update_checks_notes_then_writes_and_logs_no_text(svc, writer, make_config):
    client, ctx = svc
    allow(ctx)
    r = client.put(URL, json=body(title="Scones"))
    assert r.status_code == 200, r.text
    assert r.json()["modified"] == "2026-02-01T09:00:00+00:00" and r.json()["run"] is None
    ops = [c["operation"] for c in calls(writer)]
    assert ops == ["modified", "update"]
    update = calls(writer)[1]
    assert update["note_id"] == NOTE and update["markdown_chars"] > 0
    assert update["base_dir"].endswith("md/iCloud-Baking") and update["root"]
    log = (ctx.config.home / "writes.ndjson").read_text()
    assert "butter" not in log and json.loads(log.splitlines()[-1])["ok"] is True


def test_an_export_that_moved_on_is_a_conflict(svc, writer):
    client, ctx = svc
    allow(ctx)
    r = client.put(URL, json=body(base_modified="2025-12-01T10:00:00+00:00"))
    assert r.status_code == 409 and r.json()["reason"] == "export"
    assert calls(writer) == []


def test_a_change_in_notes_since_the_export_is_a_conflict_unless_forced(svc, writer):
    client, ctx = svc
    allow(ctx)
    writer.write_text(json.dumps({"modified": {NOTE: "2026-01-05T08:00:00+00:00"}}))
    r = client.put(URL, json=body())
    assert r.status_code == 409 and r.json()["reason"] == "notes"
    assert r.json()["notes_modified"] == "2026-01-05T08:00:00+00:00"
    assert [c["operation"] for c in calls(writer)] == ["modified"]
    r = client.put(URL, json=body(force=True))
    assert r.status_code == 200
    assert [c["operation"] for c in calls(writer)][-1] == "update"


def test_same_instant_in_another_offset_is_no_conflict(svc, writer):
    client, ctx = svc
    allow(ctx)
    writer.write_text(json.dumps({"modified": {NOTE: "2026-01-02T11:00:00+01:00"}}))
    assert client.put(URL, json=body(base_modified="2026-01-02T10:00:00Z")).status_code == 200


def _edit_manifest(root, **changes):
    path = root / "manifest.json"
    data = json.loads(path.read_text())
    for n in data["notes"]:
        if n["id"] == NOTE:
            n.update(changes)
    path.write_text(json.dumps(data))


def test_losses_are_refused_until_accepted(svc, writer, export_root):
    client, ctx = svc
    allow(ctx)
    _edit_manifest(export_root, checklist=True, attachments=[
        {"name": "plan.pdf", "kind": "document", "path": "html/x/plan.pdf"}])
    r = client.put(URL, json=body())
    assert r.status_code == 409 and r.json()["reason"] == "losses"
    assert any("plan.pdf" in x for x in r.json()["losses"]) and any("checklist" in x for x in r.json()["losses"])
    assert calls(writer) == []
    assert client.put(URL, json=body(accept_losses=True)).status_code == 200


def test_locked_and_deleted_notes_are_never_written(svc, writer, export_root):
    client, ctx = svc
    allow(ctx)
    _edit_manifest(export_root, locked=True)
    r = client.put(URL, json=body(force=True, accept_losses=True))
    assert r.status_code == 409 and r.json()["reason"] == "locked"
    gone = "/api/notes/" + quote("x-coredata://TEST/ICNote/p9", safe="")
    assert client.put(gone, json=body(force=True)).json()["reason"] == "deleted"
    assert client.put("/api/notes/nope", json=body()).status_code == 404
    assert calls(writer) == []


def test_no_write_while_an_export_runs(svc, writer, monkeypatch):
    client, ctx = svc
    allow(ctx)
    monkeypatch.setattr(type(ctx.manager), "running_run_id", property(lambda self: "r1"))
    r = client.put(URL, json=body())
    assert r.status_code == 409 and r.json()["reason"] == "running" and r.json()["running_run_id"] == "r1"


def test_notes_refusing_automation_is_explained(svc, writer):
    client, ctx = svc
    allow(ctx)
    writer.write_text(json.dumps({"fail": "permission"}))
    r = client.put(URL, json=body(force=True))
    assert r.status_code == 503 and "Automation" in r.json()["detail"]


def test_create_only_in_a_folder_the_export_knows(svc, writer):
    client, ctx = svc
    allow(ctx)
    new = {"account": "iCloud", "markdown": "# Pancakes\n", "export": False}
    r = client.post("/api/notes", json={**new, "folder_path": ["Nowhere"]})
    assert r.status_code == 404 and calls(writer) == []
    r = client.post("/api/notes", json={**new, "folder_path": ["Food"]})
    assert r.status_code == 201 and r.json()["note_id"] == "x-coredata://TEST/ICNote/new1"
    assert calls(writer)[-1]["folder_path"] == ["Food"]
    assert client.post("/api/notes", json={**new, "folder_path": ["Food"], "markdown": "  "}).status_code == 400


def test_a_write_exports_its_folder(svc, writer):
    client, ctx = svc
    allow(ctx)
    r = client.put(URL, json=body(export=True, formats=["md"]))
    assert r.status_code == 200
    run = r.json()["run"]
    assert run and run["folders"] == ["Food/Baking"] and run["accounts"] == ["iCloud"]
    assert "md" in run["formats"] and run["requested_by"] == "write"


def test_api_keys_can_carry_settings_and_write(svc):
    client, ctx = svc
    client.headers["Authorization"] = "Bearer " + make_key(ctx, ["read", "admin"])
    r = client.post("/api/admin/api-keys", json={"name": "fh", "scopes": ["read", "run", "settings", "write"]})
    assert r.status_code == 201 and r.json()["api_key"]["scopes"] == ["read", "run", "settings", "write"]
