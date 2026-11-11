"""Nested folder layouts (&folderpath, #36) and same-named folders (#37) downstream
of the AppleScript: image extraction, Markdown, dates, reconcile."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parent.parent
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()

pytestmark = pytest.mark.export


def run(script, root, *args):
    env = os.environ.copy()
    env["NOTES_EXPORT_ROOT_DIR"] = str(root)
    env["NOTES_EXPORT_USE_SUBDIRS"] = "true"
    return subprocess.run([sys.executable, str(SCRIPT_DIR / script), *args],
                          capture_output=True, text=True, env=env, cwd=str(SCRIPT_DIR), timeout=60)


def make_note(root, tracker, subdir, note_id, filename, body, folder_path):
    raw_dir = root / "raw" / subdir
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{filename}.html").write_text(body, encoding="utf-8")
    data_file = root / "data" / f"{tracker}.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(data_file.read_text()) if data_file.exists() else {}
    data[note_id] = {
        "filename": filename, "subdir": subdir, "folderPath": folder_path,
        "created": "x", "modified": "y",
        "createdAt": "2026-01-02T03:04:05+00:00", "modifiedAt": "2026-02-03T04:05:06+00:00",
        "lastExported": "2026-11-11T10:00:00.000001+00:00", "exportCount": 1,
        "fullNoteId": f"x-coredata://S/ICNote/p{note_id}",
    }
    data_file.write_text(json.dumps(data))


@pytest.fixture
def nested_export(tmp_path):
    make_note(tmp_path, "iCloud%2FFood%2FRecipes", "iCloud/Food/Recipes", "1", "Scones-1",
              f'<div>Scones</div><img src="data:image/png;base64,{PNG}">', ["Food", "Recipes"])
    make_note(tmp_path, "iCloud%2FFun%2FRecipes", "iCloud/Fun/Recipes", "2", "Cocktails-2",
              "<div>Cocktails</div>", ["Fun", "Recipes"])
    make_note(tmp_path, "iCloud%2FFood", "iCloud/Food", "3", "Food-index-3",
              "<div>Index</div>", ["Food"])
    return tmp_path


def test_images_and_markdown_follow_nested_subdirs(nested_export):
    r = run("extract_images.py", nested_export)
    assert r.returncode == 0, r.stderr
    r = run("convert_to_markdown.py", nested_export)
    assert r.returncode == 0, r.stderr
    md = nested_export / "md"
    assert (md / "iCloud/Food/Recipes/Scones-1.md").exists()
    assert (md / "iCloud/Fun/Recipes/Cocktails-2.md").exists()
    assert (md / "iCloud/Food/Food-index-3.md").exists()
    assert (nested_export / "html/iCloud/Food/Recipes/attachments/Scones-1-attachment-001.png").exists()
    assert "./attachments/Scones-1-attachment-001.png" in (md / "iCloud/Food/Recipes/Scones-1.md").read_text()


def test_same_named_folders_sharing_a_tracker_both_convert(tmp_path):
    """#37: two Dup folders share iCloud-Dup; both notes must reach Markdown."""
    make_note(tmp_path, "iCloud-Dup", "iCloud-Dup", "10", "From-Alpha-10", "<p>a</p>", ["Alpha", "Dup"])
    make_note(tmp_path, "iCloud-Dup", "iCloud-Dup", "20", "From-Beta-20", "<p>b</p>", ["Beta", "Dup"])
    assert run("extract_images.py", tmp_path).returncode == 0
    assert run("convert_to_markdown.py", tmp_path).returncode == 0
    assert (tmp_path / "md/iCloud-Dup/From-Alpha-10.md").exists()
    assert (tmp_path / "md/iCloud-Dup/From-Beta-20.md").exists()


def test_set_file_dates_uses_iso_and_nested_paths(nested_export):
    assert run("extract_images.py", nested_export).returncode == 0
    r = run("set_file_dates.py", nested_export)
    assert r.returncode == 0, r.stderr
    raw = nested_export / "raw/iCloud/Fun/Recipes/Cocktails-2.html"
    from datetime import datetime
    expected = datetime.fromisoformat("2026-02-03T04:05:06+00:00").timestamp()
    assert abs(raw.stat().st_mtime - expected) < 2


def test_reconcile_counts_nested_dirs(nested_export):
    sys.path.insert(0, str(SCRIPT_DIR))
    import reconcile
    from notes_export_utils import NotesExportTracker
    run("extract_images.py", nested_export)
    tracker = NotesExportTracker(str(nested_export))
    counts = reconcile.count_disk_files(tracker)
    assert counts["iCloud/Food/Recipes"]["raw"] == 1
    assert counts["iCloud/Food"]["raw"] == 1
    tracked = reconcile.count_tracking_json(tracker)
    assert set(tracked) == {"iCloud/Food/Recipes", "iCloud/Fun/Recipes", "iCloud/Food"}


def test_reorganize_flat_export_into_tree(tmp_path):
    """#36 post-processor: a flat export with merged Dup folders -> real tree."""
    make_note(tmp_path, "iCloud-Dup", "iCloud-Dup", "10", "From-Alpha-10",
              f'<p>a</p><img src="data:image/png;base64,{PNG}">', ["Top", "Alpha", "Dup"])
    make_note(tmp_path, "iCloud-Dup", "iCloud-Dup", "20", "From-Beta-20", "<p>b</p>", ["Top", "Beta", "Dup"])
    data = json.loads((tmp_path / "data/iCloud-Dup.json").read_text())
    for rec in data.values():
        rec["account"] = "iCloud"
    data["30"] = {"filename": "Old-30", "lastExported": "x"}  # pre-1.4.0 record, no folderPath
    (tmp_path / "data/iCloud-Dup.json").write_text(json.dumps(data))
    run("extract_images.py", tmp_path)
    run("convert_to_markdown.py", tmp_path)

    r = run("reorganize_by_folder.py", tmp_path, "--export-root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    tree = tmp_path / "by-folder" / "iCloud" / "Top"
    assert (tree / "Alpha/Dup/From-Alpha-10.md").exists()
    assert (tree / "Beta/Dup/From-Beta-20.md").exists()
    assert (tree / "Alpha/Dup/attachments/From-Alpha-10-attachment-001.png").exists()
    assert not (tree / "Beta/Dup/attachments").exists()
    assert "1 notes had no folder path" in r.stdout
    assert (tmp_path / "md/iCloud-Dup/From-Alpha-10.md").exists(), "original untouched"

    r = run("reorganize_by_folder.py", tmp_path, "--export-root", str(tmp_path))
    assert r.returncode == 1 and "already exists" in r.stderr
