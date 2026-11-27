"""1.7.0: whether the service can really write to the export folder (a probe file, never left behind),
machine-readable refusal reasons on the settings endpoints, and the last runs' ids in /api/status."""

import errno
import os
import sys
import time

import pytest

from notes_service import settings as settings_mod
from notes_service.settings import export_root_check, export_root_state

from .conftest import make_key

STATE_FIELDS = {"export_root_ok", "export_root_problem", "export_root_access", "export_root_reason"}


def _refuse_with(monkeypatch, code):
    monkeypatch.setattr(settings_mod, "_write_probe", lambda folder: PermissionError(code, os.strerror(code)))


def _wait_done(client, run_id, timeout=20):
    end = time.time() + timeout
    run = client.get(f"/api/runs/{run_id}").json()
    while run["status"] in ("queued", "running") and time.time() < end:
        time.sleep(0.1)
        run = client.get(f"/api/runs/{run_id}").json()
    return run


# ---- the probe ----
def test_probe_ok_leaves_nothing_behind(tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    assert export_root_check(str(root)) == {"access": "ok", "reason": None, "problem": None}
    assert list(root.iterdir()) == []
    state = export_root_state(str(root))
    assert state == {"export_root_ok": True, "export_root_problem": None, "export_root_access": "ok",
                     "export_root_reason": None}


def test_probe_before_the_first_export_checks_the_folder_above(tmp_path):
    root = tmp_path / "not" / "yet"
    state = export_root_state(str(root))
    # not there yet is no problem, only not ok (the first export makes it)
    assert state["export_root_access"] == "ok" and state["export_root_problem"] is None
    assert state["export_root_ok"] is False
    assert not (tmp_path / "not").exists() and [p.name for p in tmp_path.iterdir()] == ["home"]


def test_probe_denied_by_macos_names_full_disk_access(tmp_path, monkeypatch):
    _refuse_with(monkeypatch, errno.EPERM)
    check = export_root_check(str(tmp_path))
    assert check["access"] == "denied" and check["reason"] == "access_denied"
    assert "Full Disk Access" in check["problem"] and "Files and Folders" in check["problem"]
    assert os.path.realpath(sys.executable) in check["problem"]
    # EACCES where the permission bits allow writing is macOS too
    _refuse_with(monkeypatch, errno.EACCES)
    assert export_root_check(str(tmp_path))["access"] == "denied"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_probe_not_writable_by_permissions(tmp_path):
    root = tmp_path / "locked"
    root.mkdir()
    root.chmod(0o555)
    try:
        check = export_root_check(str(root))
    finally:
        root.chmod(0o755)
    assert check["access"] == "not_writable" and check["reason"] == "not_writable"
    assert "permissions" in check["problem"]


def test_probe_read_only_drive_missing_drive_and_a_file(tmp_path, monkeypatch):
    with pytest.MonkeyPatch.context() as mp:
        _refuse_with(mp, errno.EROFS)
        assert export_root_check(str(tmp_path))["reason"] == "not_writable"
        assert "read-only" in export_root_check(str(tmp_path))["problem"]
    monkeypatch.setattr(settings_mod, "_ismount", lambda p: False)
    check = export_root_check("/Volumes/FunHoardTestNoSuchDrive/AppleNotesExport")
    assert check["access"] == "missing" and check["reason"] == "drive_not_mounted"
    f = tmp_path / "file"
    f.write_text("x")
    assert export_root_check(str(f))["reason"] == "not_a_folder"
    assert export_root_check(str(f / "below"))["reason"] == "not_a_folder"


def test_probe_other_errors_are_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "_write_probe", lambda folder: OSError(errno.EIO, "I/O error"))
    check = export_root_check(str(tmp_path))
    assert check["access"] == "unknown" and check["reason"] == "probe_failed"


# ---- status and the settings endpoints ----
def test_status_reports_access(service, export_root, monkeypatch):
    client, ctx = service
    export_root.mkdir()
    st = client.get("/api/status").json()
    assert st["export_root_ok"] is True and st["export_root_access"] == "ok" and st["export_root_problem"] is None
    _refuse_with(monkeypatch, errno.EPERM)
    st = client.get("/api/status").json()
    assert st["export_root_ok"] is False and st["export_root_access"] == "denied"
    assert st["export_root_reason"] == "access_denied" and "Full Disk Access" in st["export_root_problem"]


def test_admin_settings_report_the_folder_and_take_it_back(service, export_root, monkeypatch):
    client, ctx = service
    export_root.mkdir()
    s = client.get("/api/admin/settings").json()
    assert STATE_FIELDS <= set(s) and s["export_root_ok"] is True and s["export_root_access"] == "ok"
    # sending the whole view back (state fields included) saves, and never stores them
    s["formats"] = ["md"]
    r = client.put("/api/admin/settings", json=s)
    assert r.status_code == 200, r.text
    assert r.json()["formats"] == ["md"] and STATE_FIELDS <= set(r.json())
    assert not STATE_FIELDS & set(ctx.settings.load().model_dump())
    _refuse_with(monkeypatch, errno.EPERM)
    s = client.get("/api/admin/settings").json()
    assert s["export_root_ok"] is False and "Full Disk Access" in s["export_root_problem"]


def test_client_settings_report_the_folder_beside_the_settings(service, export_root):
    client, ctx = service
    export_root.mkdir()
    h = {"Authorization": f"Bearer {make_key(ctx, ['read', 'settings'])}"}
    body = client.get("/api/settings", headers=h).json()
    assert STATE_FIELDS <= set(body) and body["export_root_ok"] is True
    assert not STATE_FIELDS & set(body["settings"])
    r = client.put("/api/settings", headers=h, json={"formats": ["md"]})
    assert r.status_code == 200 and STATE_FIELDS <= set(r.json())


# ---- refusal reasons ----
def test_refusal_reasons(service, tmp_path, monkeypatch):
    client, ctx = service

    def refused(body, reason, field="export_root"):
        r = client.put("/api/admin/settings", json=body)
        assert r.status_code == 422, (body, r.text)
        j = r.json()
        assert j["reason"] == reason and j["field"] == field and isinstance(j["detail"], str), j

    refused({"export_root": "relative/path"}, "not_absolute")
    refused({"export_root": str(ctx.config.home / "x")}, "inside_state_dir")
    refused({"nonsense": 1}, "unknown_settings", None)
    refused({"formats": ["rtf"]}, "invalid", "formats")
    f = tmp_path / "a-file"
    f.write_text("x")
    refused({"export_root": str(f)}, "not_a_folder")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings_mod, "_ismount", lambda p: False)
        refused({"export_root": "/Volumes/FunHoardTestNoSuchDrive/AppleNotesExport"}, "drive_not_mounted")
    assert not os.path.exists("/Volumes/FunHoardTestNoSuchDrive")
    with pytest.MonkeyPatch.context() as mp:
        _refuse_with(mp, errno.EPERM)
        refused({"export_root": str(tmp_path / "elsewhere")}, "access_denied")
        _refuse_with(mp, errno.EROFS)
        refused({"export_root": str(tmp_path / "elsewhere")}, "not_writable")
        # an unchanged root is never refused: other settings save while the folder is unwritable
        assert client.put("/api/admin/settings", json={"formats": ["md"]}).status_code == 200
    assert client.put("/api/admin/settings", json={"export_root": str(tmp_path / "elsewhere")}).status_code == 200


def test_not_admin_reasons(service, tmp_path):
    client, ctx = service
    settings_key = {"Authorization": f"Bearer {make_key(ctx, ['read', 'settings'])}"}
    r = client.put("/api/settings", headers=settings_key, json={"export_root": str(tmp_path / "other")})
    assert r.status_code == 403
    assert r.json()["reason"] == "not_admin" and r.json()["field"] == "export_root" and r.json()["detail"]
    r = client.put("/api/admin/settings", headers=settings_key, json={"formats": ["md"]})
    assert r.status_code == 403 and r.json()["reason"] == "not_admin" and r.json()["scope"] == "admin"
    read_key = {"Authorization": f"Bearer {make_key(ctx, ['read'])}"}
    r = client.post("/api/runs", headers=read_key, json={})
    assert r.status_code == 403 and r.json()["reason"] == "scope" and r.json()["scope"] == "run"
    # a settings + admin key may move it, and the client endpoint says why it can't
    both = {"Authorization": f"Bearer {make_key(ctx, ['read', 'settings', 'admin'])}"}
    r = client.put("/api/settings", headers=both, json={"export_root": "relative"})
    assert r.status_code == 422 and r.json()["reason"] == "not_absolute"


def test_a_run_into_a_refused_folder_fails_saying_why(service, export_root, monkeypatch):
    client, ctx = service
    export_root.mkdir()
    _refuse_with(monkeypatch, errno.EPERM)
    run = _wait_done(client, client.post("/api/runs", json={}).json()["run"]["id"])
    assert run["status"] == "failed" and "Full Disk Access" in run["message"]


# ---- the last runs in /api/status ----
def test_status_last_run_summary(service, export_root, monkeypatch):
    client, ctx = service
    st = client.get("/api/status").json()
    for prefix in ("last_run", "last_failed_run", "last_success_run"):
        assert all(st[f"{prefix}_{k}"] is None for k in ("id", "status", "finished_at", "message"))
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "ok")
    ok = _wait_done(client, client.post("/api/runs", json={}).json()["run"]["id"])
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "crash")
    failed = _wait_done(client, client.post("/api/runs", json={}).json()["run"]["id"])
    st = client.get("/api/status").json()
    assert st["last_run_id"] == failed["id"] == st["last_failed_run_id"] and st["last_run_status"] == "failed"
    assert st["last_failed_run_message"] == failed["message"] and st["last_failed_run_finished_at"]
    assert st["last_success_run_id"] == ok["id"] and st["last_success_run_status"] == "ok"
    monkeypatch.setenv("FAKE_EXPORTER_MODE", "partial")
    partial = _wait_done(client, client.post("/api/runs", json={}).json()["run"]["id"])
    st = client.get("/api/status").json()
    # the failure is no longer the latest run, but is still reported
    assert st["last_run_id"] == partial["id"] == st["last_success_run_id"]
    assert st["last_failed_run_id"] == failed["id"] != st["last_run_id"]
    assert st["last_run"]["id"] == partial["id"]
