"""Export settings (``service.json``) and how they become exporter options."""

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .config import Config

ALL_FORMATS = ("raw", "text", "html", "md", "pdf", "docx")
# Formats a run may ask for (raw is always written: it is the source of the others).
RUN_FORMATS = ("html", "md", "pdf", "docx", "text")
IMAGE_FORMATS = ("jpeg", "png", "heic", "tiff", "webp")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class SettingsError(ValueError):
    pass


def _clean_names(values: List[str], what: str) -> List[str]:
    out = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        if "," in v or v.startswith("-") or "\n" in v or "\0" in v:
            raise ValueError(f"{what} {v!r}: names may not contain commas or line breaks or start with '-'")
        out.append(v)
    return out


class Schedule(BaseModel):
    enabled: bool = False
    interval_minutes: Optional[int] = None
    daily_at: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.interval_minutes is not None and self.daily_at:
            raise ValueError("schedule: give interval_minutes or daily_at, not both")
        if self.daily_at and not _HHMM.match(self.daily_at):
            raise ValueError("schedule.daily_at must be HH:MM (24-hour)")
        if self.interval_minutes is not None and self.interval_minutes < 1:
            raise ValueError("schedule.interval_minutes must be positive")
        if self.enabled and self.interval_minutes is None and not self.daily_at:
            raise ValueError("schedule: an enabled schedule needs interval_minutes or daily_at")
        return self


class Settings(BaseModel):
    export_root: str
    formats: List[str] = Field(default_factory=lambda: ["html"])
    folder_hierarchy: bool = False
    exclude_folders: List[str] = Field(default_factory=lambda: ["Recently Deleted"])
    prune_deleted: bool = True
    tags: bool = False
    tags_in_content: bool = False
    html_wrap: bool = True
    image_format: Optional[str] = None
    image_format_from: List[str] = Field(default_factory=list)
    image_quality: Optional[int] = None
    schedule: Schedule = Field(default_factory=Schedule)

    @field_validator("formats")
    @classmethod
    def _formats(cls, v):
        bad = [f for f in v if f not in ALL_FORMATS]
        if bad:
            raise ValueError(f"unknown formats {bad}; use {list(ALL_FORMATS)}")
        return [f for f in ALL_FORMATS if f in v] or ["html"]

    @field_validator("exclude_folders")
    @classmethod
    def _exclude(cls, v):
        return _clean_names(v, "folder")

    @field_validator("image_format")
    @classmethod
    def _image_format(cls, v):
        if v in (None, ""):
            return None
        if v not in IMAGE_FORMATS:
            raise ValueError(f"image_format must be one of {list(IMAGE_FORMATS)}")
        return v

    @field_validator("image_format_from")
    @classmethod
    def _image_from(cls, v):
        return _clean_names([x.lower() for x in v], "image type")

    @field_validator("image_quality")
    @classmethod
    def _quality(cls, v):
        if v is not None and not 1 <= v <= 100:
            raise ValueError("image_quality must be 1-100")
        return v


def default_export_root() -> str:
    return str(Path.home() / "Downloads" / "AppleNotesExport")


def default_settings() -> Settings:
    return Settings(export_root=default_export_root())


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class SettingsStore:
    """service.json, read and written whole (atomically)."""

    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()

    def load(self) -> Settings:
        path = self.config.settings_file
        with self._lock:
            if not path.exists():
                return default_settings()
            data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("export_root", default_export_root())
        return Settings.model_validate(data)

    def validate(self, settings: Settings) -> Settings:
        root = Path(os.path.expanduser(settings.export_root))
        if not root.is_absolute():
            raise SettingsError("export_root must be an absolute path")
        home = self.config.home.resolve()
        resolved = root.resolve()
        if _inside(resolved, home) or _inside(home, resolved):
            raise SettingsError("export_root may not contain, or be inside, the service's state directory")
        if self.config.min_interval_minutes and settings.schedule.interval_minutes is not None \
                and settings.schedule.interval_minutes < self.config.min_interval_minutes:
            raise SettingsError(f"schedule.interval_minutes must be at least {self.config.min_interval_minutes}")
        return settings.model_copy(update={"export_root": str(root)})

    def update(self, changes: dict) -> Settings:
        """Merge ``changes`` (any subset of the fields) into the stored settings."""
        current = self.load().model_dump()
        if "schedule" in changes and isinstance(changes["schedule"], dict):
            merged_schedule = dict(current["schedule"])
            merged_schedule.update(changes["schedule"])
            changes = dict(changes, schedule=merged_schedule)
        unknown = set(changes) - set(Settings.model_fields)
        if unknown:
            raise SettingsError(f"unknown settings: {sorted(unknown)}")
        current.update(changes)
        try:
            settings = Settings.model_validate(current)
        except ValidationError as e:
            raise SettingsError("; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors()))
        settings = self.validate(settings)
        self.save(settings)
        return settings

    def save(self, settings: Settings) -> None:
        self.config.ensure_home()
        path = self.config.settings_file
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".service.", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings.model_dump(), f, indent=2)
                f.write("\n")
            os.replace(tmp, path)


def produced_formats(settings_formats: List[str], requested: Optional[List[str]] = None) -> List[str]:
    """What a run writes: raw and text always, the union of settings and request."""
    wanted = set(settings_formats) | set(requested or []) | {"raw", "text"}
    if wanted & {"md", "pdf", "docx"}:
        wanted.add("html")  # conversions are made from the HTML with its images
    return [f for f in ALL_FORMATS if f in wanted]


def _tf(value: bool) -> str:
    return "true" if value else "false"


def exporter_args(config: Config, settings: Settings, *, json_log: Path, mode: str = "incremental",
                  folders: Optional[List[str]] = None, accounts: Optional[List[str]] = None,
                  formats: Optional[List[str]] = None) -> List[str]:
    """The exportnotes.zsh command line for one run (INTEGRATION.md "Recommended invocation")."""
    fmts = set(produced_formats(settings.formats, formats))
    args = [
        str(config.exporter),
        "--root-dir", settings.export_root,
        "--python", config.python,
        "--json-log", str(json_log),
        "--non-interactive", "true",
        "--extract-images", _tf("html" in fmts),
        "--convert-markdown", _tf("md" in fmts),
        "--convert-pdf", _tf("pdf" in fmts),
        "--convert-word", _tf("docx" in fmts),
        "--html-wrap", _tf(settings.html_wrap),
        "--prune-deleted", _tf(settings.prune_deleted),
        "--tags", _tf(settings.tags),
        "--tags-in-content", _tf(settings.tags_in_content),
        "--update-all", _tf(mode == "full"),
        # Never write to Apple Notes, whatever an environment variable says.
        "--sync", "false", "--sync-only", "false", "--update-qdrant", "false",
    ]
    if settings.folder_hierarchy:
        args.append("--folder-hierarchy")
    if settings.exclude_folders:
        args += ["--exclude-folders", ",".join(settings.exclude_folders)]
    if settings.image_format:
        args += ["--image-format", settings.image_format]
        if settings.image_format_from:
            args += ["--image-format-from", ",".join(settings.image_format_from)]
        if settings.image_quality:
            args += ["--image-quality", str(settings.image_quality)]
    if folders:
        args += ["--filter-folders", ",".join(_clean_names(folders, "folder"))]
    if accounts:
        args += ["--filter-accounts", ",".join(_clean_names(accounts, "account"))]
    return args


# Variables never handed to the exporter, even when named in NOTES_SERVICE_PASS_ENV.
_BLOCKED_ENV = re.compile(r"^NOTES_EXPORT_(SYNC|SYNC_ONLY|SYNC_DRY_RUN|CREATE_NEW|UPDATE_QDRANT|CONFLICT_STRATEGY)$")


def exporter_env(config: Config) -> dict:
    """A clean environment: nothing inherited from a shell rc file changes the run."""
    src = os.environ
    env = {
        "HOME": src.get("HOME", str(Path.home())),
        "PATH": config.exporter_path,
        "LANG": "en_US.UTF-8",
        "LC_CTYPE": "en_US.UTF-8",
    }
    for name in ("USER", "LOGNAME", "TMPDIR"):
        if src.get(name):
            env[name] = src[name]
    for name in config.pass_env:
        if name in src and not _BLOCKED_ENV.match(name) and name != "PATH":
            env[name] = src[name]
    return env
