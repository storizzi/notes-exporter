"""Auth: setup, sessions, API keys, scopes, credential refusal, last admin."""

import pytest
from fastapi.testclient import TestClient

from notes_service.app import create_app

from .conftest import PASSWORD, fake_permissions, make_key


@pytest.fixture
def fresh(make_config):
    config = make_config()
    app = create_app(config, fake_permissions(config))
    return app


def test_setup_only_on_loopback_and_only_once(fresh):
    with TestClient(fresh, client=("192.168.1.20", 4000)) as remote:
        assert remote.get("/api/setup").json() == {"needed": True, "allowed_here": False}
        assert remote.post("/api/setup", json={"username": "a", "password": PASSWORD}).status_code == 403
    with TestClient(fresh, client=("127.0.0.1", 4000)) as local:
        # A reverse proxy on this Mac makes a remote client look local: refuse forwarded requests.
        r = local.post("/api/setup", json={"username": "a", "password": PASSWORD},
                       headers={"X-Forwarded-For": "8.8.8.8"})
        assert r.status_code == 403
        r = local.post("/api/setup", json={"username": "a", "password": "short"})
        assert r.status_code == 400
        r = local.post("/api/setup", json={"username": "admin1", "password": PASSWORD})
        assert r.status_code == 201 and r.json()["user"]["role"] == "admin" and r.json()["token"]
        assert local.post("/api/setup", json={"username": "b", "password": PASSWORD}).status_code == 409
        assert local.get("/api/setup").json()["needed"] is False


def test_health_is_public(fresh):
    with TestClient(fresh) as c:
        h = c.get("/api/health").json()
        assert h["service"] == "notes-exporter" and h["api_version"] == 1 and h["manifest_version"] == 1
        assert "version" in h and "platform" in h


def test_unauthenticated_is_401(service):
    client, _ = service
    del client.headers["Authorization"]
    r = client.get("/api/status")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/api/status", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer ne_notakey"}).status_code == 401


@pytest.mark.parametrize("param", ["token", "apikey", "api_key", "access_token", "TOKEN"])
def test_credentials_in_query_string_refused(service, param):
    client, ctx = service
    key = make_key(ctx, ["read"])
    r = client.get(f"/api/status?{param}={key}")
    assert r.status_code == 400 and "URL" in r.json()["detail"]
    r = client.get(f"/api/files/x?{param}=1")
    assert r.status_code == 400


def test_login_logout_me(service):
    client, ctx = service
    me = client.get("/api/auth/me").json()
    assert me["username"] == "root" and set(me["scopes"]) == {"read", "run", "settings", "write", "admin"}
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limited(service):
    client, ctx = service
    for _ in range(3):
        assert client.post("/api/auth/login", json={"username": "root", "password": "wrong-one"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "root", "password": PASSWORD})
    assert r.status_code == 429


def test_unknown_user_login_401(service):
    client, _ = service
    assert client.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD}).status_code == 401


def test_api_key_header_forms_and_scopes(service):
    client, ctx = service
    del client.headers["Authorization"]
    read = make_key(ctx, ["read"])
    assert client.get("/api/status", headers={"Authorization": f"Bearer {read}"}).status_code == 200
    assert client.get("/api/status", headers={"X-API-Key": read}).status_code == 200
    r = client.post("/api/runs", json={}, headers={"X-API-Key": read})
    assert r.status_code == 403 and "run" in r.json()["detail"]
    assert client.get("/api/admin/settings", headers={"X-API-Key": read}).status_code == 403
    run = make_key(ctx, ["run"])
    assert client.get("/api/status", headers={"X-API-Key": run}).status_code == 403
    admin = make_key(ctx, ["admin"])
    assert client.get("/api/admin/settings", headers={"X-API-Key": admin}).status_code == 200


def test_api_key_created_once_stored_hashed(service):
    client, ctx = service
    r = client.post("/api/admin/api-keys", json={"name": "FunHoard", "scopes": ["read", "run"]})
    assert r.status_code == 201
    body = r.json()
    key = body["key"]
    assert key.startswith("ne_") and len(key) > 40
    assert body["api_key"]["prefix"] == key[:10] and body["api_key"]["scopes"] == ["read", "run"]
    listed = client.get("/api/admin/api-keys").json()["api_keys"]
    assert all("key" not in k and "key_hash" not in k for k in listed)
    assert key not in ctx.config.auth_db.read_bytes().decode("latin-1")
    # last_used_at is filled in on use
    admin_auth = client.headers.pop("Authorization")
    client.get("/api/status", headers={"Authorization": f"Bearer {key}"})
    client.headers["Authorization"] = admin_auth
    (k,) = [k for k in client.get("/api/admin/api-keys").json()["api_keys"] if k["name"] == "FunHoard"]
    assert k["last_used_at"]
    # revoke
    assert client.delete(f"/api/admin/api-keys/{k['id']}").status_code == 200
    assert client.get("/api/status", headers={"X-API-Key": key, "Authorization": ""}).status_code == 401
    assert client.delete(f"/api/admin/api-keys/{k['id']}").status_code == 404


def test_bad_scopes_and_expired_key(service):
    client, ctx = service
    assert client.post("/api/admin/api-keys", json={"name": "x", "scopes": ["root"]}).status_code == 422
    assert client.post("/api/admin/api-keys", json={"name": "x", "scopes": []}).status_code == 400
    assert client.post("/api/admin/api-keys", json={"name": "x", "scopes": ["read"],
                                                    "expires_at": "2001-01-01T00:00:00Z"}).status_code == 400
    del client.headers["Authorization"]
    record, key = ctx.auth.create_key("soon", ["read"], ctx.auth.get_user_by_name("root")["id"],
                                      "2999-01-01T00:00:00+00:00")
    assert client.get("/api/status", headers={"X-API-Key": key}).status_code == 200
    ctx.auth.db.run("UPDATE api_keys SET expires_at='2001-01-01T00:00:00+00:00' WHERE id=?", (record["id"],))
    assert client.get("/api/status", headers={"X-API-Key": key}).status_code == 401


def test_reader_role(service):
    client, ctx = service
    assert client.post("/api/admin/users", json={"username": "kid", "password": PASSWORD}).status_code == 201
    t = client.post("/api/auth/login", json={"username": "kid", "password": PASSWORD}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/status", headers=h).status_code == 200
    assert client.get("/api/admin/users", headers=h).status_code == 403
    # A reader can't own an admin key, and a key keeps no more than its owner's role allows.
    kid = ctx.auth.get_user_by_name("kid")
    with pytest.raises(Exception):
        ctx.auth.create_key("x", ["admin"], kid["id"])
    _, key = ctx.auth.create_key("x", ["read", "run"], ctx.auth.get_user_by_name("root")["id"])
    ctx.auth.create_user("second", PASSWORD, "admin")
    ctx.auth.set_role(ctx.auth.get_user_by_name("root")["id"], "reader")
    # root is now a reader: its key still works for read, and nothing it holds grants admin
    assert client.get("/api/status", headers={"X-API-Key": key}).status_code == 200


def test_last_admin_protected(service):
    client, ctx = service
    root = ctx.auth.get_user_by_name("root")
    r = client.delete(f"/api/admin/users/{root['id']}")
    assert r.status_code == 409 and "last admin" in r.json()["detail"]
    r = client.patch(f"/api/admin/users/{root['id']}", json={"role": "reader"})
    assert r.status_code == 409
    other = client.post("/api/admin/users", json={"username": "two", "password": PASSWORD, "role": "admin"}).json()
    assert client.patch(f"/api/admin/users/{root['id']}", json={"role": "reader"}).status_code == 200
    t = client.post("/api/auth/login", json={"username": "two", "password": PASSWORD}).json()["token"]
    client.headers["Authorization"] = f"Bearer {t}"
    assert client.delete(f"/api/admin/users/{other['id']}").status_code == 409  # now the only admin
    assert client.delete("/api/admin/users/nope").status_code == 404


def test_password_reset_signs_out_and_removal_drops_keys(service):
    client, ctx = service
    u = client.post("/api/admin/users", json={"username": "u1", "password": PASSWORD}).json()
    t = client.post("/api/auth/login", json={"username": "u1", "password": PASSWORD}).json()["token"]
    _, key = ctx.auth.create_key("k", ["read"], u["id"])
    assert client.patch(f"/api/admin/users/{u['id']}", json={"password": "another long one"}).status_code == 200
    assert client.get("/api/status", headers={"Authorization": f"Bearer {t}"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "u1", "password": "another long one"}).status_code == 200
    assert client.patch(f"/api/admin/users/{u['id']}", json={"password": "x"}).status_code == 400
    assert client.post("/api/admin/users", json={"username": "u1", "password": PASSWORD}).status_code == 409
    assert client.delete(f"/api/admin/users/{u['id']}").status_code == 200
    del client.headers["Authorization"]
    assert client.get("/api/status", headers={"X-API-Key": key}).status_code == 401


def test_change_own_password(service):
    client, _ = service
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "a new password"}).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a new password"}).status_code == 200


def test_password_length_limits(service):
    client, _ = service
    long = "é" * 40  # 80 bytes: past bcrypt's 72
    assert client.post("/api/admin/users", json={"username": "lp", "password": long}).status_code == 400
    assert client.post("/api/admin/users", json={"username": "bad name!", "password": PASSWORD}).status_code == 400


def test_security_headers_and_ui(service):
    client, _ = service
    r = client.get("/")
    assert r.status_code == 200 and "Notes Exporter" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/nope").status_code == 404
    assert client.get("/docs").status_code == 404


def test_settings_scope(service, tmp_path):
    client, ctx = service
    del client.headers["Authorization"]
    read = make_key(ctx, ["read", "run"])
    assert client.get("/api/settings", headers={"X-API-Key": read}).status_code == 403
    assert client.put("/api/settings", json={"formats": ["md"]}, headers={"X-API-Key": read}).status_code == 403
    key = make_key(ctx, ["read", "settings"])
    h = {"X-API-Key": key}
    body = client.get("/api/settings", headers=h).json()
    assert body["read_only"] == ["export_root", "allow_writes"] and body["settings"]["formats"] == ["html"]
    root = body["settings"]["export_root"]
    # It changes what it may, merged like the admin endpoint; the schedule merges too.
    r = client.put("/api/settings", json={"formats": ["html", "md", "pdf"], "prune_deleted": False,
                                          "schedule": {"enabled": True, "daily_at": "00:13"}}, headers=h)
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["formats"] == ["html", "md", "pdf"] and s["prune_deleted"] is False
    assert s["schedule"] == {"enabled": True, "interval_minutes": None, "daily_at": "00:13"}
    # Sending export_root back unchanged is fine; moving it is not.
    assert client.put("/api/settings", json={"export_root": root, "tags": True}, headers=h).status_code == 200
    r = client.put("/api/settings", json={"export_root": str(tmp_path / "elsewhere")}, headers=h)
    assert r.status_code == 403 and "export_root" in r.json()["detail"]
    assert ctx.settings.load().export_root == root
    # Invalid values are 422, as on the admin endpoint; nothing else is reachable with this scope.
    assert client.put("/api/settings", json={"formats": ["exe"]}, headers=h).status_code == 422
    assert client.put("/api/settings", json={"nope": 1}, headers=h).status_code == 422
    assert client.get("/api/admin/settings", headers=h).status_code == 403
    assert client.get("/api/admin/api-keys", headers=h).status_code == 403
    # An admin key includes the settings scope, and may move the export.
    admin = make_key(ctx, ["admin"])
    assert client.get("/api/settings", headers={"X-API-Key": admin}).status_code == 200
    r = client.put("/api/settings", json={"export_root": str(tmp_path / "elsewhere")}, headers={"X-API-Key": admin})
    assert r.status_code == 200, r.text


def test_reader_cannot_own_a_settings_key(service):
    client, ctx = service
    ctx.auth.create_user("kid", PASSWORD, "reader")
    with pytest.raises(Exception):
        ctx.auth.create_key("x", ["settings"], ctx.auth.get_user_by_name("kid")["id"])
