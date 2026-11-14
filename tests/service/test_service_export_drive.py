"""An export root on a drive that isn't connected: refused, never created on the internal disk."""

import os
import time

from notes_service import settings as settings_mod
from notes_service.settings import export_root_problem


def test_problem_rules(monkeypatch):
    monkeypatch.setattr(settings_mod, "_ismount", lambda p: p == "/Volumes/Storage")
    assert export_root_problem("/Volumes/Storage/AppleNotesExport") is None
    assert "Gone" in export_root_problem("/Volumes/Gone/AppleNotesExport")
    assert export_root_problem("/Users/x/Downloads/AppleNotesExport") is None
    assert export_root_problem("/Volumes") is None  # not a drive's folder


def test_run_refused_and_status_says_why(service, monkeypatch):
    client, ctx = service
    root = "/Volumes/FunHoardTestNoSuchDrive/AppleNotesExport"
    monkeypatch.setattr(settings_mod, "_ismount", lambda p: False)
    ctx.settings.update({"export_root": root})
    r = client.post("/api/runs", json={})
    run = r.json()["run"]
    end = time.time() + 10
    while run["status"] in ("queued", "running") and time.time() < end:
        time.sleep(0.1)
        run = client.get(f"/api/runs/{run['id']}").json()
    assert run["status"] == "failed" and "isn't connected" in run["message"]
    assert not os.path.exists("/Volumes/FunHoardTestNoSuchDrive")
    st = client.get("/api/status").json()
    assert st["export_root_ok"] is False and "FunHoardTestNoSuchDrive" in st["export_root_problem"]
