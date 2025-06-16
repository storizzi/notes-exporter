import os
from pathlib import Path
import notes_export_utils as utils


def test_uses_subdirs_true(monkeypatch, tmp_path):
    monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
    tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
    assert tracker._uses_subdirs() is True


def test_uses_subdirs_false(monkeypatch, tmp_path):
    monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'false')
    tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
    assert tracker._uses_subdirs() is False


def test_get_output_path_with_subdirs(monkeypatch, tmp_path):
    monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'true')
    tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
    output = tracker.get_output_path('pdf', 'folder', 'note', '.pdf')
    expected = Path(tmp_path) / 'pdf' / 'folder' / 'note.pdf'
    assert output == expected
    assert output.parent.is_dir()


def test_get_output_path_without_subdirs(monkeypatch, tmp_path):
    monkeypatch.setenv('NOTES_EXPORT_USE_SUBDIRS', 'false')
    tracker = utils.NotesExportTracker(root_directory=str(tmp_path))
    output = tracker.get_output_path('pdf', 'folder', 'note', '.pdf')
    expected = Path(tmp_path) / 'pdf' / 'note.pdf'
    assert output == expected
    assert output.parent.is_dir()
