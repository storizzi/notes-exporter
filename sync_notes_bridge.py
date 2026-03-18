import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = Path(__file__).parent
SYNC_SCRIPT = SCRIPT_DIR / "sync_notes.scpt"


def _run_sync_command(command: Dict) -> Dict:
    """Execute a sync command via AppleScript and return the result."""
    input_fd, input_path = tempfile.mkstemp(suffix=".json", prefix="sync_cmd_")
    output_fd, output_path = tempfile.mkstemp(suffix=".json", prefix="sync_result_")

    try:
        # Write command to temp file
        with os.fdopen(input_fd, "w", encoding="utf-8") as f:
            json.dump(command, f)

        os.close(output_fd)

        # Run AppleScript
        result = subprocess.run(
            ["osascript", str(SYNC_SCRIPT), input_path, output_path],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {"success": False, "error": f"osascript failed: {stderr}"}

        # Read result
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "AppleScript timed out after 120 seconds"}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Failed to parse AppleScript result: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        # Clean up temp files
        for path in (input_path, output_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def update_note(full_note_id: str, title: str, html_body: str) -> Dict:
    """Update an existing note in Apple Notes.

    Returns dict with 'success' bool and 'modifiedDate' on success or 'error' on failure.
    """
    return _run_sync_command({
        "operation": "update",
        "fullNoteId": full_note_id,
        "title": title,
        "body": html_body,
    })


def create_note(account: str, folder: str, title: str, html_body: str) -> Dict:
    """Create a new note in Apple Notes.

    Returns dict with 'success' bool, 'fullNoteId', and 'modifiedDate' on success.
    """
    return _run_sync_command({
        "operation": "create",
        "account": account,
        "folder": folder,
        "title": title,
        "body": html_body,
    })


def get_modified_date(full_note_id: str) -> Optional[str]:
    """Get the current modification date of a note in Apple Notes.

    Returns the date string, or None if the note can't be found.
    """
    result = _run_sync_command({
        "operation": "get_modified",
        "fullNoteId": full_note_id,
    })
    if result.get("success"):
        return result.get("modifiedDate")
    return None
