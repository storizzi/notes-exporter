import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_to_notes import (
    SyncEngine,
    compute_file_hash,
    create_conflict_file,
    find_new_local_files,
    get_sync_status,
)


@pytest.mark.unit
@pytest.mark.sync
class TestComputeFileHash:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello world", encoding="utf-8")
        h1 = compute_file_hash(f)
        h2 = compute_file_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert compute_file_hash(f1) != compute_file_hash(f2)


@pytest.mark.unit
@pytest.mark.sync
class TestGetSyncStatus:
    def test_no_changes(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content", encoding="utf-8")
        file_hash = compute_file_hash(f)
        note_info = {
            "localFileHashAtLastSync": file_hash,
            "appleNotesModifiedAtLastSync": "Monday, 17 March 2026",
            "modified": "Monday, 17 March 2026",
        }
        local_changed, remote_changed = get_sync_status(note_info, f)
        assert not local_changed
        assert not remote_changed

    def test_local_changed(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("original", encoding="utf-8")
        old_hash = compute_file_hash(f)
        f.write_text("modified content", encoding="utf-8")
        note_info = {
            "localFileHashAtLastSync": old_hash,
            "appleNotesModifiedAtLastSync": "Monday, 17 March 2026",
            "modified": "Monday, 17 March 2026",
        }
        local_changed, remote_changed = get_sync_status(note_info, f)
        assert local_changed
        assert not remote_changed

    def test_remote_changed(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content", encoding="utf-8")
        file_hash = compute_file_hash(f)
        note_info = {
            "localFileHashAtLastSync": file_hash,
            "appleNotesModifiedAtLastSync": "Monday, 17 March 2026",
            "modified": "Tuesday, 18 March 2026",
        }
        local_changed, remote_changed = get_sync_status(note_info, f)
        assert not local_changed
        assert remote_changed

    def test_both_changed(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("original", encoding="utf-8")
        old_hash = compute_file_hash(f)
        f.write_text("modified", encoding="utf-8")
        note_info = {
            "localFileHashAtLastSync": old_hash,
            "appleNotesModifiedAtLastSync": "Monday, 17 March 2026",
            "modified": "Tuesday, 18 March 2026",
        }
        local_changed, remote_changed = get_sync_status(note_info, f)
        assert local_changed
        assert remote_changed

    def test_never_synced(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content", encoding="utf-8")
        note_info = {"modified": "Monday, 17 March 2026"}
        local_changed, remote_changed = get_sync_status(note_info, f)
        assert not local_changed
        assert not remote_changed


@pytest.mark.unit
@pytest.mark.sync
class TestCreateConflictFile:
    def test_creates_conflict_sidecar(self, tmp_path):
        md_file = tmp_path / "note.md"
        md_file.write_text("local version", encoding="utf-8")
        note_info = {"modified": "Tuesday, 18 March 2026"}
        result = create_conflict_file(md_file, "local version", note_info)
        assert result.name == "note.conflict.md"
        assert result.exists()
        content = result.read_text()
        assert "CONFLICT DETECTED" in content
        assert "local version" in content
        assert "Tuesday, 18 March 2026" in content


@pytest.mark.unit
@pytest.mark.sync
class TestSyncEngineDryRun:
    def test_dry_run_does_not_call_applescript(self, tmp_path, monkeypatch):
        # Set up a minimal environment
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

        # Create data directory with a note
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)

        # Write a markdown file
        md_file = md_dir / "test-note-123.md"
        md_file.write_text("# Test\nModified content", encoding="utf-8")
        old_hash = hashlib.sha256(b"# Test\nOriginal content").hexdigest()

        # Write tracking JSON
        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump({
                "123": {
                    "filename": "test-note-123",
                    "fullNoteId": "x-coredata://test/123",
                    "modified": "Monday, 17 March 2026",
                    "created": "Monday, 17 March 2026",
                    "firstExported": "2026-03-17 10:00:00",
                    "lastExported": "2026-03-17 10:00:00",
                    "exportCount": 1,
                    "localFileHashAtLastSync": old_hash,
                    "appleNotesModifiedAtLastSync": "Monday, 17 March 2026",
                }
            }, f)

        engine = SyncEngine(dry_run=True)
        with patch("sync_to_notes.update_note") as mock_update:
            engine.run()
            mock_update.assert_not_called()
        assert engine.stats["synced"] == 1  # Counted but not actually synced


@pytest.mark.unit
@pytest.mark.sync
class TestFindNewLocalFiles:
    def test_finds_unmatched_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)

        # Create a tracked note
        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump({"123": {"filename": "existing-note-123"}}, f)

        # Create tracked and untracked markdown files
        (md_dir / "existing-note-123.md").write_text("tracked", encoding="utf-8")
        (md_dir / "brand-new-note.md").write_text("new note", encoding="utf-8")
        (md_dir / "something.conflict.md").write_text("conflict", encoding="utf-8")

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        new_files = find_new_local_files(tracker)

        filenames = [f["filename"] for f in new_files]
        assert "brand-new-note" in filenames
        assert "existing-note-123" not in filenames
        assert "something.conflict" not in filenames
