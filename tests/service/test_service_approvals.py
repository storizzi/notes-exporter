"""The approval list and one-off sign-in links (1.7.0), with the fake writer — never Notes."""

import json
from urllib.parse import quote

from notes_service.approvals import ApprovalStore, change_percent

from .conftest import make_key
import pytest

from .test_service_writes import NOTE, URL, _edit_manifest, allow, body, calls, writer  # noqa: F401
from .test_service_writes import svc as writer_svc  # noqa: F401


@pytest.fixture
def svc(writer_svc):
    """The writes tests' service, its client a key that may also approve."""
    client, ctx = writer_svc
    client.headers["Authorization"] = "Bearer " + make_key(ctx, ["read", "write", "approve"])
    return client, ctx

LONG = "# Scones\n\nFlour, butter, sugar.\nMilk and an egg.\nBake at 220 for 12 minutes.\nServe warm with jam.\n"
OTHER = "# Shopping\n\nBananas.\nNewspaper.\nLight bulbs.\nStamps for the cards.\n"


def holds(ctx, **rules):
    """Writing on, every hold rule off but the ones named."""
    allow(ctx)
    ctx.settings.update(rules)


def long_note(export_root):
    (export_root / "md" / "iCloud-Baking" / "Scones-p1.md").write_text(LONG)


def ops(writer):
    return [c["operation"] for c in calls(writer)]


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_a_big_change_is_held_then_approved_the_normal_way(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    long_note(export_root)
    r = client.put(URL, json=body(markdown=OTHER))
    assert r.status_code == 202, r.text
    held = r.json()
    assert held["held"] is True and held["reason"] == "big_change" and held["note_id"] == NOTE
    assert ops(writer) == []                                   # nothing reached Notes
    listed = client.get("/api/approvals").json()
    assert listed["counts"]["total"] == 1 and listed["approvals"][0]["id"] == held["approval_id"]
    assert "before" not in listed["approvals"][0]
    detail = client.get(f"/api/approvals/{held['approval_id']}").json()
    assert detail["before"] == LONG and detail["after"] == OTHER and detail["change_percent"] > 50
    assert "-Flour, butter, sugar." in detail["diff"] and "+Bananas." in detail["diff"]
    assert detail["client"]["name"].startswith("test-")
    r = client.post(f"/api/approvals/{held['approval_id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["approved"] is True and r.json()["backup_note_id"]
    assert ops(writer) == ["modified", "backup", "update"]
    assert client.get("/api/approvals").json()["counts"]["total"] == 0


def test_a_small_change_or_a_short_note_goes_straight_through(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    assert client.put(URL, json=body(markdown=OTHER)).status_code == 200      # the fixture's note is 2 lines
    long_note(export_root)
    assert client.put(URL, json=body(markdown=LONG.replace("12", "14"), force=True)).status_code == 200


def test_a_delete_counts_as_a_whole_change(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    long_note(export_root)
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00Z", "export": "false"})
    assert r.status_code == 202 and r.json()["kind"] == "delete"
    assert client.get("/api/approvals").json()["approvals"][0]["change_percent"] == 100.0
    assert client.post(f"/api/approvals/{r.json()['approval_id']}/approve").json()["deleted"] is True
    assert json.loads(writer.read_text())["deleted"] == [NOTE]


def test_more_changes_than_the_window_allows_are_held(svc, writer):
    client, ctx = svc
    holds(ctx, write_hold_count_over=1, write_hold_window_hours=24)
    assert client.put(URL, json=body(force=True)).status_code == 200
    new = {"account": "iCloud", "folder_path": ["Food"], "markdown": "# Pancakes\n", "export": False}
    r = client.post("/api/notes", json=new)
    assert r.status_code == 202 and r.json()["reason"] == "count" and r.json()["kind"] == "create"
    assert "create" not in ops(writer)
    approved = client.post(f"/api/approvals/{r.json()['approval_id']}/approve").json()
    assert approved["note_id"] == "x-coredata://TEST/ICNote/new1"      # approving ignores the rules


def test_a_burst_from_one_client_is_held(svc, writer):
    client, ctx = svc
    holds(ctx, write_hold_batch_over=1, write_hold_batch_seconds=60)
    assert client.put(URL, json=body(force=True)).status_code == 200
    r = client.put(URL, json=body(force=True))
    assert r.status_code == 202 and r.json()["reason"] == "batch"
    other = make_key(ctx, ["read", "write"])                            # another client isn't in this burst
    assert client.put(URL, json=body(force=True), headers=auth(other)).status_code == 200


def test_a_note_changed_meanwhile_makes_the_approval_stale(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    long_note(export_root)
    held = client.put(URL, json=body(markdown=OTHER)).json()
    _edit_manifest(export_root, modified="2026-03-01T10:00:00+00:00")
    r = client.post(f"/api/approvals/{held['approval_id']}/approve")
    assert r.status_code == 409 and r.json()["reason"] == "export" and r.json()["stale"] is True
    item = client.get("/api/approvals").json()["approvals"][0]
    assert item["status"] == "stale" and item["stale_reason"] == "export"
    assert "update" not in ops(writer)
    assert client.post(f"/api/approvals/{held['approval_id']}/reject").json()["rejected"] is True
    assert client.get("/api/approvals").json()["counts"]["total"] == 0


def test_who_may_see_and_decide(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    long_note(export_root)
    mine = make_key(ctx, ["read", "write"])
    theirs = ctx.auth.create_key("other-writer", ["read", "write"], ctx.auth.get_user_by_name("root")["id"])[1]
    approver = ctx.auth.create_key("approver", ["approve"], ctx.auth.get_user_by_name("root")["id"])[1]
    aid = client.put(URL, json=body(markdown=OTHER), headers=auth(mine)).json()["approval_id"]
    assert client.get("/api/approvals", headers=auth(mine)).json()["counts"]["total"] == 1
    assert client.get("/api/approvals", headers=auth(theirs)).json()["counts"]["total"] == 0
    assert client.get(f"/api/approvals/{aid}", headers=auth(theirs)).status_code == 404
    reader = make_key(ctx, ["read"])
    assert client.get("/api/approvals", headers=auth(reader)).status_code == 403
    r = client.post(f"/api/approvals/{aid}/approve", headers=auth(mine))
    assert r.status_code == 403 and r.json()["reason"] == "scope"
    assert client.get("/api/approvals", headers=auth(approver)).json()["can_approve"] is True
    assert client.post(f"/api/approvals/{aid}/approve", headers=auth(approver)).status_code == 200
    admin = make_key(ctx, ["read", "admin"])                            # admin implies approve
    assert client.get("/api/approvals", headers=auth(admin)).json()["can_approve"] is True


def test_bulk_approve_and_reject(svc, writer):
    client, ctx = svc
    holds(ctx, write_hold_count_over=1)
    assert client.put(URL, json=body(force=True)).status_code == 200
    new = {"account": "iCloud", "folder_path": ["Food"], "markdown": "# Pancakes\n", "export": False}
    ids = [client.post("/api/notes", json=new).json()["approval_id"] for _ in range(3)]
    r = client.post("/api/approvals/bulk", json={"action": "reject", "ids": [ids[0], "nope-nope-nope"]}).json()
    assert r["rejected"] == 1 and r["failed"] == 1
    r = client.post("/api/approvals/bulk", json={"action": "approve", "all": True}).json()
    assert r["approved"] == 2 and r["failed"] == 0 and r["run"] is None
    assert ops(writer).count("create") == 2
    assert client.post("/api/approvals/bulk", json={"action": "approve"}).status_code == 400


def test_a_bulk_approval_exports_once(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_count_over=1)
    assert client.put(URL, json=body(force=True)).status_code == 200
    new = {"account": "iCloud", "folder_path": ["Food"], "markdown": "# Pancakes\n"}
    for _ in range(2):
        assert client.post("/api/notes", json=new).status_code == 202
    r = client.post("/api/approvals/bulk", json={"action": "approve", "all": True}).json()
    assert r["approved"] == 2 and r["run"]["folders"] == ["Food"] and r["run"]["requested_by"] == "approve"


def test_held_writes_survive_a_restart_and_age_out(svc, writer, export_root):
    client, ctx = svc
    holds(ctx, write_hold_change_percent=50, write_hold_min_lines=2)
    long_note(export_root)
    aid = client.put(URL, json=body(markdown=OTHER)).json()["approval_id"]
    assert ApprovalStore(ctx.config).get(aid)["after"] == OTHER          # what a restarted service reads
    path = ctx.config.home / "approvals" / f"{aid}.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    item = json.loads(path.read_text())
    item["created_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(item))
    assert client.get("/api/approvals").json()["counts"]["total"] == 1   # kept while max age is 0
    ctx.settings.update({"write_hold_max_age_days": 7})
    assert client.get("/api/approvals").json()["counts"]["total"] == 0 and not path.exists()


def test_holds_are_visible_in_status(svc, writer):
    client, ctx = svc
    holds(ctx, write_hold_count_over=5, write_hold_window_hours=24)
    h = client.get("/api/status").json()["writes"]["holds"]
    assert h["count_over"] == 5 and h["window_hours"] == 24 and h["held"] == 0
    assert {"approvals", "login_link"} <= set(client.get("/api/version").json()["features"])


def test_the_hold_rules_are_the_admins(svc):
    client, ctx = svc
    key = make_key(ctx, ["read", "settings"])
    r = client.put("/api/settings", json={"write_hold_count_over": 0}, headers=auth(key))
    assert r.status_code == 403 and r.json()["reason"] == "not_admin"


def test_change_percent():
    assert change_percent("a b c d", "a b c d") == 0.0
    assert change_percent("a b c d", "w x y z") == 100.0
    assert 0 < change_percent("a b c d", "a b c e") < 50


# ---- one-off sign-in links ----
def test_a_sign_in_link_works_once_with_the_keys_scopes(svc):
    client, ctx = svc
    approver = ctx.auth.create_key("FunHoard approvals", ["read", "approve"],
                                   ctx.auth.get_user_by_name("root")["id"])[1]
    r = client.post("/api/auth/login-link", json={"next": "/approvals"}, headers=auth(approver))
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert "/login-link#" in url and r.json()["next"] == "/approvals" and r.json()["ttl_seconds"] == 60
    token = url.split("#", 1)[1]
    rows = ctx.auth.db.all("SELECT * FROM login_links")
    assert len(rows) == 1 and token not in json.dumps(rows)                # only a digest is kept
    page = client.get("/login-link", headers={"Authorization": ""})
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    ex = client.post("/api/auth/login-link/exchange", json={"token": token}, headers={"Authorization": ""})
    assert ex.status_code == 200 and ex.json()["next"] == "/approvals"
    me = client.get("/api/auth/me", headers=auth(ex.json()["token"])).json()
    assert me["kind"] == "user" and set(me["scopes"]) == {"read", "approve"}   # never more than the key
    assert client.get("/api/admin/settings", headers=auth(ex.json()["token"])).status_code == 403
    again = client.post("/api/auth/login-link/exchange", json={"token": token}, headers={"Authorization": ""})
    assert again.status_code == 401 and again.json()["reason"] == "link_invalid"


def test_a_sign_in_link_needs_admin_or_approve_and_a_local_next(svc):
    client, ctx = svc
    writer_key = make_key(ctx, ["read", "write"])
    r = client.post("/api/auth/login-link", json={}, headers=auth(writer_key))
    assert r.status_code == 403
    for bad in ("https://evil.example/", "//evil.example/x", "approvals", "/\\evil"):
        r = client.post("/api/auth/login-link", json={"next": bad})
        assert r.status_code == 400, bad
    assert client.post("/api/auth/login-link").json()["next"] == "/"


def test_a_sign_in_link_runs_out(svc):
    client, ctx = svc
    token = client.post("/api/auth/login-link", json={}).json()["url"].split("#", 1)[1]
    ctx.auth.db.run("UPDATE login_links SET expires_at = 0")
    r = client.post("/api/auth/login-link/exchange", json={"token": token}, headers={"Authorization": ""})
    assert r.status_code == 401


def test_the_approvals_page_is_served(svc):
    client, ctx = svc
    r = client.get("/approvals")
    assert r.status_code == 200 and 'id="tab-approvals"' in r.text


def test_the_note_text_reader_uses_the_export(svc, export_root):
    client, ctx = svc
    entry = ctx._note_entry(NOTE)
    assert ctx._note_text(entry).startswith("# Scones")
    gone = "/api/notes/" + quote("x-coredata://TEST/ICNote/zzz", safe="")
    assert client.put(gone, json=body()).status_code in (403, 404)
