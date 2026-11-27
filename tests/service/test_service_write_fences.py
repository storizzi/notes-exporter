"""1.7.0's fences around writing notes: the backup before an update, delete, the mass-change
limit, the features list and backups kept out of exports — all with the fake writer, never Notes."""

import json

from notes_service.settings import exporter_args
from notes_service.write_state import WriteState

from .conftest import make_key
from .test_service_writes import NOTE, URL, _edit_manifest, allow, body, calls, svc, writer  # noqa: F401


def state(writer):
    return json.loads(writer.read_text()) if writer.exists() else {}


def test_an_update_backs_the_note_up_first_into_its_folder_path(svc, writer):
    client, ctx = svc
    allow(ctx)
    r = client.put(URL, json=body())
    assert r.status_code == 200, r.text
    backup = state(writer)["backups"][0]
    assert backup["of"] == NOTE and backup["folder"] == ["FunHoard Backups", "Food", "Baking"]
    assert backup["suffix"].startswith(" (before ") and backup["suffix"].endswith(")")
    log = [json.loads(x) for x in (ctx.config.home / "writes.ndjson").read_text().splitlines()]
    assert [x["operation"] for x in log] == ["backup", "update"]
    assert log[1]["backup_note_id"] == r.json()["backup_note_id"]


def test_a_failed_backup_stops_the_update(svc, writer):
    client, ctx = svc
    allow(ctx)
    writer.write_text(json.dumps({"fail": "failed", "fail_op": "backup"}))
    r = client.put(URL, json=body())
    assert r.status_code == 502 and r.json()["reason"] == "backup_failed"
    assert "update" not in [c["operation"] for c in calls(writer)]
    assert client.get("/api/writes").json()["limits"]["changes_last_hour"] == 0


def test_skipping_the_backup_needs_the_admin_to_allow_it(svc, writer):
    client, ctx = svc
    allow(ctx)
    r = client.put(URL, json=body(backup="none"))
    assert r.status_code == 403 and r.json()["reason"] == "backup_required" and calls(writer) == []
    ctx.settings.update({"write_backup_required": False})
    r = client.put(URL, json=body(backup="none"))
    assert r.status_code == 200 and r.json()["backup_note_id"] is None
    assert "backup" not in [c["operation"] for c in calls(writer)]


def test_the_fences_are_the_admins(svc):
    client, ctx = svc
    key = make_key(ctx, ["read", "settings"])
    for change in ({"write_backup_required": False}, {"write_max_changes_per_hour": 0}):
        r = client.put("/api/settings", json=change, headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 403 and r.json()["reason"] == "not_admin"


def test_bad_fence_settings_are_refused(svc):
    client, ctx = svc
    admin = make_key(ctx, ["read", "admin"])
    for change in ({"write_backup_folder": "A/B"}, {"write_backup_folder": " "}, {"write_max_changes_per_day": -1}):
        r = client.put("/api/admin/settings", json=change, headers={"Authorization": f"Bearer {admin}"})
        assert r.status_code == 422, change


def test_delete_goes_to_recently_deleted_after_the_checks(svc, writer):
    client, ctx = svc
    allow(ctx)
    assert client.delete(URL).json()["reason"] == "bad_request"
    r = client.delete(URL, params={"base": "2025-12-01T10:00:00+00:00", "export": "false"})
    assert r.status_code == 409 and r.json()["reason"] == "export"
    writer.write_text(json.dumps({"modified": {NOTE: "2026-01-05T08:00:00+00:00"}}))
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00+00:00", "export": "false"})
    assert r.status_code == 409 and r.json()["reason"] == "notes"
    writer.write_text("{}")
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00+00:00", "export": "false"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True and r.json()["recently_deleted"] is True
    assert r.json()["backup_note_id"] is None
    assert state(writer)["deleted"] == [NOTE] and "backups" not in state(writer)


def test_delete_with_a_backup_and_refused_for_locked_notes(svc, writer, export_root):
    client, ctx = svc
    allow(ctx)
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00Z", "backup": "folder", "export": "false"})
    assert r.status_code == 200 and r.json()["backup_note_id"] == "x-coredata://TEST/ICNote/backup1"
    assert [c["operation"] for c in calls(writer)] == ["modified", "backup", "delete"]
    _edit_manifest(export_root, locked=True)
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00Z", "force": "true"})
    assert r.status_code == 409 and r.json()["reason"] == "locked"


def test_delete_needs_the_write_scope(svc, writer):
    client, ctx = svc
    allow(ctx)
    other = make_key(ctx, ["read", "run", "settings"])
    r = client.delete(URL, params={"base": "x"}, headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 403 and calls(writer) == []


def test_a_delete_exports_its_folder(svc, writer):
    client, ctx = svc
    allow(ctx)
    r = client.delete(URL, params={"base": "2026-01-02T10:00:00Z"})
    assert r.status_code == 200 and r.json()["run"]["folders"] == ["Food/Baking"]


def test_the_mass_change_limit_holds_across_a_restart(svc, writer):
    client, ctx = svc
    allow(ctx)
    ctx.settings.update({"write_max_changes_per_hour": 2})
    assert client.put(URL, json=body(force=True)).status_code == 200
    new = {"account": "iCloud", "folder_path": ["Food"], "markdown": "# Pancakes\n", "export": False}
    assert client.post("/api/notes", json=new).status_code == 201
    r = client.put(URL, json=body(force=True))
    assert r.status_code == 429 and r.json()["reason"] == "write_limit"
    assert r.json()["window"] == "hour" and 3500 <= r.json()["retry_after"] <= 3600
    assert r.headers["retry-after"] == str(r.json()["retry_after"])
    assert client.get("/api/status").json()["writes"]["limits"]["changes_last_hour"] == 2
    # What a restarted service reads: the same count from write_state.json.
    assert WriteState(ctx.config).check(2, 0)["window"] == "hour"
    ctx.settings.update({"write_max_changes_per_hour": 0})
    assert client.put(URL, json=body(force=True)).status_code == 200


def test_the_day_limit(svc, writer):
    client, ctx = svc
    allow(ctx)
    ctx.settings.update({"write_max_changes_per_hour": 0, "write_max_changes_per_day": 1})
    assert client.put(URL, json=body(force=True)).status_code == 200
    r = client.delete(URL, params={"base": "x", "force": "true"})
    assert r.status_code == 429 and r.json()["window"] == "day"
    assert client.get("/api/status").json()["writes"]["limits"]["limited_until"]


def test_features_are_advertised(svc):
    client, ctx = svc
    for path in ("/api/health", "/api/version"):
        assert {"write", "write_backup", "delete", "write_limit"} <= set(client.get(path).json()["features"])


def test_backup_folders_stay_out_of_exports(svc, writer, tmp_path):
    client, ctx = svc
    allow(ctx)
    assert client.put(URL, json=body()).status_code == 200
    argv = exporter_args(ctx.config, ctx.settings.load(), json_log=tmp_path / "x.ndjson")
    excluded = argv[argv.index("--exclude-folders") + 1].split(",")
    assert {"Recently Deleted", "FunHoard Backups", "FunHoard Backups/Food",
            "FunHoard Backups/Food/Baking"} <= set(excluded)
    ctx.settings.update({"write_backup_export": True})
    argv = exporter_args(ctx.config, ctx.settings.load(), json_log=tmp_path / "x.ndjson")
    assert argv[argv.index("--exclude-folders") + 1] == "Recently Deleted"
