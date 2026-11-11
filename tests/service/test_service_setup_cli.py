"""Setup commands: API keys written into an env file, generated passwords kept
in the Keychain (through tests/service/fake_security.py, never the real one)."""

import io
import json
import os
import stat
import sys

import pytest

from notes_service.auth import AuthStore
from notes_service.cli import main
from notes_service.config import Config

from .conftest import PASSWORD


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NOTES_SERVICE_BCRYPT_ROUNDS", "4")
    monkeypatch.setattr(sys, "stdin", io.StringIO(PASSWORD + "\n"))
    assert main(["user", "add", "simon", "--admin", "--password-stdin"]) == 0
    return tmp_path / "state"


def store():
    return AuthStore(Config.from_env())


def env_key(path, name="NOTES_EXPORTER_API_KEY"):
    for line in path.read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    return None


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_env_file_new(state, tmp_path, capsys):
    capsys.readouterr()
    target = tmp_path / "backend" / ".env"
    target.parent.mkdir()
    assert main(["apikey", "create", "--name", "FunHoard", "--scopes", "read,run", "--env-file", str(target)]) == 0
    out, err = capsys.readouterr()
    key = env_key(target)
    assert key and key.startswith("ne_")
    assert key not in out and key not in err
    assert out.strip() == (f"created FunHoard (read,run), key {key[:10]}… written to {os.path.realpath(target)} "
                           "as NOTES_EXPORTER_API_KEY")
    assert target.read_text() == f"NOTES_EXPORTER_API_KEY={key}\n"
    assert mode(target) == 0o600
    assert store().principal_from_key(key).scopes == {"read", "run"}
    assert not [p for p in target.parent.iterdir() if p.name != ".env"]   # no temp file left


def test_env_file_existing_lines_kept(state, tmp_path, capsys):
    target = tmp_path / ".env"
    before = (b"# FunHoard backend\r\nMONGO_URL=mongodb://localhost:27017\r\n\n"
              b"export NOTES_EXPORTER_API_KEY=ne_oldvalue\n"
              b"OTHER='quoted value'  # comment\n"
              b"NOTES_EXPORTER_API_KEY=ne_duplicate\n"
              b"NOTES_EXPORTER_API_KEY_OLD=keep me\n"
              b"LAST=no newline")
    target.write_bytes(before)
    os.chmod(target, 0o644)
    assert main(["apikey", "create", "--name", "FunHoard", "--scopes", "read,run", "--env-file", str(target)]) == 0
    capsys.readouterr()
    after = target.read_bytes()
    lines = after.split(b"\n")
    key = lines[3].split(b"=", 1)[1].decode()
    assert lines[3] == b"export NOTES_EXPORTER_API_KEY=" + key.encode()
    expected = (b"# FunHoard backend\r\nMONGO_URL=mongodb://localhost:27017\r\n\n"
                b"export NOTES_EXPORTER_API_KEY=" + key.encode() + b"\n"
                b"OTHER='quoted value'  # comment\n"
                b"NOTES_EXPORTER_API_KEY_OLD=keep me\n"
                b"LAST=no newline")
    assert after == expected
    assert mode(target) == 0o600
    assert store().principal_from_key(key) is not None


def test_env_file_other_name_appends(state, tmp_path, capsys):
    target = tmp_path / ".env"
    target.write_text("A=1\n")
    assert main(["apikey", "create", "--name", "k", "--env-file", str(target), "--env-var", "NOTES_KEY_2"]) == 0
    text = target.read_text()
    assert text.startswith("A=1\nNOTES_KEY_2=ne_") and text.endswith("\n")
    assert "as NOTES_KEY_2" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["lower", "1ABC", "A-B", "A B", ""])
def test_env_var_name_refused(state, tmp_path, bad):
    target = tmp_path / ".env"
    with pytest.raises(SystemExit):
        main(["apikey", "create", "--name", "k", "--env-file", str(target), "--env-var", bad])
    assert not target.exists()
    assert store().list_keys() == []


def test_env_var_needs_env_file(state):
    with pytest.raises(SystemExit):
        main(["apikey", "create", "--name", "k", "--env-var", "X"])


def test_env_file_unwritable_keeps_no_key(state, tmp_path, capsys):
    target = tmp_path / "missing-dir" / ".env"
    assert main(["apikey", "create", "--name", "k", "--env-file", str(target)]) == 1
    assert store().list_keys() == []
    assert "not kept" in capsys.readouterr().err


def test_replace_revokes_older_keys_of_that_name(state, tmp_path, capsys):
    target = tmp_path / ".env"
    s = store()
    owner = s.get_user_by_name("simon")
    _, old1 = s.create_key("FunHoard", "read,run", owner["id"])
    _, old2 = s.create_key("FunHoard", "read", owner["id"])
    _, other = s.create_key("Something else", "read", owner["id"])
    assert main(["apikey", "create", "--name", "FunHoard", "--scopes", "read,run", "--env-file", str(target),
                 "--replace"]) == 0
    out, err = capsys.readouterr()
    new = env_key(target)
    assert new not in out + err
    assert "revoked 2 older key(s) named FunHoard" in out
    s = store()
    assert s.principal_from_key(new) is not None
    assert s.principal_from_key(old1) is None and s.principal_from_key(old2) is None
    assert s.principal_from_key(other) is not None


# ---- generated passwords in the Keychain ----

def security_calls(tmp_path):
    log = tmp_path / "security.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def keychain(tmp_path):
    path = tmp_path / "keychain.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_generated_password_in_keychain(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NOTES_SERVICE_BCRYPT_ROUNDS", "4")
    assert main(["user", "add", "simon", "--admin", "--generate-password", "--keychain"]) == 0
    out, err = capsys.readouterr()
    item = keychain(tmp_path)["simon|notes-exporter"]
    password = item["password"]
    assert len(password) >= 32 and not password.startswith("-")
    assert item["label"] == "notes-exporter (simon)"
    assert password not in out and password not in err
    assert 'password for simon stored in your login Keychain as "notes-exporter" (open the Passwords app to see it)' in out
    assert "added simon (admin)" in out
    calls = security_calls(tmp_path)
    assert calls[0]["argv"] == ["-i"]
    assert calls[0]["stdin"] == (f'add-generic-password -U -a "simon" -s "notes-exporter" '
                                 f'-l "notes-exporter (simon)" -w "{password}"\n')
    assert all(password not in " ".join(c["argv"]) for c in calls)
    assert store().verify_password("simon", password)


def test_passwd_regenerates_into_keychain(state, tmp_path, capsys):
    assert main(["user", "passwd", "simon", "--generate-password", "--keychain", "--keychain-service", "ne-test"]) == 0
    out, err = capsys.readouterr()
    password = keychain(tmp_path)["simon|ne-test"]["password"]
    assert password not in out + err
    assert '"ne-test"' in out
    assert store().verify_password("simon", password)
    assert not store().verify_password("simon", PASSWORD)


def test_generate_needs_keychain(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(tmp_path / "state"))
    with pytest.raises(SystemExit):
        main(["user", "add", "simon", "--admin", "--generate-password"])
    assert store().list_users() == []
    assert security_calls(tmp_path) == []


def test_keychain_failure_creates_no_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_SECURITY_FAIL", "1")
    assert main(["user", "add", "simon", "--admin", "--generate-password", "--keychain"]) == 1
    assert "couldn't store the password" in capsys.readouterr().err
    assert store().list_users() == []


def test_keychain_failure_keeps_old_password(state, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SECURITY_FAIL", "1")
    assert main(["user", "passwd", "simon", "--generate-password", "--keychain"]) == 1
    assert store().verify_password("simon", PASSWORD)


def test_existing_user_refused_before_keychain(state, tmp_path, capsys):
    assert main(["user", "add", "simon", "--generate-password", "--keychain"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert security_calls(tmp_path) == []
