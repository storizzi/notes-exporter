"""EPUB output: one book per note (convert_to_epub.py) and per folder
(build_epub_books.py), unit-level and through exportnotes.zsh with the fake
osascript (Apple Notes is never touched)."""

import base64
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from epub_builder import (BookMeta, Chapter, ImageStore, build_epub, html_to_xhtml,  # noqa: E402
                          identifier_urn, write_if_changed)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG2 = PNG + b"\x00"   # different bytes, same type
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"


def check_structure(data: bytes) -> dict:
    """Assert the container rules and return {name: bytes}."""
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    assert infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED
    assert infos[0].extra == b"" and z.read("mimetype") == b"application/epub+zip"
    # the raw bytes: "mimetype" right after the first local header (offset 30)
    assert data[30:38] == b"mimetype" and data[38:58] == b"application/epub+zip"
    files = {i.filename: z.read(i.filename) for i in infos}
    container = ElementTree.fromstring(files["META-INF/container.xml"])
    rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    assert rootfile.get("full-path") == "OEBPS/content.opf"
    opf = ElementTree.fromstring(files["OEBPS/content.opf"])
    items = {i.get("href"): i for i in opf.iter(OPF + "item")}
    for name in files:
        if name.startswith("OEBPS/") and name != "OEBPS/content.opf":
            assert name[len("OEBPS/"):] in items, f"{name} not in the OPF manifest"
    for href in items:
        assert "OEBPS/" + href in files, f"manifest lists missing {href}"
    for name, body in files.items():
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            ElementTree.fromstring(body)   # well-formed XML
    assert items["nav.xhtml"].get("properties") == "nav"
    assert opf.find(f"{OPF}spine").get("toc") == "ncx"
    return files


def opf_of(files):
    return ElementTree.fromstring(files["OEBPS/content.opf"])


def note_book(html: str, base: Path, warnings=None, title="Scones"):
    images = ImageStore()
    body = html_to_xhtml(html, base, images, (warnings if warnings is not None else []).append)
    meta = BookMeta(identifier_urn("", "x-coredata://S/ICNote/p1"), title, "en",
                    modified="2026-03-05T07:08:09+00:00", created="2026-01-01T10:00:00+00:00",
                    subjects=["iCloud", "Food/Baking"])
    return build_epub(meta, [Chapter("note", title, body, "note.xhtml")], images)


# ── unit: one note ──────────────────────────────────────────────────────

def test_note_epub_structure_and_images_with_spaces(tmp_path):
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "My photo (1).png").write_bytes(PNG)
    (att / "second.png").write_bytes(PNG2)
    html = ('<html><head><title>x</title><style>p{}</style></head><body><div><h1>Scones</h1>'
            '<img src="attachments/My%20photo%20%281%29.png"><br><font color="red" face="Arial">red</font>'
            '<img src="attachments/second.png" onclick="evil()"><script>alert(1)</script>'
            '<p>caf&eacute; &nbsp; &amp; <b>bold<i>nested</b></i></p><a href="attachments/second.png">file</a>'
            '<input checked></div></body></html>')
    files = check_structure(note_book(html, tmp_path))
    opf = opf_of(files)
    assert opf.find(f".//{DC}identifier").text == "urn:x-apple-notes:x-coredata%3A%2F%2FS%2FICNote%2Fp1"
    assert opf.find(f".//{DC}title").text == "Scones"
    assert opf.find(f".//{DC}date").text == "2026-03-05T07:08:09Z"
    assert [s.text for s in opf.iter(DC + "subject")] == ["iCloud", "Food/Baking"]
    assert opf.find(f".//{DC}language").text == "en"
    metas = {m.get("property"): m.text for m in opf.iter(OPF + "meta")}
    assert metas["dcterms:modified"] == "2026-03-05T07:08:09Z" and metas["dcterms:created"] == "2026-01-01T10:00:00Z"
    images = [i for i in opf.iter(OPF + "item") if i.get("media-type") == "image/png"]
    assert len(images) == 2
    note = files["OEBPS/note.xhtml"].decode()
    for img in images:
        assert f'src="{img.get("href")}"' in note
    assert "<script" not in note and "onclick" not in note and "<font" not in note and "color: red" in note
    assert "café" in note and "&nbsp;" not in note
    assert 'href="attachments' not in note
    assert b"toc.ncx" and "Scones" in files["OEBPS/nav.xhtml"].decode()


def test_shared_image_stored_once(tmp_path):
    (tmp_path / "a.png").write_bytes(PNG)
    (tmp_path / "b.png").write_bytes(PNG)
    files = check_structure(note_book('<img src="a.png"><img src="b.png">', tmp_path))
    assert len([n for n in files if n.startswith("OEBPS/images/")]) == 1


def test_note_without_images(tmp_path):
    files = check_structure(note_book("<div><h1>Plain</h1><div>Just text</div></div>", tmp_path, title="Plain"))
    assert not any(n.startswith("OEBPS/images/") for n in files)
    assert "Just text" in files["OEBPS/note.xhtml"].decode()


def test_missing_and_remote_images_are_dropped_with_a_warning(tmp_path):
    warnings = []
    files = check_structure(note_book('<p>a<img src="attachments/gone.png">b<img src="https://x.test/i.png"></p>',
                                      tmp_path, warnings))
    note = files["OEBPS/note.xhtml"].decode()
    assert "<img" not in note and "ab" in note.replace("\n", "")
    assert any("gone.png" in w and "missing" in w for w in warnings)
    assert any("not a local file" in w for w in warnings)


def test_inline_data_image(tmp_path):
    src = "data:image/png;base64," + base64.b64encode(PNG).decode()
    files = check_structure(note_book(f'<img src="{src}">', tmp_path))
    assert [n for n in files if n.startswith("OEBPS/images/")]


def test_deterministic_and_write_if_changed(tmp_path):
    (tmp_path / "a.png").write_bytes(PNG)
    one = note_book('<img src="a.png"><p>x</p>', tmp_path)
    two = note_book('<img src="a.png"><p>x</p>', tmp_path)
    assert one == two
    out = tmp_path / "out" / "n.epub"
    assert write_if_changed(out, one) is True
    mtime = out.stat().st_mtime_ns
    assert write_if_changed(out, two) is False and out.stat().st_mtime_ns == mtime


def test_unparseable_markup_falls_back_to_text(tmp_path):
    files = check_structure(note_book("<p>ok</p><x:weird a='1'>t</x:weird><p>\x01bad\x02</p>", tmp_path))
    assert "ok" in files["OEBPS/note.xhtml"].decode()


# ── through exportnotes.zsh with the fake osascript ─────────────────────

SCRIPT = REPO / "exportnotes.zsh"
needs_zsh = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("zsh"),
                               reason="exportnotes.zsh needs macOS and zsh")


def _img(data=PNG):
    return f'<img src="data:image/png;base64,{base64.b64encode(data).decode()}">'


def _note(nid, title, folder=("Food",), modified="2026-03-05T07:08:09", body="", **extra):
    note = {"account": "iCloud", "folder": list(folder), "folder_id": "-".join(folder), "id": nid,
            "title": title, "modified": modified, "created": "2026-01-0%dT10:00:00" % (nid % 9 + 1),
            "html": f"<div><h1>{title}</h1><div>Body of {title}</div>{body}</div>", "text": f"{title}\nBody"}
    note.update(extra)
    return note


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "osascript"
    fake.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{REPO / 'tests' / 'fake_osascript.py'}' \"$@\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    assert shutil.which("osascript", path=f"{bin_dir}:{os.environ['PATH']}") == str(fake)
    library = tmp_path / "library.json"
    e = {k: v for k, v in os.environ.items() if not k.startswith("NOTES_EXPORT_")}
    e.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_NOTES_LIBRARY=str(library),
             NOTES_EXPORT_SKIP_PERMISSION_CHECK="true", HOME=str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return {"env": e, "library": library, "root": tmp_path / "export"}


def write_library(env, notes):
    env["library"].write_text(json.dumps({"notes": notes, "fail": None}))


def run(env, *args):
    cmd = ["zsh", str(SCRIPT), "--python", sys.executable, "--root-dir", str(env["root"]),
           "--filename-format", "&title", "--folder-hierarchy", "--json-log", *args]
    r = subprocess.run(cmd, env=env["env"], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-3000:]
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


def manifest(env):
    return json.loads((env["root"] / "manifest.json").read_text())


@needs_zsh
def test_convert_epub_end_to_end(env):
    write_library(env, [_note(1, "Scones", ("Food", "Baking"), body=_img()), _note(2, "Plain")])
    events = run(env, "--convert-epub")
    stages = {(e["stage"], e["status"]) for e in events if e["type"] == "stage"}
    assert ("epub", "finished") in stages
    assert next(e for e in events if e["type"] == "start")["formats"][-1] == "epub"
    m = manifest(env)
    notes = {n["title"]: n for n in m["notes"]}
    out = notes["Scones"]["outputs"]["epub"]
    assert out["path"] == "epub/iCloud/Food/Baking/Scones.epub"
    files = check_structure((env["root"] / out["path"]).read_bytes())
    assert len([n for n in files if n.startswith("OEBPS/images/")]) == 1
    assert notes["Plain"]["outputs"]["epub"]["sha256"]
    # incremental: nothing changed -> the same files, not rewritten
    mtime = (env["root"] / out["path"]).stat().st_mtime_ns
    run(env, "--convert-epub")
    m2 = manifest(env)
    assert {n["title"]: n["outputs"]["epub"]["sha256"] for n in m2["notes"]} == \
        {t: n["outputs"]["epub"]["sha256"] for t, n in notes.items()}
    assert (env["root"] / out["path"]).stat().st_mtime_ns == mtime
    # rename: the old epub goes, previous_outputs says so
    write_library(env, [_note(1, "Cheese Scones", ("Food", "Baking"), modified="2026-03-07T07:00:00", body=_img()),
                        _note(2, "Plain")])
    run(env, "--convert-epub")
    m3 = {n["id"]: n for n in manifest(env)["notes"]}
    renamed = next(n for n in m3.values() if n["title"] == "Cheese Scones")
    assert renamed["outputs"]["epub"]["path"].endswith("Cheese-Scones.epub")
    assert renamed["previous_outputs"]["epub"] == out["path"]
    assert not (env["root"] / out["path"]).exists()


@needs_zsh
def test_prune_deleted_removes_epub(env):
    write_library(env, [_note(1, "Keep"), _note(2, "Gone")])
    run(env, "--convert-epub")
    gone = env["root"] / "epub/iCloud/Food/Gone.epub"
    assert gone.exists()
    write_library(env, [_note(1, "Keep")])
    run(env, "--convert-epub", "--prune-deleted")
    assert not gone.exists()
    d = manifest(env)["deleted"][0]
    assert "epub/iCloud/Food/Gone.epub" in d["removed_outputs"]


# ── books per folder ────────────────────────────────────────────────────

def book_titles(files):
    nav = files["OEBPS/nav.xhtml"].decode()
    root = ElementTree.fromstring(nav)
    ns = "{http://www.w3.org/1999/xhtml}"
    return [a.text for a in root.iter(ns + "a")]


def books(env):
    return {"/".join(b["folder_path"]): b for b in manifest(env)["books"]}


LIB = [
    _note(1, "Bread", ("Food",), modified="2026-03-01T07:00:00"),
    _note(2, "Apple pie", ("Food",), modified="2026-03-04T07:00:00", body=_img()),
    _note(3, "Scones", ("Food", "Baking"), modified="2026-03-02T07:00:00", body=_img()),
    _note(4, "Rolls", ("Food", "Baking"), modified="2026-03-03T07:00:00", body=_img()),   # same image as 3
    _note(5, "Todo", ("Work",), modified="2026-03-05T07:00:00"),
    _note(6, "Secret", ("Work",)),
]


def locked(lib, title):
    return [dict(n, locked=True) if n["title"] == title else n for n in lib]


@needs_zsh
def test_books_separate_membership_and_order(env):
    write_library(env, LIB)
    run(env, "--epub-books", "folder")
    write_library(env, locked(LIB, "Secret"))   # exported once, now locked: left out of the book
    events = run(env, "--epub-books", "folder")
    assert ("books", "finished") in {(e["stage"], e["status"]) for e in events if e["type"] == "stage"}
    b = books(env)
    assert set(b) == {"Food", "Food/Baking", "Work"}
    food = b["Food"]
    assert food["path"] == "epub-books/iCloud/Food.epub" and food["nested_folders"] == []
    assert food["id"] == f"{food['account_id']}/{food['folder_id']}"
    files = check_structure((env["root"] / food["path"]).read_bytes())
    assert book_titles(files) == ["Apple pie", "Bread"]          # modified, newest first
    ids = {n["title"]: n["id"] for n in manifest(env)["notes"]}
    assert food["notes"] == [ids["Apple pie"], ids["Bread"]]
    baking = check_structure((env["root"] / b["Food/Baking"]["path"]).read_bytes())
    assert len([n for n in baking if n.startswith("OEBPS/images/")]) == 1   # shared image once
    assert b["Work"]["skipped_notes"] == 1 and b["Work"]["notes"] == [ids["Todo"]]
    assert b["Work"]["changed_this_run"] and not b["Food"]["changed_this_run"]
    assert manifest(env)["run"]["counts"]["books"] == 3


@needs_zsh
def test_books_title_and_created_order(env):
    write_library(env, LIB)
    run(env, "--epub-books", "folder", "--epub-book-order", "title")
    files = check_structure((env["root"] / books(env)["Food"]["path"]).read_bytes())
    assert book_titles(files) == ["Apple pie", "Bread"]
    run(env, "--epub-books", "folder", "--epub-book-order", "created")
    files = check_structure((env["root"] / books(env)["Food/Baking"]["path"]).read_bytes())
    assert book_titles(files) == ["Rolls", "Scones"]   # created 2026-01-05 then 01-04


@needs_zsh
def test_books_nested(env):
    write_library(env, LIB)
    run(env, "--epub-books", "folder", "--epub-book-subfolders", "nested")
    b = books(env)
    assert set(b) == {"Food", "Work"}
    food = b["Food"]
    assert [f.rsplit("/", 1)[-1] for f in food["nested_folders"]] == ["Food-Baking"]
    files = check_structure((env["root"] / food["path"]).read_bytes())
    nav = ElementTree.fromstring(files["OEBPS/nav.xhtml"])
    ns = "{http://www.w3.org/1999/xhtml}"
    top = nav.find(f".//{ns}nav/{ns}ol")
    labels = [(li.find(ns + "a") if li.find(ns + "a") is not None else li.find(ns + "span")).text for li in top]
    assert labels == ["Apple pie", "Bread", "Baking"]
    part = top[2]
    assert [a.text for a in part.iter(ns + "a")] == ["Rolls", "Scones"]
    ncx = ElementTree.fromstring(files["OEBPS/toc.ncx"])
    assert len(list(ncx.iter("{http://www.daisy.org/z3986/2005/ncx/}navPoint"))) == 5
    assert len(food["notes"]) == 4


@needs_zsh
def test_books_rebuilt_only_on_change_and_removed_with_folder(env):
    write_library(env, LIB)
    run(env, "--epub-books", "folder")
    first = books(env)
    paths = {k: env["root"] / v["path"] for k, v in first.items()}
    mtimes = {k: p.stat().st_mtime_ns for k, p in paths.items()}
    run(env, "--epub-books", "folder")
    again = books(env)
    assert not any(b["changed_this_run"] for b in again.values())
    assert {k: p.stat().st_mtime_ns for k, p in paths.items()} == mtimes
    # edit one note in Food/Baking: only that book changes
    lib = [dict(n) for n in LIB]
    lib[2]["html"] = lib[2]["html"].replace("Body of Scones", "Body of better Scones")
    lib[2]["modified"] = "2026-03-08T07:00:00"
    write_library(env, lib)
    run(env, "--epub-books", "folder")
    third = books(env)
    assert third["Food/Baking"]["changed_this_run"] and third["Food/Baking"]["sha256"] != first["Food/Baking"]["sha256"]
    assert not third["Food"]["changed_this_run"] and not third["Work"]["changed_this_run"]
    assert paths["Food"].stat().st_mtime_ns == mtimes["Food"]
    assert third["Food/Baking"]["notes"][0] == next(n["id"] for n in manifest(env)["notes"] if n["title"] == "Scones")
    # Work's only exportable note deleted, the other one locked: the book goes, with a tombstone
    write_library(env, locked([n for n in lib if n["title"] != "Todo"], "Secret"))
    run(env, "--epub-books", "folder")
    m = manifest(env)
    assert "Work" not in {"/".join(b["folder_path"]) for b in m["books"]}
    assert not paths["Work"].exists()
    (tomb,) = m["deleted_books"]
    assert tomb["id"] == first["Work"]["id"] and tomb["path"] == first["Work"]["path"] and tomb["deleted_at"]


@pytest.mark.skipif(not shutil.which("epubcheck"), reason="epubcheck not installed (brew install epubcheck)")
def test_epubcheck_validates(tmp_path):
    (tmp_path / "a b (1).png").write_bytes(PNG)
    data = note_book('<div><h1>T</h1><img src="a%20b%20%281%29.png"><font color="red">x</font></div>', tmp_path)
    out = tmp_path / "note.epub"
    out.write_bytes(data)
    r = subprocess.run(["epubcheck", str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
