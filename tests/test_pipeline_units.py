"""Unit tests for the 1.4.0 pipeline pieces: events, permission words,
tracker discovery, pruning, the manifest and image conversion."""

import base64
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_manifest  # noqa: E402
import events  # noqa: E402
import extract_images  # noqa: E402
import notes_permission  # noqa: E402
import prune_deleted  # noqa: E402
from tracker_io import tracker_files, write_json_atomic  # noqa: E402


# ── events ───────────────────────────────────────────────────────────────

@pytest.fixture
def event_pipe(monkeypatch, tmp_path):
    path = tmp_path / "events.jsonl"
    f = open(path, "wb")
    monkeypatch.setenv("NOTES_EXPORT_EVENT_FD", str(f.fileno()))
    events._last_progress.clear()

    def read():
        f.flush()
        return [json.loads(l) for l in path.read_text().splitlines()]
    yield read
    f.close()


def test_emit_is_silent_without_fd(monkeypatch):
    monkeypatch.delenv("NOTES_EXPORT_EVENT_FD", raising=False)
    events.emit("progress", done=1, total=2)  # no error, nothing written
    assert not events.enabled()


def test_progress_is_throttled_but_keeps_first_and_last(event_pipe):
    for i in range(0, 101):
        events.progress("markdown", i, 100)
    got = event_pipe()
    assert got[0]["done"] == 0 and got[-1]["done"] == 100
    assert len(got) < 10
    assert all(e["type"] == "progress" and e["total"] == 100 for e in got)


def test_relay_turns_markers_into_events(event_pipe):
    stderr = io.StringIO()
    stream = io.StringIO("@@PLAN\t2\n"
                         "@@FOLDER\t1\t2\tiCloud\tFood/Baking\t3\n"
                         "@@NOTE\t1\t12\n"
                         "@@NOTE_ERROR\t13\tNotes got an error\\tbadly\n"
                         "ordinary log line\n"
                         "@@FOLDER\t2\t2\tiCloud\tWork\t1\n")
    assert events.relay(stream, stderr) == 0
    got = event_pipe()
    assert got[0] == {**got[0], "type": "plan", "folders": 2}
    progress = [e for e in got if e["type"] == "progress"]
    assert [(e["done"], e["total"]) for e in progress] == [(0, 2), (0, 2), (1, 2), (2, 2)]
    assert progress[1]["folder"] == "Food/Baking"
    errors = [e for e in got if e["type"] == "note_error"]
    assert errors[0]["note_id"] == "13" and errors[0]["message"] == "Notes got an error\tbadly"
    assert "ordinary log line" in stderr.getvalue()


def test_relay_reports_refusal():
    assert events.relay(io.StringIO("execution error: Not authorized to send Apple events "
                                    "to Notes. (-1743)\n"), io.StringIO()) == 3


def test_emit_cli_parses_json_values(event_pipe):
    events.main(["events.py", "emit", "result", "status=ok", "exit_code:=0", "formats:=[\"md\"]"])
    got = event_pipe()[0]
    assert got["status"] == "ok" and got["exit_code"] == 0 and got["formats"] == ["md"]


# ── permission words ─────────────────────────────────────────────────────

@pytest.mark.parametrize("status,word,code", [
    (0, "allowed", 0), (-1744, "prompt", 3), (-1743, "denied", 3),
    (-600, "not-running", 4), (-50, "unknown(-50)", 5)])
def test_permission_words(status, word, code):
    assert notes_permission.describe(status) == (word, code)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_permission_check_never_prompts():
    # Whatever this Mac says, the call returns at once with a known status
    assert isinstance(notes_permission.check(), int)


# ── trackers ─────────────────────────────────────────────────────────────

def test_hidden_json_files_are_not_trackers(tmp_path):
    for name in ("iCloud-Notes.json", ".run_info.json", ".manifest_cache.json"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in tracker_files(tmp_path)] == ["iCloud-Notes.json"]
    assert tracker_files(tmp_path / "missing") == []


# ── prune ────────────────────────────────────────────────────────────────

def _export(tmp_path, records, tracker="iCloud-Food"):
    root = tmp_path / "export"
    for rec in records.values():
        for d, ext in (("raw", ".html"), ("md", ".md")):
            sub = rec.get("subdir", tracker)
            p = root / d / sub / f"{rec['filename']}{ext}"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"{rec['filename']} {d}")
    (root / "data").mkdir(parents=True, exist_ok=True)
    write_json_atomic(root / "data" / f"{tracker}.json", records)
    return root


def test_prune_deleted_keeps_live_and_locally_edited_files(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    root = _export(tmp_path, {
        "1": {"filename": "Live", "fullNoteId": "x/p1"},
        "2": {"filename": "Gone", "deletedDate": "d", "fullNoteId": "x/p2"},
        "3": {"filename": "Edited", "deletedDate": "d", "fullNoteId": "x/p3",
              "markdownHash": "0" * 64},
    })
    att = root / "md/iCloud-Food/attachments/Gone-attachment-001.png"
    att.parent.mkdir(parents=True)
    att.write_bytes(b"png")

    summary = prune_deleted.prune(root, moved=True, deleted=False)
    assert summary["files"] == 0  # --moved alone leaves deleted notes' files

    dry = prune_deleted.prune(root, moved=False, deleted=True, dry_run=True)
    assert (root / "raw/iCloud-Food/Gone.html").exists() and dry["files"] == 4

    summary = prune_deleted.prune(root, moved=False, deleted=True)
    assert not (root / "raw/iCloud-Food/Gone.html").exists()
    assert not att.exists()
    assert (root / "raw/iCloud-Food/Live.html").exists()
    assert (root / "md/iCloud-Food/Edited.md").exists() and summary["kept_edited"] == 1
    data = json.loads((root / "data/iCloud-Food.json").read_text())
    assert "md/iCloud-Food/Gone.md" in data["2"]["prunedOutputs"]
    assert "prunedDate" in data["2"] and "prunedDate" not in data["1"]
    # A second pass does nothing more
    assert prune_deleted.prune(root, moved=False, deleted=True)["files"] == 0


def test_prune_never_removes_a_path_a_live_note_uses(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    root = _export(tmp_path, {
        "1": {"filename": "Same", "fullNoteId": "x/p1"},
        "2": {"filename": "Same", "deletedDate": "d", "fullNoteId": "x/p2"},
    })
    prune_deleted.prune(root, moved=True, deleted=True)
    assert (root / "md/iCloud-Food/Same.md").exists()


# ── manifest ─────────────────────────────────────────────────────────────

def test_manifest_tags_hashes_and_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    root = _export(tmp_path, {
        "1": {"filename": "Tagged", "fullNoteId": "x-coredata://S/ICNote/p1", "title": "Tagged",
              "accountId": "x-coredata://S/ICAccount/p1", "account": "iCloud",
              "folderPath": ["Food"], "modifiedAt": "2026-03-05T07:08:09+00:00"},
        "2": {"filename": "Database", "fullNoteId": "x-coredata://S/ICNote/p2",
              "tags": ["Work"], "tagsSource": "database", "pinned": True, "checklist": False},
    })
    text = root / "text/iCloud-Food/Tagged.txt"
    text.parent.mkdir(parents=True)
    text.write_text("Shopping #groceries and #weekly-plan, not #123 or a&#39;s")
    html = root / "html/iCloud-Food/Tagged.html"
    html.parent.mkdir(parents=True)
    (html.parent / "attachments").mkdir()
    (html.parent / "attachments/Tagged-attachment-001.png").write_bytes(b"\x89PNG")
    html.write_text('<img src="./attachments/Tagged-attachment-001.png">'
                    '<img src="https://example.com/x.png">')

    m = build_manifest.build(root, {"status": "ok"})
    notes = {n["short_id"]: n for n in m["notes"]}
    assert notes["1"]["tags"] == ["groceries", "weekly-plan"]
    assert notes["1"]["tags_source"] == "text"
    assert notes["1"]["pinned"] is None and notes["1"]["checklist"] is None
    assert notes["2"]["tags"] == ["Work"] and notes["2"]["pinned"] is True
    att = notes["1"]["attachments"]
    assert [(a["name"], a["kind"], a["bytes"]) for a in att] == [
        ("Tagged-attachment-001.png", "image", 4)]
    assert att[0]["path"] == "html/iCloud-Food/attachments/Tagged-attachment-001.png"
    assert m["accounts"] == [{"id": "x-coredata://S/ICAccount/p1", "name": "iCloud"}]

    # write is atomic and the next build sees no change
    build_manifest.write(root, m)
    again = build_manifest.build(root, {"status": "ok"})
    assert [n["changed_this_run"] for n in again["notes"]] == [False, False]
    assert again["run"]["sequence"] == 2

    # an edited file changes its hash and marks the note changed
    (root / "md/iCloud-Food/Tagged.md").write_text("edited")
    third = build_manifest.build(root, {"status": "ok"})
    changed = {n["short_id"]: n["changed_this_run"] for n in third["notes"]}
    assert changed == {"1": True, "2": False}


def test_manifest_ignores_a_foreign_previous_file(tmp_path):
    root = _export(tmp_path, {"1": {"filename": "A", "fullNoteId": "x/p1"}})
    (root / "manifest.json").write_text(json.dumps({"something": "else"}))
    m = build_manifest.build(root, {})
    assert m["run"]["sequence"] == 1 and m["notes"][0]["changed_this_run"] is True


# ── image conversion (#28) and tags in content (#16) ─────────────────────

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_conversion_settings(monkeypatch):
    monkeypatch.setenv("NOTES_EXPORT_IMAGE_FORMAT", "JPG")
    monkeypatch.setenv("NOTES_EXPORT_IMAGE_FORMAT_FROM", "png, heif")
    monkeypatch.setenv("NOTES_EXPORT_IMAGE_QUALITY", "70")
    target, sources, quality = extract_images.conversion_target()
    assert (target, sources, quality) == ("jpeg", {"png", "heic"}, 70)
    assert extract_images.should_convert("png", target, sources)
    assert not extract_images.should_convert("jpeg", target, sources)
    assert not extract_images.should_convert("tiff", target, sources)
    assert not extract_images.should_convert("gif", "png", None)
    monkeypatch.setenv("NOTES_EXPORT_IMAGE_FORMAT", "bmp")
    with pytest.raises(ValueError):
        extract_images.conversion_target()


@pytest.mark.skipif(not shutil.which("sips"), reason="needs macOS sips")
def test_convert_png_to_jpeg_with_sips():
    out = extract_images.convert_image(PNG_1PX, "png", "jpeg", 80)
    assert out[:3] == b"\xff\xd8\xff"


def test_tags_line_and_wrapped_keywords():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<div>x</div>", "html.parser")
    extract_images.add_tags_line(soup, ["food", "a<b"])
    assert soup.find("p", class_="note-tags").get_text() == "Tags: #food #a<b"
    page = extract_images._wrap_html(str(soup), "T & <T>", ["food", "a<b"])
    assert "<title>T &amp; &lt;T&gt;</title>" in page
    assert 'content="food, a&lt;b"' in page
