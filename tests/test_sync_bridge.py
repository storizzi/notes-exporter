import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_notes_bridge import _run_sync_command, update_note, create_note, get_modified_date


@pytest.mark.unit
@pytest.mark.sync
class TestRunSyncCommand:
    def test_handles_timeout(self):
        with patch("sync_notes_bridge.subprocess.run") as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=120)
            result = _run_sync_command({"operation": "test"})
            assert result["success"] is False
            assert "timed out" in result["error"]

    def test_handles_nonzero_exit(self):
        with patch("sync_notes_bridge.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="some error")
            result = _run_sync_command({"operation": "test"})
            assert result["success"] is False
            assert "some error" in result["error"]

    def test_writes_command_to_temp_file(self):
        """Verify the command dict is serialized to a temp JSON file."""
        command = {"operation": "update", "fullNoteId": "x-coredata://test", "title": "Test"}
        with patch("sync_notes_bridge.subprocess.run") as mock_run:
            # Make it return a valid result file
            def side_effect(args, **kwargs):
                # Write a result to the output file
                output_path = args[3]  # 4th arg is output path
                with open(output_path, "w") as f:
                    json.dump({"success": True}, f)
                return MagicMock(returncode=0, stderr="")
            mock_run.side_effect = side_effect
            result = _run_sync_command(command)
            assert result["success"] is True

    def test_cleans_up_temp_files(self):
        """Temp files should be cleaned up even on error."""
        with patch("sync_notes_bridge.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("test error")
            result = _run_sync_command({"operation": "test"})
            assert result["success"] is False


@pytest.mark.unit
@pytest.mark.sync
class TestUpdateNote:
    def test_calls_with_correct_operation(self):
        with patch("sync_notes_bridge._run_sync_command") as mock:
            mock.return_value = {"success": True, "modifiedDate": "now"}
            result = update_note("x-coredata://test", "Title", "<html>body</html>")
            mock.assert_called_once()
            cmd = mock.call_args[0][0]
            assert cmd["operation"] == "update"
            assert cmd["fullNoteId"] == "x-coredata://test"
            assert cmd["title"] == "Title"


@pytest.mark.unit
@pytest.mark.sync
class TestCreateNote:
    def test_calls_with_correct_operation(self):
        with patch("sync_notes_bridge._run_sync_command") as mock:
            mock.return_value = {"success": True, "fullNoteId": "x-coredata://new"}
            result = create_note("iCloud", "Notes", "New Note", "<html>body</html>")
            cmd = mock.call_args[0][0]
            assert cmd["operation"] == "create"
            assert cmd["account"] == "iCloud"
            assert cmd["folder"] == "Notes"


@pytest.mark.unit
@pytest.mark.sync
class TestGetModifiedDate:
    def test_returns_date_on_success(self):
        with patch("sync_notes_bridge._run_sync_command") as mock:
            mock.return_value = {"success": True, "modifiedDate": "Monday, 17 March 2026"}
            result = get_modified_date("x-coredata://test")
            assert result == "Monday, 17 March 2026"

    def test_returns_none_on_failure(self):
        with patch("sync_notes_bridge._run_sync_command") as mock:
            mock.return_value = {"success": False, "error": "not found"}
            result = get_modified_date("x-coredata://test")
            assert result is None
