"""Integration tests — run commands as subprocesses against isolated test data.

These tests never touch the live export directory. They create temp directories
with sample data and run the actual Python scripts as subprocesses.

Run with: pytest -m integration
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parent.parent


def run_script(script_name: str, args: list, env_overrides: dict = None,
               timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a Python script as a subprocess with env overrides."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script_name)] + args,
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(SCRIPT_DIR),
    )


def setup_test_export(tmp_path, num_notes=5):
    """Create a minimal export directory with sample data."""
    notebook = "iCloud-Notes"
    for d in ["data", f"raw/{notebook}", f"html/{notebook}",
              f"text/{notebook}", f"md/{notebook}"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    tracking = {}
    for i in range(1, num_notes + 1):
        filename = f"test-note-{i}"
        tracking[str(i)] = {
            "filename": filename,
            "created": "Monday, 1 January 2026 at 10:00:00 AM",
            "modified": "Wednesday, 15 January 2026 at 14:30:00",
            "firstExported": "2026-01-15 14:30:00",
            "lastExported": "2026-01-15 14:30:00",
            "exportCount": 1,
            "fullNoteId": f"x-coredata://TEST/ICNote/p{i}",
        }
        content = f"This is test note {i} about topic-{i}. Keywords: alpha beta gamma."
        html = f"<html><body><p>{content}</p></body></html>"
        (tmp_path / "raw" / notebook / f"{filename}.html").write_text(html)
        (tmp_path / "text" / notebook / f"{filename}.txt").write_text(content)
        (tmp_path / "md" / notebook / f"{filename}.md").write_text(
            f"# Test Note {i}\n\n{content}")

    # Add a deleted note
    tracking["99"] = {
        "filename": "deleted-note-99",
        "created": "Monday, 1 January 2026 at 10:00:00 AM",
        "modified": "Monday, 1 January 2026 at 10:00:00 AM",
        "firstExported": "2026-01-01 10:00:00",
        "lastExported": "2026-01-01 10:00:00",
        "exportCount": 1,
        "deletedDate": "Tuesday, 14 January 2026 at 09:00:00 AM",
    }

    json_file = tmp_path / "data" / f"{notebook}.json"
    with open(json_file, "w") as f:
        json.dump(tracking, f, indent=2)

    return tmp_path


# ── Search Integration Tests ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.search
class TestQueryNotesIntegration:
    def test_text_search_finds_results(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "alpha" in result.stdout.lower() or "match" in result.stderr.lower()

    def test_text_search_no_results(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["zzz_nonexistent_term_zzz"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "0 match" in result.stderr

    def test_regex_search(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["-E", "topic-[0-9]+"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "topic-" in result.stdout

    def test_case_insensitive(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["-i", "ALPHA"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "match" in result.stderr.lower()

    def test_files_only(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["-l", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert ".md" in result.stdout

    def test_context_lines(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["-c", "1", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "|" in result.stdout  # Context lines have | separator

    def test_format_filter(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["--format", "text", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0

    def test_json_output_to_stdout(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("query_notes.py", ["--json-log", "-", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        for line in lines:
            record = json.loads(line)
            assert "type" in record

    def test_json_output_to_file(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        json_file = tmp_path / "results.jsonl"
        result = run_script("query_notes.py",
                           ["--json-log", str(json_file), "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert json_file.exists()
        lines = json_file.read_text().strip().split("\n")
        assert any(json.loads(l)["type"] == "summary" for l in lines)

    def test_date_filter_modified_within(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        # All test notes have modified date in 2026 — "within 1y" should find them
        result = run_script("query_notes.py",
                           ["--modified-within", "100y", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0

    def test_has_images_filter(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        # No test notes have images
        result = run_script("query_notes.py",
                           ["--has-images", "-l", "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "0 file" in result.stderr

    def test_max_matches(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        json_file = tmp_path / "results.jsonl"
        result = run_script("query_notes.py",
                           ["-m", "1", "--json-log", str(json_file), "alpha"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        lines = [json.loads(l) for l in json_file.read_text().strip().split("\n") if l.strip()]
        matches = [r for r in lines if r["type"] == "match"]
        # Each file should have at most 1 match
        from collections import Counter
        for count in Counter(r["file"] for r in matches).values():
            assert count <= 1


# ── Reconcile Integration Tests ───────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.reconcile
class TestReconcileIntegration:
    def test_basic_reconcile(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("reconcile.py", ["--skip-apple", "--skip-qdrant"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "RECONCILIATION REPORT" in result.stdout
        assert "Tracking JSON" in result.stdout

    def test_reconcile_with_notebooks(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("reconcile.py",
                           ["--skip-apple", "--skip-qdrant", "--notebooks"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "iCloud-Notes" in result.stdout

    def test_reconcile_with_details(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        # Add an orphan file to trigger a discrepancy
        (tmp_path / "raw" / "iCloud-Notes" / "orphan.html").write_text("orphan")
        result = run_script("reconcile.py",
                           ["--skip-apple", "--skip-qdrant", "--details"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "orphan" in result.stdout

    def test_reconcile_json_output(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("reconcile.py",
                           ["--skip-apple", "--skip-qdrant", "--json-log"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) > 0
        for line in lines:
            record = json.loads(line)
            assert "type" in record

    def test_reconcile_json_has_counts(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("reconcile.py",
                           ["--skip-apple", "--skip-qdrant", "--json-log"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        lines = [json.loads(l) for l in result.stdout.strip().split("\n") if l.strip()]
        json_count = next((r for r in lines if r.get("source") == "tracking_json"), None)
        assert json_count is not None
        assert json_count["active"] == 5
        assert json_count["deleted"] == 1


# ── Sync Integration Tests ───────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.sync
class TestSyncIntegration:
    def test_sync_dry_run(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("sync_to_notes.py", ["--dry-run"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        assert "SYNC SUMMARY" in result.stdout

    def test_sync_dry_run_json(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("sync_to_notes.py", ["--dry-run", "--json-log"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        summaries = [json.loads(l) for l in lines if json.loads(l).get("type") == "summary"]
        assert len(summaries) >= 1
        assert summaries[0]["command"] == "sync_to_notes"


# ── Qdrant Integration Tests ─────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.qdrant
class TestQdrantIntegration:
    def test_check_command(self):
        """Check command should always work (reports status even if Qdrant is down)."""
        result = run_script("qdrant_integration.py", ["check"])
        assert result.returncode == 0
        assert "Prerequisites" in result.stdout

    def test_check_json_output(self, tmp_path):
        json_file = tmp_path / "check.jsonl"
        result = run_script("qdrant_integration.py",
                           ["--json-log", str(json_file), "check"])
        assert result.returncode == 0
        assert json_file.exists()
        lines = [l for l in json_file.read_text().strip().split("\n") if l.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["type"] == "status"
        assert record["command"] == "check"
        assert "docker" in record
        assert "qdrant" in record
        assert "embeddings" in record

    def test_status_command(self):
        """Status should work even if collection doesn't exist."""
        result = run_script("qdrant_integration.py", ["status"])
        # May fail if Qdrant not running, that's OK for CI
        # Just verify it doesn't crash
        assert result.returncode == 0 or "Cannot connect" in result.stderr

    def test_dry_run_command(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        result = run_script("qdrant_integration.py", ["dry-run"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        # May fail if Qdrant not running
        if result.returncode == 0:
            assert "DRY RUN" in result.stdout

    def test_dry_run_json(self, tmp_path):
        export_dir = setup_test_export(tmp_path)
        json_file = tmp_path / "dry-run.jsonl"
        result = run_script("qdrant_integration.py",
                           ["--json-log", str(json_file), "dry-run"],
                           env_overrides={"NOTES_EXPORT_ROOT_DIR": str(export_dir)})
        if result.returncode == 0 and json_file.exists():
            lines = [l for l in json_file.read_text().strip().split("\n") if l.strip()]
            if lines:
                record = json.loads(lines[0])
                assert "type" in record


# ── Settings Integration Tests ────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.settings
class TestSettingsIntegration:
    def test_settings_file_loaded(self, tmp_path, monkeypatch):
        """Settings file in script dir should be picked up."""
        settings = {
            "conflictStrategy": "local",
            "createNewNotes": True,
        }
        settings_file = SCRIPT_DIR / ".notes-exporter-settings.json"
        created = False
        if not settings_file.exists():
            settings_file.write_text(json.dumps(settings))
            created = True
        try:
            from sync_settings import load_settings
            loaded = load_settings()
            if created:
                assert loaded["conflictStrategy"] == "local"
        finally:
            if created:
                settings_file.unlink(missing_ok=True)


# ── Export Feature Integration Tests ──────────────────────────────────────

@pytest.mark.integration
@pytest.mark.export
class TestExportFeaturesIntegration:
    def test_help_output(self):
        result = run_script("query_notes.py", ["--help"])
        assert result.returncode == 0
        assert "--json-log" in result.stdout
        assert "--ai-search" in result.stdout
        assert "--has-images" in result.stdout
        assert "--modified-within" in result.stdout

    def test_reconcile_help(self):
        result = run_script("reconcile.py", ["--help"])
        assert result.returncode == 0
        assert "--json-log" in result.stdout
        assert "--skip-apple" in result.stdout
        assert "--details" in result.stdout

    def test_qdrant_help(self):
        result = run_script("qdrant_integration.py", ["--help"])
        assert result.returncode == 0
        assert "--json-log" in result.stdout

    def test_sync_help(self):
        result = run_script("sync_to_notes.py", ["--help"])
        assert result.returncode == 0
        assert "--json-log" in result.stdout
        assert "--dry-run" in result.stdout
