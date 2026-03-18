import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_SETTINGS = {
    "editFormat": "markdown",
    "autoRegenerate": {
        "html": True,
        "pdf": False,
        "word": False
    },
    "conflictStrategy": "abort",
    "syncSource": "markdown",
    "createNewNotes": False
}

SETTINGS_FILENAME = ".notes-exporter-settings.json"


def find_settings_file() -> Optional[Path]:
    """Find the settings file, checking script directory first, then export root."""
    # Check script directory
    script_dir = Path(__file__).parent
    settings_path = script_dir / SETTINGS_FILENAME
    if settings_path.exists():
        return settings_path

    # Check export root directory
    root_dir = os.getenv("NOTES_EXPORT_ROOT_DIR")
    if root_dir:
        settings_path = Path(root_dir) / SETTINGS_FILENAME
        if settings_path.exists():
            return settings_path

    return None


def load_settings() -> Dict[str, Any]:
    """Load settings from file, falling back to defaults."""
    settings = DEFAULT_SETTINGS.copy()
    settings["autoRegenerate"] = DEFAULT_SETTINGS["autoRegenerate"].copy()

    settings_file = find_settings_file()
    if settings_file:
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                file_settings = json.load(f)
            # Merge file settings over defaults
            for key, value in file_settings.items():
                if key == "autoRegenerate" and isinstance(value, dict):
                    settings["autoRegenerate"].update(value)
                else:
                    settings[key] = value
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load settings from {settings_file}: {e}")

    # Environment variable overrides
    env_map = {
        "NOTES_EXPORT_SYNC_SOURCE": "syncSource",
        "NOTES_EXPORT_CONFLICT_STRATEGY": "conflictStrategy",
        "NOTES_EXPORT_CREATE_NEW": "createNewNotes",
    }
    for env_key, settings_key in env_map.items():
        env_val = os.getenv(env_key)
        if env_val is not None:
            if settings_key == "createNewNotes":
                settings[settings_key] = env_val.lower() == "true"
            else:
                settings[settings_key] = env_val

    return settings


def save_default_settings(path: Optional[Path] = None) -> Path:
    """Save default settings to file. Returns the path written to."""
    if path is None:
        path = Path(__file__).parent / SETTINGS_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SETTINGS, f, indent=2)
    return path


def apply_cli_overrides(settings: Dict[str, Any],
                        conflict: Optional[str] = None,
                        create_new: Optional[bool] = None,
                        sync_source: Optional[str] = None) -> Dict[str, Any]:
    """Apply CLI flag overrides to settings. CLI flags take highest precedence."""
    if conflict is not None:
        settings["conflictStrategy"] = conflict
    if create_new is not None:
        settings["createNewNotes"] = create_new
    if sync_source is not None:
        settings["syncSource"] = sync_source
    return settings
