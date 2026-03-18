import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notes_export_utils as utils


@pytest.mark.unit
@pytest.mark.export
class TestNotesExportTracker:
    def test_init_with_root_directory(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        assert tracker.root_directory == str(tmp_path)
        assert tracker.data_directory == str(tmp_path / "data")

    def test_uses_subdirs_true(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        assert tracker._uses_subdirs() is True

    def test_uses_subdirs_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'false')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        assert tracker._uses_subdirs() is False

    def test_uses_subdirs_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv('NOTES_EXPORT_USE_SUBDIRS', raising=False)
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        assert tracker._uses_subdirs() is True

    def test_get_output_path_with_subdirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('pdf', 'folder', 'note', '.pdf')
        assert output == Path(tmp_path) / 'pdf' / 'folder' / 'note.pdf'
        assert output.parent.is_dir()

    def test_get_output_path_without_subdirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'false')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('pdf', 'folder', 'note', '.pdf')
        assert output == Path(tmp_path) / 'pdf' / 'note.pdf'
        assert output.parent.is_dir()

    def test_get_output_path_creates_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('md', 'deep/nested', 'note', '.md')
        assert output.parent.is_dir()

    def test_load_notebook_data(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        data = {"1234": {"filename": "test", "modified": "some date"}}
        data_file = tmp_path / "test.json"
        data_file.write_text(json.dumps(data))
        loaded = tracker.load_notebook_data(str(data_file))
        assert loaded == data

    def test_load_notebook_data_missing_file(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        loaded = tracker.load_notebook_data(str(tmp_path / "nonexistent.json"))
        assert loaded == {}

    def test_load_notebook_data_invalid_json(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json{{{")
        loaded = tracker.load_notebook_data(str(bad_file))
        assert loaded == {}

    def test_save_notebook_data(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        data = {"1234": {"filename": "test"}}
        data_file = tmp_path / "test.json"
        tracker.save_notebook_data(str(data_file), data)
        with open(data_file) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_get_all_data_files(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "notebook1.json").write_text("{}")
        (data_dir / "notebook2.json").write_text("{}")
        (data_dir / "not-json.txt").write_text("")
        files = tracker.get_all_data_files()
        assert len(files) == 2
        assert all(f.suffix == ".json" for f in files)

    def test_get_all_data_files_no_dir(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        files = tracker.get_all_data_files()
        assert files == []

    def test_get_notes_to_process_skips_deleted(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        data = {
            "1234": {
                "filename": "test",
                "lastExported": "2024-01-01",
                "deletedDate": "2024-01-02"
            }
        }
        (data_dir / "notebook.json").write_text(json.dumps(data))
        notes = tracker.get_notes_to_process("markdown")
        assert len(notes) == 0

    def test_mark_note_exported(self, tmp_path):
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        data = {"1234": {"filename": "test", "lastExported": "2024-01-01"}}
        data_file = tmp_path / "test.json"
        data_file.write_text(json.dumps(data))
        tracker.mark_note_exported(str(data_file), "1234", "markdown")
        with open(data_file) as f:
            updated = json.load(f)
        assert updated["1234"]["lastExportedToMarkdown"] == "2024-01-01"


@pytest.mark.unit
@pytest.mark.export
class TestGetOutputPathFormats:
    """Test output paths for all supported export formats."""

    def test_markdown_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('md', 'iCloud-Notes', 'My-Note-123', '.md')
        assert output == Path(tmp_path) / 'md' / 'iCloud-Notes' / 'My-Note-123.md'

    def test_pdf_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('pdf', 'iCloud-Notes', 'My-Note-123', '.pdf')
        assert output == Path(tmp_path) / 'pdf' / 'iCloud-Notes' / 'My-Note-123.pdf'

    def test_word_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('docx', 'iCloud-Notes', 'My-Note-123', '.docx')
        assert output == Path(tmp_path) / 'docx' / 'iCloud-Notes' / 'My-Note-123.docx'

    def test_html_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
        tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
        output = tracker.get_output_path('html', 'iCloud-Notes', 'My-Note-123', '.html')
        assert output == Path(tmp_path) / 'html' / 'iCloud-Notes' / 'My-Note-123.html'
