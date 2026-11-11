"""Settings → Show in Finder: POST /api/admin/export-folder/open (a fake open, never the Finder)."""
import json

from fastapi.testclient import TestClient

from notes_service.app import create_app

from .conftest import PASSWORD, fake_permissions


def opened(tmp_path):
    log = tmp_path / "open.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_opens_the_saved_export_folder(service, export_root, tmp_path):
    client, _ = service
    assert client.post("/api/admin/export-folder/open").status_code == 404  # not made yet
    export_root.mkdir()
    r = client.post("/api/admin/export-folder/open")
    assert r.status_code == 200
    assert r.json() == {"opened": str(export_root.resolve()), "on_this_mac": True}
    assert opened(tmp_path) == [[str(export_root.resolve())]]


def test_admin_only(service, export_root, tmp_path):
    client, ctx = service
    export_root.mkdir()
    ctx.auth.create_user("reader1", PASSWORD, "reader")
    token = client.post("/api/auth/login", json={"username": "reader1", "password": PASSWORD}).json()["token"]
    r = client.post("/api/admin/export-folder/open", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and opened(tmp_path) == []


def test_says_so_when_asked_from_another_computer(make_config, export_root, tmp_path):
    config = make_config()
    app = create_app(config, fake_permissions(config))
    export_root.mkdir()
    with TestClient(app, client=("192.168.1.50", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        ctx.settings.update({"export_root": str(export_root)})
        token = client.post("/api/auth/login", json={"username": "root", "password": PASSWORD}).json()["token"]
        r = client.post("/api/admin/export-folder/open", headers={"Authorization": f"Bearer {token}"})
        assert r.json()["on_this_mac"] is False
        ctx.manager.shutdown()


def test_a_failing_open_is_readable(service, export_root, monkeypatch):
    client, _ = service
    export_root.mkdir()
    monkeypatch.setenv("FAKE_OPEN_EXIT", "1")
    r = client.post("/api/admin/export-folder/open")
    assert r.status_code == 500 and "couldn't open" in r.json()["detail"]
