"""Fixtures for the service tests. Every test gets its own HOME, state
directory and export root under tmp_path; the exporter is tests/service/fake_exporter.py
and the permission checks are fakes, so nothing reaches Apple Notes or launchd."""

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402

from notes_service.app import create_app  # noqa: E402
from notes_service.config import Config  # noqa: E402
from notes_service.permissions import PermissionChecker  # noqa: E402

FAKE_EXPORTER = HERE / "fake_exporter.py"
FAKE_PERMISSION = HERE / "fake_permission.py"
FAKE_SECURITY = HERE / "fake_security.py"
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("NOTES_SERVICE_", "NOTES_EXPORT_", "FAKE_EXPORTER_", "FAKE_PERMISSION_",
                            "FAKE_SECURITY_", "NOTES_PERMISSION_")):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Safety: whatever a test builds from the environment asks fakes, never Apple Events or the Keychain.
    monkeypatch.setenv("NOTES_SERVICE_PERMISSION_HELPER", str(FAKE_PERMISSION))
    monkeypatch.setenv("NOTES_SERVICE_SECURITY_BIN", str(FAKE_SECURITY))
    monkeypatch.setenv("NOTES_SERVICE_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_SECURITY_STORE", str(tmp_path / "keychain.json"))
    monkeypatch.setenv("FAKE_SECURITY_LOG", str(tmp_path / "security.log"))
    return home


@pytest.fixture
def make_config(tmp_path):
    def make(**kw):
        defaults = dict(home=tmp_path / "state", scheduler_enabled=False, permission_check=True,
                        exporter=FAKE_EXPORTER, python=sys.executable, cancel_grace_seconds=1.0,
                        exporter_path=f"{Path(sys.executable).parent}:/usr/bin:/bin",
                        pass_env=["FAKE_EXPORTER_MODE", "FAKE_EXPORTER_SECONDS", "FAKE_EXPORTER_ARGS_FILE"],
                        progress_write_seconds=0.0, login_max_attempts=3, bcrypt_rounds=4,
                        permission_helper=FAKE_PERMISSION, security_bin=str(FAKE_SECURITY))
        defaults.update(kw)
        return Config(**defaults)
    return make


def fake_permissions(config):
    return PermissionChecker(config, automation=lambda: "allowed", disk=lambda: False)


@pytest.fixture
def export_root(tmp_path):
    return tmp_path / "export"


@pytest.fixture
def service(make_config, export_root):
    """(client, ctx) with an admin 'root' signed in; settings point at export_root."""
    config = make_config()
    app = create_app(config, fake_permissions(config))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        ctx.settings.update({"export_root": str(export_root)})
        token = client.post("/api/auth/login", json={"username": "root", "password": PASSWORD}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, ctx
        ctx.manager.shutdown()


def make_key(ctx, scopes, owner="root"):
    user = ctx.auth.get_user_by_name(owner)
    return ctx.auth.create_key(f"test-{'-'.join(scopes)}", scopes, user["id"])[1]
