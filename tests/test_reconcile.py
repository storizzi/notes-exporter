import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from reconcile import (
    count_tracking_json,
    count_disk_files,
    get_tracked_notes,
    get_disk_filenames,
    find_specific_discrepancies,
)


def _setup_export_dir(tmp_path, notes, deleted=None, formats=None):
    """Helper to create a mock export directory structure."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    if formats is None:
        formats = ["raw", "md"]

    # Build tracking JSON
    notebook = "iCloud-Notes"
    tracking = {}
    for note_id, filename in notes.items():
        tracking[note_id] = {
            "filename": filename,
            "created": "Monday, 1 January 2026 at 10:00:00",
            "modified": "Monday, 1 January 2026 at 10:00:00",
            "firstExported": "2026-01-01 10:00:00",
            "lastExported": "2026-01-01 10:00:00",
            "exportCount": 1,
            "fullNoteId": f"x-coredata://test/{note_id}",
        }
    if deleted:
        for note_id, filename in deleted.items():
            tracking[note_id] = {
                "filename": filename,
                "created": "Monday, 1 January 2026 at 10:00:00",
                "modified": "Monday, 1 January 2026 at 10:00:00",
                "firstExported": "2026-01-01 10:00:00",
                "lastExported": "2026-01-01 10:00:00",
                "exportCount": 1,
                "deletedDate": "Tuesday, 2 January 2026 at 10:00:00",
            }

    json_file = data_dir / f"{notebook}.json"
    with open(json_file, "w") as f:
        json.dump(tracking, f)

    # Create disk files
    ext_map = {"raw": ".html", "html": ".html", "text": ".txt",
               "md": ".md", "pdf": ".pdf", "docx": ".docx"}
    for fmt in formats:
        fmt_dir = tmp_path / fmt / notebook
        fmt_dir.mkdir(parents=True)
        for filename in notes.values():
            (fmt_dir / f"{filename}{ext_map[fmt]}").write_text("content")

    return notebook


@pytest.mark.unit
@pytest.mark.reconcile
class TestCountTrackingJson:
    def test_counts_active_and_deleted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a", "2": "note-b"},
                         deleted={"3": "note-c"})
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        counts = count_tracking_json(tracker)
        assert counts["iCloud-Notes"]["active"] == 2
        assert counts["iCloud-Notes"]["deleted"] == 1
        assert counts["iCloud-Notes"]["total"] == 3
        assert counts["iCloud-Notes"]["with_full_id"] == 2


@pytest.mark.unit
@pytest.mark.reconcile
class TestCountDiskFiles:
    def test_counts_by_format(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a", "2": "note-b"},
                         formats=["raw", "md"])
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        counts = count_disk_files(tracker)
        assert counts["_totals"]["raw"] == 2
        assert counts["_totals"]["md"] == 2


@pytest.mark.unit
@pytest.mark.reconcile
class TestFindSpecificDiscrepancies:
    def test_finds_orphan_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        notebook = _setup_export_dir(tmp_path, notes={"1": "note-a"}, formats=["raw"])
        # Add an orphan file not in tracking
        (tmp_path / "raw" / notebook / "orphan-note.html").write_text("orphan")

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, {})
        combined = "\n".join(details)
        assert "orphan-note" in combined

    def test_finds_missing_disk_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a", "2": "note-b"},
                         formats=["raw"])
        # Delete one file from disk
        (tmp_path / "raw" / "iCloud-Notes" / "note-b.html").unlink()

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, {})
        combined = "\n".join(details)
        assert "note-b" in combined
        assert "no raw file" in combined

    def test_finds_deleted_still_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a"},
                         deleted={"2": "deleted-note"},
                         formats=["raw", "md"])
        # Create files for the deleted note
        for fmt, ext in [("raw", ".html"), ("md", ".md")]:
            (tmp_path / fmt / "iCloud-Notes" / f"deleted-note{ext}").write_text("old")

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, {})
        combined = "\n".join(details)
        assert "deleted-note" in combined
        assert "Deleted note still on disk" in combined

    def test_finds_missing_fullnoteid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path, notes={"1": "note-a"}, formats=["raw"])
        # Remove fullNoteId from tracking
        json_file = tmp_path / "data" / "iCloud-Notes.json"
        data = json.load(open(json_file))
        del data["1"]["fullNoteId"]
        with open(json_file, "w") as f:
            json.dump(data, f)

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, {})
        combined = "\n".join(details)
        assert "Missing fullNoteId" in combined
        assert "note-a" in combined

    def test_finds_missing_from_qdrant(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a", "2": "note-b"},
                         formats=["raw"])
        # Qdrant only has note 1
        qdrant_ids = {"iCloud-Notes": {"1"}}

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, qdrant_ids)
        combined = "\n".join(details)
        assert "Not in Qdrant" in combined
        assert "note-b" in combined

    def test_no_discrepancies_when_clean(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        _setup_export_dir(tmp_path,
                         notes={"1": "note-a", "2": "note-b"},
                         formats=["raw", "md"])
        qdrant_ids = {"iCloud-Notes": {"1", "2"}}

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        disk = get_disk_filenames(tracker)
        tracked = get_tracked_notes(tracker)
        details = find_specific_discrepancies(tracker, disk, tracked, qdrant_ids)
        assert len(details) == 0
