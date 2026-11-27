"""End to end: the real ``notes-exporter serve`` on a free port, ``notes-exporter mcp setup``
making the MCP key (into the state directory's mcp.env, registered with a fake ``claude``),
then the real ``notes-exporter mcp serve`` started the way an MCP client starts it — a
subprocess speaking JSON-RPC on stdio — searching and reading the fixture export and
starting a run. Nothing reaches Apple Notes, a real Claude, launchd or the real export folder.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from .test_service_e2e import FAKE_EXPORTER, REPO, cli, server, wait_run  # noqa: F401  (server is a fixture)


class Stdio:
    def __init__(self, cmd, env):
        self.p = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        assert line, self.p.stderr.read()
        reply = json.loads(line)
        assert reply["id"] == self.next_id
        return reply

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def tool(self, name, **args):
        r = self.request("tools/call", {"name": name, "arguments": args})["result"]
        return r

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)
        return self.p.returncode


def test_mcp_over_stdio_against_the_real_service(server, tmp_path):
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text('#!/bin/sh\necho "$@" >> "$FAKE_CLAUDE_LOG"\n')
    fake_claude.chmod(0o755)
    http, env = server({"NOTES_SERVICE_EXPORTER": str(FAKE_EXPORTER),
                        "NOTES_SERVICE_EXPORTER_PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
                        "NOTES_SERVICE_CLAUDE_BIN": str(fake_claude),
                        "FAKE_CLAUDE_LOG": str(tmp_path / "claude.log")})
    http.json("PUT", "/api/admin/settings", {"export_root": str(tmp_path / "export"), "formats": ["html", "md"]})
    run = http.json("POST", "/api/runs", {}, expect=202)["run"]
    assert wait_run(http, run["id"])["status"] == "ok"

    out = cli(env, "mcp", "setup", "--client", "claude-code")
    assert "tools: notes_status" in out and "start_export" in out and "update_note" not in out
    env_file = tmp_path / "state" / "mcp.env"
    key = [l for l in env_file.read_text().splitlines() if l.startswith("NOTES_EXPORTER_API_KEY=")][0].split("=", 1)[1]
    assert key not in out
    registered = (tmp_path / "claude.log").read_text().splitlines()[-1].split(" -- ", 1)[1].split()
    assert registered[1:3] == ["mcp", "serve"]

    # Start it exactly as Claude Code would.
    s = Stdio(registered, env)
    try:
        init = s.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "e2e", "version": "0"}})["result"]
        assert init["serverInfo"]["name"] == "notes-exporter"
        s.notify("notifications/initialized")
        tools = {t["name"] for t in s.request("tools/list")["result"]["tools"]}
        assert {"search_notes", "read_note", "start_export"} <= tools and "update_note" not in tools

        hit = s.tool("search_notes", query="scones")
        found = json.loads(hit["content"][0]["text"])["notes"]
        assert [n["title"] for n in found] == ["Scones"]
        note = s.tool("read_note", id=found[0]["id"])
        assert not note["isError"] and "Scones" in note["content"][1]["text"]

        started = s.tool("start_export")
        rid = json.loads(started["content"][0]["text"])["run"]["id"]
        assert wait_run(http, rid)["status"] == "ok"
        got = json.loads(s.tool("get_run", run_id=rid, log_lines=5)["content"][0]["text"])
        assert got["status"] == "ok" and "log_tail" in got
    finally:
        assert s.close() == 0

    # Revoked: the tools say so instead of failing silently.
    assert "revoked 1 key(s)" in cli(env, "mcp", "uninstall", "--client", "claude-code")
    s = Stdio(registered, env)
    try:
        s.request("initialize", {"protocolVersion": "2025-06-18"})
        r = s.tool("notes_status")
        assert r["isError"] and "refused the API key" in r["content"][0]["text"]
    finally:
        s.close()
