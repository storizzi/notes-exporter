import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import set_file_dates


@pytest.mark.unit
@pytest.mark.export
class TestParseAppleDate:
    def test_12_hour_format(self):
        result = set_file_dates.parse_apple_date("Thursday, August 26, 2021 at 7:38:15 PM")
        assert result == datetime(2021, 8, 26, 19, 38, 15)

    def test_12_hour_format_am(self):
        result = set_file_dates.parse_apple_date("Monday, January 1, 2024 at 9:00:00 AM")
        assert result == datetime(2024, 1, 1, 9, 0, 0)

    def test_non_breaking_space(self):
        # \u202f is narrow no-break space, sometimes inserted before AM/PM
        result = set_file_dates.parse_apple_date("Thursday, August 26, 2021 at 7:38:15\u202fPM")
        assert result == datetime(2021, 8, 26, 19, 38, 15)

    def test_invalid_date_returns_none(self):
        result = set_file_dates.parse_apple_date("not a date")
        assert result is None

    def test_empty_string_returns_none(self):
        result = set_file_dates.parse_apple_date("")
        assert result is None


@pytest.mark.unit
@pytest.mark.export
class TestProcessNotebookData:
    def test_processes_active_notes(self, tmp_path):
        # Create data file
        data = {
            "1234": {
                "filename": "Test-Note-1234",
                "created": "Monday, January 1, 2024 at 9:00:00 AM",
                "modified": "Tuesday, January 2, 2024 at 10:00:00 AM"
            }
        }
        data_file = tmp_path / "data" / "test.json"
        data_file.parent.mkdir(parents=True)
        data_file.write_text(json.dumps(data))

        # Create target files
        for fmt, ext in [("html", ".html"), ("text", ".txt"), ("raw", ".html")]:
            d = tmp_path / fmt / "test"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"Test-Note-1234{ext}").write_text("content")

        result = set_file_dates.process_notebook_data(
            str(data_file), tmp_path, True, "test"
        )
        assert result == 3  # 3 files updated

    def test_skips_deleted_notes(self, tmp_path):
        data = {
            "1234": {
                "filename": "Test-Note-1234",
                "created": "Monday, January 1, 2024 at 9:00:00 AM",
                "modified": "Tuesday, January 2, 2024 at 10:00:00 AM",
                "deletedDate": "Wednesday, January 3, 2024 at 11:00:00 AM"
            }
        }
        data_file = tmp_path / "data" / "test.json"
        data_file.parent.mkdir(parents=True)
        data_file.write_text(json.dumps(data))

        # Create target file
        html_dir = tmp_path / "html" / "test"
        html_dir.mkdir(parents=True)
        (html_dir / "Test-Note-1234.html").write_text("content")

        result = set_file_dates.process_notebook_data(
            str(data_file), tmp_path, True, "test"
        )
        assert result == 0  # deleted notes should be skipped

    def test_skips_missing_dates(self, tmp_path):
        data = {
            "1234": {
                "filename": "Test-Note-1234"
                # No created/modified dates
            }
        }
        data_file = tmp_path / "data" / "test.json"
        data_file.parent.mkdir(parents=True)
        data_file.write_text(json.dumps(data))

        result = set_file_dates.process_notebook_data(
            str(data_file), tmp_path, True, "test"
        )
        assert result == 0

    def test_handles_missing_data_file(self, tmp_path):
        result = set_file_dates.process_notebook_data(
            str(tmp_path / "nonexistent.json"), tmp_path, True, "test"
        )
        assert result == 0

    def test_without_subdirs(self, tmp_path):
        data = {
            "1234": {
                "filename": "Test-Note-1234",
                "created": "Monday, January 1, 2024 at 9:00:00 AM",
                "modified": "Tuesday, January 2, 2024 at 10:00:00 AM"
            }
        }
        data_file = tmp_path / "data" / "test.json"
        data_file.parent.mkdir(parents=True)
        data_file.write_text(json.dumps(data))

        # Create files without subdirectory
        html_dir = tmp_path / "html"
        html_dir.mkdir(parents=True)
        (html_dir / "Test-Note-1234.html").write_text("content")

        result = set_file_dates.process_notebook_data(
            str(data_file), tmp_path, False, "test"
        )
        assert result == 1
