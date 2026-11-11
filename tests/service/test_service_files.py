"""Manifest (ETag/304), note queries and files (containment, Range, ETag)."""

import hashlib
import os
from urllib.parse import quote

import pytest

from .fixture_export import PNG, build_export


@pytest.fixture
def exported(service, export_root):
    client, ctx = service
    build_export(export_root)
    return client, ctx, export_root


def test_manifest_404_before_any_export(service):
    client, _ = service
    r = client.get("/api/manifest")
    assert r.status_code == 404 and "detail" in r.json()


def test_manifest_verbatim_with_etag(exported):
    client, _, root = exported
    raw = (root / "manifest.json").read_bytes()
    r = client.get("/api/manifest")
    assert r.status_code == 200 and r.content == raw
    assert r.headers["etag"] == '"' + hashlib.sha256(raw).hexdigest() + '"'
    assert r.headers["content-type"].startswith("application/json")
    r2 = client.get("/api/manifest", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    build_export(root)  # a new run: sequence 2, new ETag
    r3 = client.get("/api/manifest", headers={"If-None-Match": r.headers["etag"]})
    assert r3.status_code == 200 and r3.headers["etag"] != r.headers["etag"]
    assert r3.json()["run"]["sequence"] == 2


def test_notes_filters(exported):
    client, _, root = exported
    all_ = client.get("/api/notes").json()
    assert all_["sequence"] == 1 and len(all_["notes"]) == 3 and all_["deleted"] == []
    assert [n["title"] for n in client.get("/api/notes?folder=Food").json()["notes"]] == ["Scones"]
    assert [n["title"] for n in client.get("/api/notes?folder=Food/Baking").json()["notes"]] == ["Scones"]
    assert len(client.get("/api/notes?folder=Notes").json()["notes"]) == 2
    assert len(client.get("/api/notes?account=iCloud").json()["notes"]) == 3
    assert len(client.get("/api/notes?account=x-coredata://TEST/ICAccount/p1").json()["notes"]) == 3
    assert client.get("/api/notes?account=Other").json()["notes"] == []
    with_deleted = client.get("/api/notes?include_deleted=true").json()
    assert [d["id"] for d in with_deleted["deleted"]] == ["x-coredata://TEST/ICNote/p9"]
    build_export(root)  # nothing changed in run 2
    assert client.get("/api/notes?changed_since_sequence=1").json()["notes"] == []
    assert len(client.get("/api/notes?changed_since_sequence=0").json()["notes"]) == 3
    assert client.get("/api/notes?changed_since_sequence=1&include_deleted=true").json()["deleted"] == []


def test_note_by_encoded_id(exported):
    client, _, _ = exported
    nid = "x-coredata://TEST/ICNote/p2"
    r = client.get("/api/notes/" + quote(nid, safe=""))
    assert r.status_code == 200 and r.json()["title"] == "My Note (draft)"
    assert client.get("/api/notes/" + quote("x-coredata://TEST/ICNote/p9", safe="")).json()["deleted"] is True
    assert client.get("/api/notes/" + quote("x-coredata://TEST/ICNote/p77", safe="")).status_code == 404


def test_file_with_manifest_etag_and_type(exported):
    client, _, root = exported
    rel = "html/iCloud-Baking/attachments/Scones-p1-attachment-001.png"
    r = client.get("/api/files/" + rel)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["etag"] == f'"sha256:{hashlib.sha256(PNG).hexdigest()}"'
    assert r.headers["accept-ranges"] == "bytes"
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get("/api/files/" + rel, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    md = client.get("/api/files/md/iCloud-Baking/Scones-p1.md")
    assert md.headers["content-type"] == "text/markdown; charset=utf-8"


def test_file_with_spaces_and_parentheses(exported):
    client, _, _ = exported
    r = client.get("/api/files/" + quote("html/iCloud-Notes/My Note (draft)-p2.html"))
    assert r.status_code == 200 and "Draft café" in r.text
    assert r.headers["content-type"] == "text/html; charset=utf-8"


def test_file_etag_falls_back_to_size_mtime(exported):
    client, _, root = exported
    p = root / "data" / "extra.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text("{}")
    st = p.stat()
    r = client.get("/api/files/data/extra.json")
    assert r.headers["etag"] == f'"{st.st_size:x}-{st.st_mtime_ns:x}"'
    # a file changed since the manifest was written doesn't get the stale sha
    (root / "html/iCloud-Notes/Shopping-p3.html").write_text("<p>Milk and more milk</p>")
    r = client.get("/api/files/html/iCloud-Notes/Shopping-p3.html")
    assert not r.headers["etag"].startswith('"sha256:')


def test_ranges(exported):
    client, _, _ = exported
    rel = "/api/files/html/iCloud-Baking/attachments/Scones-p1-attachment-001.png"
    r = client.get(rel, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == PNG[:10]
    assert r.headers["content-range"] == f"bytes 0-9/{len(PNG)}" and r.headers["content-length"] == "10"
    r = client.get(rel, headers={"Range": "bytes=100-"})
    assert r.status_code == 206 and r.content == PNG[100:]
    r = client.get(rel, headers={"Range": "bytes=-16"})
    assert r.status_code == 206 and r.content == PNG[-16:]
    r = client.get(rel, headers={"Range": f"bytes={len(PNG)}-"})
    assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(PNG)}"
    r = client.get(rel, headers={"Range": "bytes=0-1,4-5"})
    assert r.status_code == 200 and r.content == PNG   # multi-range: whole file
    r = client.get(rel, headers={"Range": "bytes=0-9", "If-Range": '"stale"'})
    assert r.status_code == 200
    h = client.head(rel)
    assert h.status_code == 200 and h.headers["content-length"] == str(len(PNG)) and h.content == b""


@pytest.mark.parametrize("path", [
    "../state/auth.sqlite", "html/../../state/auth.sqlite", "%2e%2e/state/auth.sqlite",
    "html/%2e%2e/%2e%2e/home", "..%2fstate%2fauth.sqlite",
])
def test_traversal_refused(exported, path):
    client, _, _ = exported
    r = client.get("/api/files/" + path)
    assert r.status_code in (403, 404)
    assert b"SQLite" not in r.content


def test_traversal_is_403(exported):
    client, _, _ = exported
    assert client.get("/api/files/..%2F..%2Fetc%2Fpasswd").status_code == 403
    assert client.get("/api/files/%2Fetc%2Fpasswd").status_code == 403


def test_symlink_out_of_root_refused(exported, tmp_path):
    client, _, root = exported
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    os.symlink(secret, root / "html" / "link.txt")
    r = client.get("/api/files/html/link.txt")
    assert r.status_code == 403 and "private" not in r.text
    inside = root / "html" / "inside.txt"
    os.symlink(root / "html/iCloud-Notes/Shopping-p3.html", inside)
    assert client.get("/api/files/html/inside.txt").status_code == 200


def test_missing_file_and_directory(exported):
    client, _, _ = exported
    assert client.get("/api/files/html/nothing.html").status_code == 404
    assert client.get("/api/files/html").status_code == 404
    assert client.get("/api/files/").status_code in (403, 404)


def test_status(service, export_root):
    client, ctx = service
    s = client.get("/api/status").json()
    assert s["running_run_id"] is None and s["last_run"] is None
    assert s["permission"]["automation"] == "allowed" and s["permission"]["full_disk_access"] is False
    assert s["formats"] == ["html"] and s["schedule"]["enabled"] is False and s["next_run_at"] is None
    assert s["export_root_ok"] is False  # not created yet
    export_root.mkdir()
    assert client.get("/api/status").json()["export_root_ok"] is True
