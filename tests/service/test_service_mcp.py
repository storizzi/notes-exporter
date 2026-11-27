"""The MCP server (notes_service/mcp_server.py) against the service in a TestClient, the
/api/admin/mcp endpoints, and `notes-exporter mcp setup | uninstall` with a fake `claude`
and a Claude Desktop config under tmp_path. Nothing reaches Apple Notes, a real client or
the real state directory."""

import base64
import io
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from notes_service import mcp_client, mcp_server
from notes_service.app import create_app
from notes_service.cli import main as cli_main
from notes_service.mcp_server import Api, ApiError, NotesMcp, Unreachable

from .conftest import PASSWORD, fake_permissions, make_key
from .fixture_export import PNG, build_export

HERE = Path(__file__).resolve().parent
SCONES = "x-coredata://TEST/ICNote/p1"
DRAFT = "x-coredata://TEST/ICNote/p2"


class ClientApi(Api):
    """Api over a FastAPI TestClient instead of the network."""

    def __init__(self, client, key):
        super().__init__("http://testserver", key)
        self.client = client

    def call(self, method, path, params=None, body=None, headers=None, timeout=None):
        if params:
            q = {k: ("true" if v is True else "false" if v is False else v) for k, v in params.items() if v is not None}
            path += "?" + urlencode(q)
        h = dict(headers or {})
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        r = self.client.request(method, path, json=body, headers=h)
        hdrs = {k.lower(): v for k, v in r.headers.items()}
        if r.status_code == 304:
            return 304, hdrs, b""
        if r.status_code >= 400:
            try:
                parsed = r.json()
            except ValueError:
                parsed = {"detail": r.text}
            raise ApiError(r.status_code, parsed.get("detail"), parsed)
        return r.status_code, hdrs, r.content


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
        yield client, ctx
        ctx.manager.shutdown()


def mcp(svc, scopes=("read",), read_only=False):
    client, ctx = svc
    return NotesMcp(ClientApi(client, make_key(ctx, list(scopes))), read_only=read_only)


def rpc(server, method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def call(server, name, **args):
    r = rpc(server, "tools/call", {"name": name, "arguments": args})
    assert "result" in r, r
    return r["result"]


def data(result, item=0):
    assert not result["isError"], result["content"][0]["text"]
    return json.loads(result["content"][item]["text"])


# ---- protocol ----
def test_initialize_negotiates_and_describes_itself(svc):
    s = mcp(svc)
    r = rpc(s, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "t", "version": "1"}})["result"]
    assert r["protocolVersion"] == "2025-06-18"
    assert r["serverInfo"]["name"] == "notes-exporter" and r["capabilities"]["tools"] == {"listChanged": False}
    assert "base_modified" in r["instructions"]
    assert rpc(s, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] \
        == mcp_server.SUPPORTED_PROTOCOLS[0]
    assert rpc(s, "ping") == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(s, "no/such")["error"]["code"] == -32601
    assert rpc(s, "tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32602


def test_tools_follow_the_keys_scopes(svc):
    names = lambda s: {t["name"] for t in rpc(s, "tools/list")["result"]["tools"]}
    read = names(mcp(svc, ["read"]))
    assert {"search_notes", "read_note", "list_notes", "notes_status"} <= read
    assert not read & {"start_export", "update_note", "create_note"}
    assert {"start_export", "cancel_export"} <= names(mcp(svc, ["read", "run"]))
    full = names(mcp(svc, ["read", "run", "write"]))
    assert {"update_note", "create_note"} <= full
    assert names(mcp(svc, ["read", "run", "write"], read_only=True)) == read
    # a tool the key can't use is explained, not run
    r = call(mcp(svc, ["read"]), "start_export")
    assert r["isError"] and "'run' scope" in r["content"][0]["text"]
    spec = next(t for t in rpc(mcp(svc, ["read", "write"]), "tools/list")["result"]["tools"] if t["name"] == "update_note")
    assert spec["annotations"]["destructiveHint"] is True and spec["inputSchema"]["required"] == ["id", "markdown", "base_modified"]


def test_stdio_loop_one_message_per_line(svc):
    s = mcp(svc)
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
             "not json",
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), ""]
    out = io.BytesIO()
    mcp_server.serve(s, io.BytesIO(("\n".join(lines) + "\n").encode()), out)
    replies = [json.loads(l) for l in out.getvalue().decode().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == -32700 and replies[2]["result"]["tools"]


# ---- reading ----
def test_status_folders_and_listing(svc):
    s = mcp(svc)
    st = data(call(s, "notes_status"))
    assert st["export"]["notes"] == 3 and st["this_key_scopes"] == ["read"]
    folders = data(call(s, "list_folders"))["folders"]
    assert {"account": "iCloud", "folder": "Food", "notes": 0, "notes_with_subfolders": 1} in folders
    assert {"account": "iCloud", "folder": "Notes", "notes": 2, "notes_with_subfolders": 2} in folders
    listed = data(call(s, "list_notes", folder="food/baking"))
    assert listed["total"] == 1 and listed["notes"][0]["title"] == "Scones"
    assert listed["notes"][0]["formats"] == ["html", "md"] and listed["notes"][0]["attachments"] == 1
    assert data(call(s, "list_notes", account="Other"))["total"] == 0
    assert data(call(s, "list_notes", modified_after="2026-01-03"))["total"] == 0
    assert data(call(s, "list_notes", limit=2))["notes"].__len__() == 2
    assert call(s, "list_notes", modified_after="soon")["isError"]
    assert call(s, "list_notes", colour="red")["isError"]


def test_search_titles_and_text(svc):
    s = mcp(svc)
    hits = data(call(s, "search_notes", query="scones"))
    assert [n["title"] for n in hits["notes"]] == ["Scones"]
    text = data(call(s, "search_notes", query="CAFÉ"))          # only in the HTML body
    assert [n["id"] for n in text["notes"]] == [DRAFT] and "café" in text["notes"][0]["snippet"]
    assert data(call(s, "search_notes", query="café", titles_only=True))["total"] == 0
    assert data(call(s, "search_notes", query='"draft café"'))["total"] == 1
    assert data(call(s, "search_notes", query="draft milk"))["total"] == 0
    assert call(s, "search_notes")["isError"]                    # query is required


def test_read_note_formats_and_errors(svc):
    s = mcp(svc)
    r = call(s, "read_note", id=SCONES)
    meta = data(r)
    assert meta["format"] == "md" and meta["modified"] == "2026-01-02T10:00:00+00:00"
    assert meta["attachments"][0]["kind"] == "image"
    assert r["content"][1]["text"].startswith("# Scones")
    draft = call(s, "read_note", id=DRAFT)
    assert data(draft)["format"] == "html" and draft["content"][1]["text"] == "Draft café"
    assert "<p>" in call(s, "read_note", id=DRAFT, format="html")["content"][1]["text"]
    assert "has: html" in call(s, "read_note", id=DRAFT, format="markdown")["content"][0]["text"]
    cut = call(s, "read_note", id=SCONES, max_chars=5)["content"][1]["text"]
    assert cut.startswith("# Sco") and "cut at 5" in cut
    gone = call(s, "read_note", id="x-coredata://TEST/ICNote/p9")
    assert gone["isError"] and "deleted" in gone["content"][0]["text"]
    assert "No note" in call(s, "read_note", id="x-coredata://TEST/ICNote/p77")["content"][0]["text"]


def test_attachment_comes_back_as_an_image(svc):
    s = mcp(svc)
    r = call(s, "get_attachment", note_id=SCONES, attachment="Scones-p1-attachment-001.png")
    assert not r["isError"]
    img = r["content"][1]
    assert img["type"] == "image" and img["mimeType"] == "image/png" and base64.b64decode(img["data"]) == PNG
    assert call(s, "get_attachment", note_id=SCONES, attachment="nope.pdf")["isError"]


def test_no_export_yet_is_explained(make_config, tmp_path):
    config = make_config()
    app = create_app(config, fake_permissions(config))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        ctx.settings.update({"export_root": str(tmp_path / "empty")})
        s = NotesMcp(ClientApi(client, make_key(ctx, ["read"])))
        r = call(s, "list_notes")
        assert r["isError"] and "no export yet" in r["content"][0]["text"].lower()
        ctx.manager.shutdown()


def test_a_refused_or_missing_key_and_no_service(svc):
    client, _ = svc
    bad = NotesMcp(ClientApi(client, "ne_not-a-real-key"))
    assert {t["name"] for t in rpc(bad, "tools/list")["result"]["tools"]} >= {"search_notes"}
    r = call(bad, "list_notes")
    assert r["isError"] and "refused the API key" in r["content"][0]["text"]

    def down(req, timeout=None):
        raise OSError("connection refused")
    nobody = NotesMcp(Api("http://127.0.0.1:9", "ne_x", opener=down))
    r = call(nobody, "notes_status")
    assert r["isError"] and "isn't answering" in r["content"][0]["text"]


# ---- runs and writes ----
def test_start_follow_and_refuse_a_second_export(svc, monkeypatch):
    monkeypatch.setenv("FAKE_EXPORTER_SECONDS", "3")
    s = mcp(svc, ["read", "run"])
    started = data(call(s, "start_export", folders=["Notes"]))
    rid = started["run"]["id"]
    assert started["run"]["folders"] == ["Notes"]
    again = call(s, "start_export")
    assert again["isError"] and rid in again["content"][0]["text"]
    assert data(call(s, "get_run", run_id=rid))["id"] == rid
    assert data(call(s, "cancel_export", run_id=rid))["id"] == rid
    assert data(call(s, "list_runs"))["runs"][0]["id"] == rid


def _wait_idle(ctx, timeout=30):
    import time
    end = time.time() + timeout
    while ctx.manager.running_run_id and time.time() < end:
        time.sleep(0.05)
    assert not ctx.manager.running_run_id


def test_writes_are_fenced_then_work(svc, writer):
    client, ctx = svc
    s = mcp(svc, ["read", "write"])
    args = dict(id=SCONES, markdown="# Scones\n\nMore butter.\n", base_modified="2026-01-02T10:00:00+00:00")
    off = call(s, "update_note", **args)
    assert off["isError"] and "turned off" in off["content"][0]["text"]
    ctx.settings.update({"allow_writes": True})
    stale = call(s, "update_note", **{**args, "base_modified": "2025-01-01T00:00:00+00:00"})
    assert stale["isError"] and "changed since you read it" in stale["content"][0]["text"]
    ok = data(call(s, "update_note", **args))
    assert ok["written"] and ok["note_id"] == SCONES and ok["export_run"]
    busy = call(s, "create_note", account="iCloud", folder="Food/Baking", markdown="# Bread\n")
    assert busy["isError"] and "export is running" in busy["content"][0]["text"]   # the write's own export
    _wait_idle(ctx)
    made = data(call(s, "create_note", account="iCloud", folder="Food/Baking", markdown="# Bread\n"))
    assert made["created"]
    _wait_idle(ctx)
    nowhere = call(s, "create_note", account="iCloud", folder="Nowhere", markdown="# X\n")
    assert nowhere["isError"] and "list_folders" in nowhere["content"][0]["text"]
    ctx.manager.shutdown()


# ---- /api/admin/mcp ----
def _signed_in(client):
    token = client.post("/api/auth/login", json={"username": "root", "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_mcp_keeps_the_key_in_the_env_file_and_rotates_it(svc):
    client, ctx = svc
    h = _signed_in(client)
    st = client.get("/api/admin/mcp", headers=h).json()
    assert st["key"] is None and st["key_problem"] == "no key yet"
    assert "claude mcp add --scope user notes-exporter -- " in st["clients"]["claude_code"]
    assert json.loads(st["clients"]["json"])["mcpServers"]["notes-exporter"]["args"][:2] == ["mcp", "serve"]

    r = client.post("/api/admin/mcp", json={"scopes": ["read", "run"]}, headers=h)
    assert r.status_code == 201 and "key" not in r.json()
    env = Path(r.json()["env_file"])
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    first = mcp_client.read_env_key(env)
    assert ctx.auth.key_record(first)["scopes"] == ["read", "run"]
    st = client.get("/api/admin/mcp", headers=h).json()
    assert st["key"]["prefix"] == first[:10]

    r2 = client.post("/api/admin/mcp", json={"scopes": ["write"]}, headers=h).json()
    assert r2["revoked"] == [first[:10]] and r2["api_key"]["scopes"] == ["read", "write"]
    assert ctx.auth.key_record(first) is None
    assert client.post("/api/admin/mcp", json={"scopes": ["admin"]}, headers=h).status_code == 422


def test_admin_mcp_shows_a_key_once_for_another_computer(svc):
    client, ctx = svc
    h = _signed_in(client)
    kept = client.post("/api/admin/mcp", json={}, headers=h).json()
    r = client.post("/api/admin/mcp", json={"keep": "show", "name": "MCP (laptop)", "read_only": True}, headers=h).json()
    assert r["key"].startswith("ne_") and "--key-stdin" in r["remote_setup"]
    assert "--read-only" in json.loads(r["clients"]["json"])["mcpServers"]["notes-exporter"]["args"]
    # the key file still holds the first key
    assert ctx.auth.key_record(mcp_client.read_env_key(kept["env_file"]))["prefix"] == kept["api_key"]["prefix"]


def test_admin_mcp_needs_admin(svc):
    client, ctx = svc
    h = {"Authorization": f"Bearer {make_key(ctx, ['read', 'run'])}"}
    assert client.get("/api/admin/mcp", headers=h).status_code == 403
    assert client.post("/api/admin/mcp", json={}, headers=h).status_code == 403


def test_change_my_password_signs_out(svc):
    client, ctx = svc
    h = _signed_in(client)
    bad = client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "a new password"}, headers=h)
    assert bad.status_code == 403
    ok = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a new password"}, headers=h)
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/login", json={"username": "root", "password": "a new password"}).status_code == 200


def test_the_web_page_has_the_mcp_and_account_tabs(svc):
    client, _ = svc
    page = client.get("/").text
    assert 'data-tab="mcp"' in page and 'id="password-form"' in page
    js = client.get("/static/app.js").text
    assert "/admin/mcp" in js and "/auth/password" in js


# ---- notes-exporter mcp setup | check | uninstall ----
FAKE_CLAUDE = """#!/bin/sh
echo "$@" >> "$FAKE_CLAUDE_LOG"
exit 0
"""


@pytest.fixture
def setup_env(tmp_path, monkeypatch, make_config):
    state = tmp_path / "state"
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(state))
    monkeypatch.setenv("NOTES_SERVICE_BCRYPT_ROUNDS", "4")
    monkeypatch.setenv("NOTES_SERVICE_PORT", "9")          # nothing listens there: check says so
    claude = tmp_path / "fake-claude"   # not "claude": the disk is case-insensitive, and Claude/ is below
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(0o755)
    monkeypatch.setenv("NOTES_SERVICE_CLAUDE_BIN", str(claude))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "claude.log"))
    desktop = tmp_path / "Claude" / "claude_desktop_config.json"
    desktop.parent.mkdir()
    desktop.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": True}))
    monkeypatch.setenv("NOTES_SERVICE_CLAUDE_DESKTOP_CONFIG", str(desktop))
    for v in ("NOTES_EXPORTER_API_KEY", "NOTES_EXPORTER_URL", "NOTES_EXPORTER_MCP_ENV_FILE"):
        monkeypatch.delenv(v, raising=False)
    from notes_service.auth import AuthStore
    from notes_service.config import Config
    config = Config.from_env()
    config.ensure_home()
    AuthStore(config).create_user("root", PASSWORD, "admin")
    return {"state": state, "claude_log": tmp_path / "claude.log", "desktop": desktop, "config": config}


def test_setup_makes_the_key_and_registers_both_clients(setup_env, capsys):
    rc = cli_main(["mcp", "setup", "--client", "claude-code", "--client", "claude-desktop", "--write"])
    out = capsys.readouterr().out
    assert rc == 2 and "isn't answering" in out          # registered; the service just isn't running here
    env = setup_env["state"] / "mcp.env"
    key = mcp_client.read_env_key(env)
    assert key and key not in out                          # never printed
    from notes_service.auth import AuthStore
    store = AuthStore(setup_env["config"])
    assert store.key_record(key)["scopes"] == ["read", "run", "write"] and store.key_record(key)["name"] == "MCP"
    log = setup_env["claude_log"].read_text().splitlines()
    port_url = "http://127.0.0.1:9"
    assert log[0] == "mcp remove --scope user notes-exporter"
    assert log[1].startswith("mcp add --scope user notes-exporter -- ") and log[1].endswith(
        f"notes-exporter mcp serve --url {port_url} --env-file {env}")
    desk = json.loads(setup_env["desktop"].read_text())
    assert desk["keep"] is True and desk["mcpServers"]["other"] == {"command": "x"}
    assert desk["mcpServers"]["notes-exporter"]["args"] == ["mcp", "serve", "--url", port_url, "--env-file", str(env)]
    assert list(setup_env["desktop"].parent.glob("claude_desktop_config.json.bak-*"))

    # again: the key rotates, the clients stay
    cli_main(["mcp", "setup", "--client", "claude-desktop"])
    capsys.readouterr()
    key2 = mcp_client.read_env_key(env)
    assert key2 != key and store.key_record(key) is None and store.key_record(key2)["scopes"] == ["read", "run"]

    assert cli_main(["mcp", "uninstall"]) == 0
    out = capsys.readouterr().out
    assert "revoked 1 key(s)" in out and store.key_record(key2) is None
    assert "notes-exporter" not in json.loads(setup_env["desktop"].read_text())["mcpServers"]
    assert setup_env["claude_log"].read_text().splitlines()[-1] == "mcp remove --scope user notes-exporter"


def test_setup_dry_run_changes_nothing(setup_env, capsys):
    before = setup_env["desktop"].read_text()
    assert cli_main(["mcp", "setup", "--dry-run", "--client", "claude-code", "--client", "claude-desktop"]) == 0
    out = capsys.readouterr().out
    assert "would run:" in out and "would set mcpServers.notes-exporter" in out
    assert not (setup_env["state"] / "mcp.env").exists() and setup_env["desktop"].read_text() == before
    assert not setup_env["claude_log"].exists()


def test_setup_for_another_mac_takes_the_key_on_stdin(setup_env, capsys, monkeypatch):
    with pytest.raises(SystemExit, match="key-stdin"):
        cli_main(["mcp", "setup", "--url", "https://notes.example", "--client", "print"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("ne_from-the-other-mac\n"))
    cli_main(["mcp", "setup", "--url", "https://notes.example", "--key-stdin", "--client", "print"])
    out = capsys.readouterr().out
    assert "ne_from-the-other-mac" not in out and '"--url",' in out and "https://notes.example" in out
    assert mcp_client.read_env_key(setup_env["state"] / "mcp.env") == "ne_from-the-other-mac"


def test_read_env_key_forms(tmp_path):
    f = tmp_path / "e.env"
    f.write_text("# x\nOTHER=1\nexport NOTES_EXPORTER_API_KEY='ne_abc'\n")
    assert mcp_client.read_env_key(f) == "ne_abc"
    assert mcp_client.read_env_key(tmp_path / "missing") is None
