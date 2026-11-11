"""notes-exporter as a service: an authenticated HTTP API that runs, schedules
and serves exports (see SERVICE-API.md)."""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
try:
    __version__ = _VERSION_FILE.read_text().strip()
except OSError:
    __version__ = "unknown"

API_VERSION = 1
MANIFEST_VERSION = 1
