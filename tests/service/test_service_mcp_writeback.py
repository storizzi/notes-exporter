"""The MCP server's write tools against 1.7.0's fences (backup, delete, limits, approvals) —
the fake writer, never Notes."""

import json

from .test_service_mcp import SCONES, call, data, mcp, svc, writer  # noqa: F401

OFF = {"write_hold_batch_over": 0, "write_hold_count_over": 0, "write_hold_change_percent": 0}
ARGS = dict(id=SCONES, markdown="# Scones\n\nMore butter.\n", base_modified="2026-01-02T10:00:00+00:00")


def test_update_reports_the_backup_and_delete_works(svc, writer):
    client, ctx = svc
    ctx.settings.update({"allow_writes": True, **OFF})
    s = mcp(svc, ["read", "write"])
    assert {"delete_note", "list_held_writes"} <= {t["spec"]["name"] for t in s.tools()}
    assert "approve_held_write" not in {t["spec"]["name"] for t in s.tools()}
    ok = data(call(s, "update_note", **ARGS))
    assert ok["written"] and ok["backup_note_id"] == "x-coredata://TEST/ICNote/backup1"
    ctx.manager.shutdown()


def test_delete_and_the_limit(svc, writer):
    client, ctx = svc
    ctx.settings.update({"allow_writes": True, "write_max_changes_per_hour": 1, **OFF})
    s = mcp(svc, ["read", "write"])
    gone = data(call(s, "delete_note", id=SCONES, base_modified="2026-01-02T10:00:00+00:00"))
    assert gone["deleted"] and gone["recently_deleted"]
    assert json.loads(writer.read_text())["deleted"] == [SCONES]
    ctx.manager.shutdown()
    limited = call(s, "update_note", **{**ARGS, "force": True})
    assert limited["isError"] and "limit against mass changes" in limited["content"][0]["text"]


def test_a_held_write_says_so_and_only_an_approver_approves(svc, writer):
    client, ctx = svc
    ctx.settings.update({"allow_writes": True, **OFF, "write_hold_count_over": 0, "write_hold_batch_over": 0})
    ctx.settings.update({"write_hold_count_over": 1})
    s = mcp(svc, ["read", "write"])
    assert data(call(s, "update_note", **ARGS))["written"]
    ctx.manager.shutdown()
    held = data(call(s, "create_note", account="iCloud", folder="Food", markdown="# Bread\n"))
    assert held["held"] and held["written"] is False and "Don't send it again" in held["message"]
    mine = data(call(s, "list_held_writes"))
    assert mine["counts"]["total"] == 1
    approver = mcp(svc, ["read", "approve"])
    done = data(call(approver, "approve_held_write", approval_id=held["approval_id"]))
    assert done["approved"] and done["note_id"] == "x-coredata://TEST/ICNote/new1"
    ctx.manager.shutdown()
