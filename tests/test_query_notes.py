import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from query_notes import (
    search_file, note_has_images,
    parse_timespan, parse_date_arg, parse_apple_date,
    passes_date_filter, get_note_dates,
)


@pytest.mark.unit
@pytest.mark.search
class TestSearchFile:
    def test_finds_literal_text(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("Line one\nHello world\nLine three", encoding="utf-8")
        pattern = re.compile(re.escape("Hello world"))
        matches = search_file(f, pattern)
        assert len(matches) == 1
        assert matches[0]['line_num'] == 2
        assert "Hello world" in matches[0]['line']

    def test_finds_regex(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("TODO: fix this\nDone\nFIXME: later", encoding="utf-8")
        pattern = re.compile(r"TODO|FIXME")
        matches = search_file(f, pattern)
        assert len(matches) == 2
        assert matches[0]['line_num'] == 1
        assert matches[1]['line_num'] == 3

    def test_case_insensitive(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("Hello\nhello\nHELLO", encoding="utf-8")
        pattern = re.compile("hello", re.IGNORECASE)
        matches = search_file(f, pattern)
        assert len(matches) == 3

    def test_no_matches(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("nothing here", encoding="utf-8")
        pattern = re.compile("xyz123")
        matches = search_file(f, pattern)
        assert len(matches) == 0

    def test_files_only_mode(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("match one\nmatch two\nmatch three", encoding="utf-8")
        pattern = re.compile("match")
        matches = search_file(f, pattern, files_only=True)
        assert len(matches) == 1  # Only returns one match in files-only mode

    def test_context_lines(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("a\nb\nc\ntarget\nd\ne\nf", encoding="utf-8")
        pattern = re.compile("target")
        matches = search_file(f, pattern, context_lines=1)
        assert len(matches) == 1
        assert "c" in matches[0]['context']
        assert "target" in matches[0]['context']
        assert "d" in matches[0]['context']

    def test_max_matches(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("match\nmatch\nmatch\nmatch\nmatch", encoding="utf-8")
        pattern = re.compile("match")
        matches = search_file(f, pattern, max_matches=2)
        assert len(matches) == 2

    def test_handles_binary_gracefully(self, tmp_path):
        f = tmp_path / "binary.md"
        f.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        pattern = re.compile("test")
        matches = search_file(f, pattern)
        assert len(matches) == 0  # Should not crash

    def test_multiple_encodings(self, tmp_path):
        f = tmp_path / "note.md"
        # Write Latin-1 content
        f.write_bytes("caf\xe9 latt\xe9".encode('latin-1'))
        pattern = re.compile("caf")
        matches = search_file(f, pattern)
        assert len(matches) == 1


@pytest.mark.unit
@pytest.mark.search
class TestNoteHasImages:
    def test_no_images(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        f = tmp_path / "md" / "notebook" / "note.md"
        f.parent.mkdir(parents=True)
        f.write_text("no images here")
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        assert note_has_images(f, tracker) is False

    def test_has_images_in_attachments(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        note_dir = tmp_path / "md" / "notebook"
        note_dir.mkdir(parents=True)
        f = note_dir / "my-note-123.md"
        f.write_text("has images")
        att_dir = note_dir / "attachments"
        att_dir.mkdir()
        (att_dir / "my-note-123-attachment-001.png").write_bytes(b'\x89PNG')
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        assert note_has_images(f, tracker) is True

    def test_has_images_beside_docs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        note_dir = tmp_path / "md" / "notebook"
        note_dir.mkdir(parents=True)
        f = note_dir / "my-note-123.md"
        f.write_text("has images")
        (note_dir / "my-note-123-attachment-001.jpg").write_bytes(b'\xff\xd8')
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        assert note_has_images(f, tracker) is True

    def test_no_matching_attachments(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        note_dir = tmp_path / "md" / "notebook"
        note_dir.mkdir(parents=True)
        f = note_dir / "my-note-123.md"
        f.write_text("no images")
        att_dir = note_dir / "attachments"
        att_dir.mkdir()
        # Different note's attachment
        (att_dir / "other-note-456-attachment-001.png").write_bytes(b'\x89PNG')
        from notes_export_utils import get_tracker
        tracker = get_tracker()
        assert note_has_images(f, tracker) is False


@pytest.mark.unit
@pytest.mark.search
class TestParseTimespan:
    def test_hours(self):
        assert parse_timespan("5h") == timedelta(hours=5)

    def test_days(self):
        assert parse_timespan("3d") == timedelta(days=3)

    def test_weeks(self):
        assert parse_timespan("2w") == timedelta(weeks=2)

    def test_months(self):
        assert parse_timespan("2m") == timedelta(days=60)

    def test_years(self):
        assert parse_timespan("1y") == timedelta(days=365)

    def test_seconds(self):
        assert parse_timespan("30s") == timedelta(seconds=30)

    def test_minutes(self):
        assert parse_timespan("15min") == timedelta(minutes=15)

    def test_long_form(self):
        assert parse_timespan("3days") == timedelta(days=3)
        assert parse_timespan("2weeks") == timedelta(weeks=2)
        assert parse_timespan("1year") == timedelta(days=365)

    def test_fractional(self):
        assert parse_timespan("1.5d") == timedelta(days=1.5)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_timespan("abc")
        with pytest.raises(ValueError):
            parse_timespan("5x")

    def test_whitespace(self):
        assert parse_timespan("  3d  ") == timedelta(days=3)


@pytest.mark.unit
@pytest.mark.search
class TestParseDateArg:
    def test_iso_format(self):
        result = parse_date_arg("2026-01-15")
        assert result == datetime(2026, 1, 15)

    def test_iso_with_time(self):
        result = parse_date_arg("2026-01-15 14:30:00")
        assert result == datetime(2026, 1, 15, 14, 30, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_date_arg("not-a-date")


@pytest.mark.unit
@pytest.mark.search
class TestParseAppleDate:
    def test_12_hour(self):
        result = parse_apple_date("Thursday, August 26, 2021 at 7:38:15 PM")
        assert result == datetime(2021, 8, 26, 19, 38, 15)

    def test_24_hour(self):
        result = parse_apple_date("Monday, 17 March 2026 at 14:30:00")
        assert result == datetime(2026, 3, 17, 14, 30, 0)

    def test_empty_returns_none(self):
        assert parse_apple_date("") is None
        assert parse_apple_date(None) is None


@pytest.mark.unit
@pytest.mark.search
class TestPassesDateFilter:
    def test_no_filters(self):
        dates = {'created': datetime(2026, 1, 15), 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates) is True

    def test_modified_after_pass(self):
        dates = {'created': datetime(2026, 1, 1), 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates, modified_after=datetime(2026, 2, 1)) is True

    def test_modified_after_fail(self):
        dates = {'created': datetime(2026, 1, 1), 'modified': datetime(2026, 1, 15)}
        assert passes_date_filter(dates, modified_after=datetime(2026, 2, 1)) is False

    def test_created_before_pass(self):
        dates = {'created': datetime(2025, 6, 1), 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates, created_before=datetime(2026, 1, 1)) is True

    def test_created_before_fail(self):
        dates = {'created': datetime(2026, 6, 1), 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates, created_before=datetime(2026, 1, 1)) is False

    def test_combined_filters(self):
        dates = {'created': datetime(2025, 6, 1), 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates,
            created_after=datetime(2025, 1, 1),
            modified_before=datetime(2026, 6, 1)) is True

    def test_missing_date_fails_filter(self):
        dates = {'created': None, 'modified': datetime(2026, 3, 1)}
        assert passes_date_filter(dates, created_after=datetime(2025, 1, 1)) is False


@pytest.mark.unit
@pytest.mark.search
class TestGetNoteDates:
    def test_looks_up_dates_from_tracking(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        import json
        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump({"123": {
                "filename": "my-note-123",
                "created": "Thursday, August 26, 2021 at 7:38:15 PM",
                "modified": "Monday, 17 March 2026 at 14:30:00",
            }}, f)

        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)
        note_file = md_dir / "my-note-123.md"
        note_file.write_text("content")

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        # Clear cache from prior tests
        get_note_dates.__defaults__[0].clear()
        dates = get_note_dates(note_file, tracker)
        assert dates["created"] == datetime(2021, 8, 26, 19, 38, 15)
        assert dates["modified"] == datetime(2026, 3, 17, 14, 30, 0)

    def test_returns_none_for_unknown_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        from notes_export_utils import get_tracker
        tracker = get_tracker()
        get_note_dates.__defaults__[0].clear()
        dates = get_note_dates(tmp_path / "unknown.md", tracker)
        assert dates["created"] is None
        assert dates["modified"] is None
