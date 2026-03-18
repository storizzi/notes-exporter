"""Shared test configuration, fixtures, and markers.

Test categories (run with -m flag):
    pytest -m unit              # Unit tests only
    pytest -m integration       # Integration tests only
    pytest -m search            # Search/query feature
    pytest -m sync              # Bidirectional sync feature
    pytest -m qdrant            # Qdrant vector DB feature
    pytest -m reconcile         # Reconciliation feature
    pytest -m export            # Export features (images, html, etc.)
    pytest -m settings          # Settings/config
    pytest -m json_output       # JSON Lines output

Scope control:
    NOTES_TEST_LIMIT=10         # Default: limit to 10 items per test
    NOTES_TEST_LIMIT=0          # Unlimited (all items)
    pytest --all-items          # Same as NOTES_TEST_LIMIT=0

Test isolation:
    All tests use a temporary directory, never the live export directory.
    NOTES_TEST_DIR env var is set automatically by fixtures.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCRIPT_DIR = Path(__file__).parent.parent


# ── Pytest configuration ──────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption("--all-items", action="store_true", default=False,
                     help="Run tests with no item limit (default: 10)")


def pytest_configure(config):
    """Register custom markers."""
    for marker in [
        "unit: Unit tests (fast, no external dependencies)",
        "integration: Integration tests (run commands as subprocesses)",
        "search: Search/query feature tests",
        "sync: Bidirectional sync feature tests",
        "qdrant: Qdrant vector DB tests",
        "reconcile: Reconciliation tests",
        "export: Export feature tests (images, html wrap, etc.)",
        "settings: Settings/config tests",
        "json_output: JSON Lines output tests",
    ]:
        config.addinivalue_line("markers", marker)


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests as 'unit' unless they're in an integration test class."""
    for item in items:
        if "Integration" in item.nodeid or "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif not any(item.iter_markers(name=m) for m in ["unit", "integration"]):
            item.add_marker(pytest.mark.unit)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def test_limit(request):
    """Get the item limit for tests. Default 10, 0 = unlimited."""
    if request.config.getoption("--all-items", default=False):
        return 0
    return int(os.getenv("NOTES_TEST_LIMIT", "10"))


@pytest.fixture
def test_export_dir(tmp_path, monkeypatch):
    """Create an isolated test export directory with sample data.

    Sets NOTES_EXPORT_ROOT_DIR to the temp directory so no test
    touches the live installation.
    """
    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

    # Create directory structure
    for d in ["data", "raw/iCloud-Notes", "html/iCloud-Notes",
              "text/iCloud-Notes", "md/iCloud-Notes"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    return tmp_path


@pytest.fixture
def sample_notes(test_export_dir):
    """Populate the test export directory with sample notes.

    Creates 15 sample notes with tracking JSON, raw HTML, and markdown files.
    Returns dict of {note_id: note_info}.
    """
    notebook = "iCloud-Notes"
    tracking = {}

    notes_data = [
        ("1", "Meeting-Notes-1", "Discussion about Q1 goals and deadlines"),
        ("2", "Recipe-Chicken-Curry-2", "Ingredients: chicken, curry paste, coconut milk"),
        ("3", "Project-Plan-3", "Phase 1: Research. Phase 2: Implementation"),
        ("4", "Travel-Ideas-4", "Visit Japan in spring for cherry blossoms"),
        ("5", "Book-Review-5", "The Great Gatsby - a classic American novel"),
        ("6", "Shopping-List-6", "Milk, eggs, bread, butter, cheese"),
        ("7", "Code-Snippets-7", "def hello():\n    print('Hello World')"),
        ("8", "Workout-Plan-8", "Monday: chest. Wednesday: back. Friday: legs"),
        ("9", "Garden-Notes-9", "Plant tomatoes in May. Water daily."),
        ("10", "Budget-2026-10", "Monthly expenses: rent, utilities, groceries"),
        ("11", "Deleted-Note-11", "This note was deleted"),
        ("12", "Note-With-Image-12", "A note with an embedded image"),
        ("13", "Empty-Note-13", ""),
        ("14", "Long-Note-14", "Lorem ipsum " * 500),
        ("15", "Unicode-Note-15", "Caf\u00e9 latt\u00e9 \u2014 \u00fcber cool"),
    ]

    for note_id, filename, content in notes_data:
        info = {
            "filename": filename,
            "created": "Monday, 1 January 2026 at 10:00:00 AM",
            "modified": "Wednesday, 15 January 2026 at 14:30:00",
            "firstExported": "2026-01-15 14:30:00",
            "lastExported": "2026-01-15 14:30:00",
            "exportCount": 1,
            "fullNoteId": f"x-coredata://TEST-UUID/ICNote/p{note_id}",
        }

        if note_id == "11":
            info["deletedDate"] = "Tuesday, 14 January 2026 at 09:00:00 AM"

        if note_id == "12":
            # Create an image attachment
            att_dir = test_export_dir / "md" / notebook / "attachments"
            att_dir.mkdir(exist_ok=True)
            (att_dir / f"{filename}-attachment-001.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
            content = f"![image](./attachments/{filename}-attachment-001.png)\n\n{content}"

        tracking[note_id] = info

        # Write files for non-deleted notes
        if "deletedDate" not in info:
            raw_html = f"<html><body><h1>{filename}</h1><p>{content}</p></body></html>"
            (test_export_dir / "raw" / notebook / f"{filename}.html").write_text(raw_html, encoding="utf-8")
            (test_export_dir / "text" / notebook / f"{filename}.txt").write_text(content, encoding="utf-8")
            (test_export_dir / "md" / notebook / f"{filename}.md").write_text(
                f"# {filename.replace('-', ' ')}\n\n{content}", encoding="utf-8")

    # Write tracking JSON
    json_file = test_export_dir / "data" / f"{notebook}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2)

    return tracking


@pytest.fixture
def script_dir():
    """Path to the project's script directory."""
    return SCRIPT_DIR
