"""End to end, with fakes: ``notes-exporter permission`` against a running
service, and scripts/live_check.py's logic (the opt-in ``live`` tier) run
against a service whose exporter and permission helper are fakes. Nothing here
reads Apple Notes; the real live tier is never run by the test suite."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from .test_service_e2e import FAKE_EXPORTER, REPO, server  # noqa: F401  (the fixture)

spec = importlib.util.spec_from_file_location("live_check_under_test", REPO / "scripts" / "live_check.py")
live_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_check)

NOTE_WORDS = ("Scones", "Shopping", "Draft", "draft", "Baking", "café", "iCloud-")


def run_cli(env, *args):
    return subprocess.run([str(REPO / "notes-exporter"), *args], env=env, capture_output=True, text=True,
                          timeout=60)


@pytest.fixture
def perm_server(server, tmp_path):  # noqa: F811
    state = tmp_path / "perm-state"
    state.write_text("prompt")
    http, env = server({"NOTES_SERVICE_EXPORTER": str(FAKE_EXPORTER),
                        "NOTES_SERVICE_EXPORTER_PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
                        "NOTES_SERVICE_PERMISSION_CHECK": "true",
                        "FAKE_PERMISSION_STATE": str(state),
                        "FAKE_PERMISSION_LOG": str(tmp_path / "perm.log")})
    http.json("PUT", "/api/admin/settings", {"export_root": str(tmp_path / "export"), "formats": ["html", "md"]})
    return http, env, state


def asks(tmp_path):
    log = tmp_path / "perm.log"
    return [a for a in (json.loads(x)["argv"] for x in log.read_text().splitlines()) if "--ask" in a]


def test_permission_cli_against_service(perm_server, tmp_path):
    http, env, state = perm_server
    r = run_cli(env, "permission", "status", "--refresh")
    assert r.returncode == 3 and "automation: prompt" in r.stdout, r.stderr
    r = run_cli(env, "permission", "request")
    assert r.returncode == 0, r.stderr
    assert "macOS is asking on this Mac — click Allow" in r.stdout and "automation: allowed" in r.stdout
    assert len(asks(tmp_path)) == 1
    assert http.json("GET", "/api/status")["permission"]["automation"] == "allowed"
    # The CLI's short sessions were all revoked afterwards.
    db = sqlite3.connect(tmp_path / "state" / "auth.sqlite")
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE revoked=0").fetchone()[0] == 0
    assert run_cli(env, "permission", "status", "--as", "nobody").returncode != 0


def test_permission_cli_without_service(server, tmp_path):  # noqa: F811
    http, env = server()
    env = dict(env, NOTES_SERVICE_PORT="1")
    r = run_cli(env, "permission", "request")
    assert r.returncode == 2
    assert "start the service first — the permission belongs to the process that asks" in r.stderr


def test_permission_cli_here(server, tmp_path):  # noqa: F811
    http, env = server()
    env = dict(env, FAKE_PERMISSION_STATE=str(tmp_path / "here-state"), FAKE_PERMISSION_LOG=str(tmp_path / "perm.log"))
    (tmp_path / "here-state").write_text("prompt")
    r = run_cli(env, "permission", "request", "--here")
    assert r.returncode == 0 and "not for the service" in r.stdout and "automation: allowed" in r.stdout
    assert len(asks(tmp_path)) == 1


def test_live_check_logic_with_fakes(perm_server, tmp_path):
    http, env, state = perm_server
    lines = []
    result = live_check.run_live_check(http.base, http.key, out=lines.append, poll=0.2, timeout=60)
    text = "\n".join(lines)
    assert "macOS is asking on this Mac — click Allow" in text
    assert result["status"] == "ok" and result["notes"] == 3 and result["books"] == 0
    assert result["checked"] == {"outputs": 4, "attachments": 1, "books": 0}
    assert "notes 3, changed 3" in text
    assert not any(w in text for w in NOTE_WORDS), text   # counts only, nothing of the notes
    assert http.key not in text
    runs = http.json("GET", "/api/runs?limit=1")["runs"]
    assert runs[0]["trigger"] == "cli"


def test_live_check_needs_admin_scope_to_ask(perm_server, tmp_path):
    http, env, state = perm_server
    key = run_cli(env, "apikey", "create", "--name", "live", "--scopes", "read,run").stdout.strip().splitlines()[-1]
    with pytest.raises(live_check.LiveCheckFailed, match="--scopes read,run,admin"):
        live_check.run_live_check(http.base, key, out=lambda s: None, poll=0.2)
    assert asks(tmp_path) == []


class TamperedFiles(live_check.httpx.HTTPTransport):
    """Hands back other bytes for one exported note file, as a damaged export would."""

    def handle_request(self, request):
        response = super().handle_request(request)
        if request.method == "GET" and "/api/files/" in request.url.path and request.url.path.endswith(".md"):
            response.read()
            return live_check.httpx.Response(200, content=b"tampered", request=request)
        return response


def test_live_check_spots_a_damaged_file(perm_server, tmp_path):
    http, env, state = perm_server
    state.write_text("allowed")
    lines = []
    with live_check.httpx.Client(base_url=http.base, headers={"Authorization": f"Bearer {http.key}"},
                                 transport=TamperedFiles()) as client:
        with pytest.raises(live_check.LiveCheckFailed, match="don't match the manifest"):
            live_check.run_live_check(http.base, http.key, out=lines.append, poll=0.2, client=client)
    assert "4 outputs (1 bad)" in "\n".join(lines)
    assert asks(tmp_path) == []   # already allowed: nothing asked


def test_load_key_from_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("OTHER=1\n# NOTES_EXPORTER_API_KEY=commented\nexport NOTES_EXPORTER_API_KEY=\"ne_abc\"\n")
    assert live_check.load_key({"NOTES_EXPORTER_LIVE_ENV_FILE": str(f)}) == "ne_abc"
    assert live_check.load_key({"NOTES_EXPORTER_API_KEY": "ne_env", "NOTES_EXPORTER_LIVE_ENV_FILE": str(f)}) == "ne_env"
    assert live_check.load_key({}) is None


def test_live_main_skips_without_opt_in(monkeypatch, capsys):
    monkeypatch.delenv("NOTES_EXPORTER_LIVE", raising=False)
    assert live_check.main() == 0
    assert "skipped" in capsys.readouterr().out
