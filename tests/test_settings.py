import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_settings import (
    DEFAULT_SETTINGS,
    apply_cli_overrides,
    load_settings,
    save_default_settings,
)


@pytest.mark.unit
@pytest.mark.settings
class TestDefaultSettings:
    def test_has_required_keys(self):
        assert "editFormat" in DEFAULT_SETTINGS
        assert "autoRegenerate" in DEFAULT_SETTINGS
        assert "conflictStrategy" in DEFAULT_SETTINGS
        assert "syncSource" in DEFAULT_SETTINGS
        assert "createNewNotes" in DEFAULT_SETTINGS

    def test_default_values(self):
        assert DEFAULT_SETTINGS["editFormat"] == "markdown"
        assert DEFAULT_SETTINGS["conflictStrategy"] == "abort"
        assert DEFAULT_SETTINGS["createNewNotes"] is False
        assert DEFAULT_SETTINGS["autoRegenerate"]["html"] is True
        assert DEFAULT_SETTINGS["autoRegenerate"]["pdf"] is False


@pytest.mark.unit
@pytest.mark.settings
class TestLoadSettings:
    def test_returns_defaults_when_no_file(self, monkeypatch):
        monkeypatch.delenv("NOTES_EXPORT_SYNC_SOURCE", raising=False)
        monkeypatch.delenv("NOTES_EXPORT_CONFLICT_STRATEGY", raising=False)
        monkeypatch.delenv("NOTES_EXPORT_CREATE_NEW", raising=False)
        settings = load_settings()
        assert settings["editFormat"] == "markdown"
        assert settings["conflictStrategy"] == "abort"

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_CONFLICT_STRATEGY", "local")
        monkeypatch.setenv("NOTES_EXPORT_CREATE_NEW", "true")
        settings = load_settings()
        assert settings["conflictStrategy"] == "local"
        assert settings["createNewNotes"] is True

    def test_env_var_create_new_false(self, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_CREATE_NEW", "false")
        settings = load_settings()
        assert settings["createNewNotes"] is False


@pytest.mark.unit
@pytest.mark.settings
class TestSaveDefaultSettings:
    def test_creates_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            save_default_settings(path)
            with open(path) as f:
                data = json.load(f)
            assert data["editFormat"] == "markdown"
            assert data["conflictStrategy"] == "abort"
        finally:
            path.unlink(missing_ok=True)


@pytest.mark.unit
@pytest.mark.settings
class TestApplyCliOverrides:
    def test_conflict_override(self):
        settings = load_settings()
        settings = apply_cli_overrides(settings, conflict="local")
        assert settings["conflictStrategy"] == "local"

    def test_create_new_override(self):
        settings = load_settings()
        settings = apply_cli_overrides(settings, create_new=True)
        assert settings["createNewNotes"] is True

    def test_no_override_preserves_defaults(self):
        settings = load_settings()
        original = settings.copy()
        settings = apply_cli_overrides(settings)
        assert settings["conflictStrategy"] == original["conflictStrategy"]

    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_CONFLICT_STRATEGY", "remote")
        settings = load_settings()
        assert settings["conflictStrategy"] == "remote"
        settings = apply_cli_overrides(settings, conflict="local")
        assert settings["conflictStrategy"] == "local"
