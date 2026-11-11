"""Asking macOS for permission to automate Notes: notes_permission.py --ask's
logic (with the Apple Event call replaced), the service's request endpoint and
the helper subprocess (tests/service/fake_permission.py, never the real one)."""

import importlib.util
import json
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from notes_service.app import create_app
from notes_service.permissions import PermissionChecker, PermissionRequestBusy, automation_state, request_automation

from .conftest import FAKE_PERMISSION, PASSWORD, REPO, make_key

spec = importlib.util.spec_from_file_location("notes_permission_under_test", REPO / "notes_permission.py")
notes_permission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes_permission)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_ask_allowed_without_launching():
    calls, launched = [], []
    status = notes_permission.ask(5, 0.5, checker=lambda ask: calls.append(ask) or 0,
                                  launcher=lambda: launched.append(1))
    assert status == 0 and calls == [True] and launched == []


def test_ask_launches_notes_and_retries():
    answers = iter([notes_permission.PROC_NOT_FOUND, notes_permission.PROC_NOT_FOUND, 0])
    asks, launched, clock = [], [], Clock()
    status = notes_permission.ask(5, 0.5, checker=lambda ask: asks.append(ask) or next(answers),
                                  launcher=lambda: launched.append(1), clock=clock, sleep=clock.sleep)
    assert status == 0 and launched == [1] and asks == [True, True, True]


def test_ask_gives_up_after_wait():
    clock = Clock()
    status = notes_permission.ask(2, 0.5, checker=lambda ask: notes_permission.PROC_NOT_FOUND,
                                  launcher=lambda: None, clock=clock, sleep=clock.sleep)
    assert status == notes_permission.PROC_NOT_FOUND and clock.t >= 2


def test_main_ask_and_check_words(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(notes_permission, "check", lambda ask=False: seen.append(ask) or -1744)
    assert notes_permission.main([]) == 3 and capsys.readouterr().out.strip() == "prompt"
    monkeypatch.setattr(notes_permission, "ask", lambda wait, poll: seen.append(("ask", wait)) or 0)
    assert notes_permission.main(["--ask", "--wait", "7"]) == 0 and capsys.readouterr().out.strip() == "allowed"
    assert seen == [False, ("ask", 7.0)]


def test_launch_notes_uses_open_in_background(monkeypatch):
    ran = []
    monkeypatch.setenv("NOTES_PERMISSION_OPEN", "/fake/open")
    monkeypatch.setattr(notes_permission.subprocess, "run", lambda argv, **kw: ran.append(argv))
    notes_permission.launch_notes()
    assert ran == [["/fake/open", "-g", "-j", "-b", "com.apple.Notes"]]


def test_helper_subprocess_check_and_ask(make_config, tmp_path, monkeypatch):
    state, log = tmp_path / "perm-state", tmp_path / "perm.log"
    state.write_text("prompt")
    monkeypatch.setenv("FAKE_PERMISSION_STATE", str(state))
    monkeypatch.setenv("FAKE_PERMISSION_LOG", str(log))
    config = make_config(permission_launch_wait_seconds=4)
    assert config.permission_helper == FAKE_PERMISSION
    assert automation_state(config) == "prompt"
    assert request_automation(config) == "allowed"
    assert automation_state(config) == "allowed"
    argvs = [json.loads(line)["argv"] for line in log.read_text().splitlines()]
    assert argvs == [[], ["--ask", "--wait", "4"], []]


def test_request_times_out(make_config, monkeypatch):
    monkeypatch.setenv("FAKE_PERMISSION_SLEEP", "5")
    config = make_config(permission_request_timeout_seconds=0.5)
    assert request_automation(config) == "unknown(TimeoutExpired)"


def test_checker_request_refreshes_and_is_one_at_a_time(make_config):
    state = {"auto": "prompt"}
    gate, entered = threading.Event(), threading.Event()

    def requester():
        entered.set()
        gate.wait(5)
        state["auto"] = "allowed"
        return "allowed"

    checker = PermissionChecker(make_config(), automation=lambda: state["auto"], disk=lambda: None,
                                requester=requester)
    assert checker.get()["automation"] == "prompt"
    results = []
    t = threading.Thread(target=lambda: results.append(checker.request()))
    t.start()
    assert entered.wait(5) and checker.requesting
    with pytest.raises(PermissionRequestBusy):
        checker.request()
    gate.set()
    t.join(5)
    assert results[0]["automation"] == "allowed" and not checker.requesting
    assert checker.get()["automation"] == "allowed"   # the cache was refreshed


@pytest.fixture
def perm_service(make_config, tmp_path):
    state = {"auto": "prompt", "asked": 0}
    gate = threading.Event()
    gate.set()

    def requester():
        state["asked"] += 1
        gate.wait(5)
        state["auto"] = "allowed"
        return "allowed"

    config = make_config()
    checker = PermissionChecker(config, automation=lambda: state["auto"], disk=lambda: False, requester=requester)
    app = create_app(config, checker)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        yield client, ctx, state, gate
        ctx.manager.shutdown()


def test_permission_endpoints(perm_service):
    client, ctx, state, gate = perm_service
    admin = {"Authorization": f"Bearer {make_key(ctx, ['read', 'run', 'admin'])}"}
    runner = {"Authorization": f"Bearer {make_key(ctx, ['read', 'run'])}"}
    assert client.post("/api/admin/permission/request", headers=runner).status_code == 403
    assert client.get("/api/admin/permission", headers=runner).status_code == 403
    got = client.get("/api/admin/permission", headers=admin).json()
    assert got["automation"] == "prompt" and got["requesting"] is False
    assert client.get("/api/status", headers=admin).json()["permission"]["automation"] == "prompt"
    r = client.post("/api/admin/permission/request", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"automation", "full_disk_access", "checked_at"}
    assert body["automation"] == "allowed" and body["full_disk_access"] is False and state["asked"] == 1
    assert client.get("/api/status", headers=admin).json()["permission"]["automation"] == "allowed"


def test_permission_request_busy(perm_service):
    client, ctx, state, gate = perm_service
    admin = {"Authorization": f"Bearer {make_key(ctx, ['read', 'run', 'admin'])}"}
    gate.clear()
    first = []
    t = threading.Thread(target=lambda: first.append(client.post("/api/admin/permission/request", headers=admin)))
    t.start()
    for _ in range(100):
        if ctx.permissions.requesting:
            break
        time.sleep(0.02)
    assert ctx.permissions.requesting
    assert client.post("/api/admin/permission/request", headers=admin).status_code == 409
    assert client.get("/api/admin/permission", headers=admin).json()["requesting"] is True
    gate.set()
    t.join(10)
    assert first[0].status_code == 200 and state["asked"] == 1
