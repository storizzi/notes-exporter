"""The notes-exporter command line (users, keys, serve's bind check)."""

import io
import subprocess
import sys

import pytest

from notes_service.auth import AuthStore
from notes_service.cli import main
from notes_service.config import Config

from .conftest import PASSWORD, REPO


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NOTES_SERVICE_BCRYPT_ROUNDS", "4")
    return tmp_path / "state"


def stdin(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_users_and_keys(state, monkeypatch, capsys):
    stdin(monkeypatch, PASSWORD + "\n")
    assert main(["user", "add", "simon", "--admin", "--password-stdin"]) == 0
    stdin(monkeypatch, PASSWORD + "\n")
    assert main(["user", "add", "reader1", "--password-stdin"]) == 0
    assert main(["user", "list"]) == 0
    out = capsys.readouterr().out
    assert "simon" in out and "admin" in out and "reader1" in out
    assert main(["apikey", "create", "--name", "FunHoard", "--scopes", "read,run"]) == 0
    out = capsys.readouterr().out
    key = out.strip().splitlines()[-1]
    assert key.startswith("ne_")
    store = AuthStore(Config.from_env())
    assert store.principal_from_key(key).scopes == {"read", "run"}
    assert main(["apikey", "list"]) == 0
    listed = capsys.readouterr().out
    assert key[:10] in listed and key not in listed
    assert main(["apikey", "create", "--name", "x", "--scopes", "bogus"]) == 1
    assert main(["apikey", "revoke", key[:10]]) == 0
    assert store.principal_from_key(key) is None
    stdin(monkeypatch, "a different password\n")
    assert main(["user", "passwd", "reader1", "--password-stdin"]) == 0
    assert store.verify_password("reader1", "a different password")
    assert main(["user", "remove", "simon"]) == 1   # the last admin
    assert main(["user", "remove", "reader1"]) == 0


def test_apikey_owner_needed_with_two_admins(state, monkeypatch):
    for name in ("a1", "a2"):
        stdin(monkeypatch, PASSWORD + "\n")
        main(["user", "add", name, "--admin", "--password-stdin"])
    with pytest.raises(SystemExit):
        main(["apikey", "create", "--name", "k"])
    assert main(["apikey", "create", "--name", "k", "--owner", "a2", "--expires-days", "30"]) == 0


def test_serve_refuses_remote_without_flag(state, capsys):
    assert main(["serve", "--host", "0.0.0.0", "--port", "1"]) == 2
    assert "--allow-remote" in capsys.readouterr().err


def test_entry_script_runs(state):
    r = subprocess.run([str(REPO / "notes-exporter"), "--help"], capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(state.parent), "NOTES_SERVICE_PYTHON": sys.executable})
    assert r.returncode == 0 and "serve" in r.stdout
