"""Export settings (``service.json``) and how they become exporter options."""

import errno
import json
import os
import re
import sys
import tempfile
import uuid
import threading
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .config import Config

ALL_FORMATS = ("raw", "text", "html", "md", "pdf", "docx", "epub")
# Formats a run may ask for (raw is always written: it is the source of the others).
RUN_FORMATS = ("html", "md", "pdf", "docx", "epub", "text")
IMAGE_FORMATS = ("jpeg", "png", "heic", "tiff", "webp")
# Settings a `settings`-scope key can read but not change: where the export is written is the
# Mac's own business (a key could otherwise point the exporter at any folder of its user's).
# Whether clients may write to Notes is the Mac owner's decision too, and so are the fences
# around those writes (backups, limits): a client can't loosen them.
WRITE_FENCES = ("write_backup_folder", "write_backup_required", "write_backup_export",
                "write_max_changes_per_hour", "write_max_changes_per_day", "write_hold_batch_over",
                "write_hold_batch_seconds", "write_hold_count_over", "write_hold_window_hours",
                "write_hold_change_percent", "write_hold_min_lines", "write_hold_max_age_days",
                "login_link_ttl_seconds")
CLIENT_READ_ONLY = ("export_root", "allow_writes") + WRITE_FENCES
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# Fields GET /api/admin/settings adds to the settings (how the export folder is right now). A
# client that sends the settings back whole may include them: they are dropped, never saved.
# export_root_check reasons that refuse a new export_root and stop a run before it starts
# (probe_failed doesn't: an unexplained error is reported, never trusted to block an export).
REFUSING_REASONS = ("drive_not_mounted", "not_a_folder", "not_writable", "access_denied")
DERIVED_FIELDS = ("export_root_ok", "export_root_problem", "export_root_access", "export_root_reason")


class SettingsError(ValueError):
    """An invalid setting. ``reason`` is machine-readable (SERVICE-API.md "Refusals"),
    ``field`` the setting it is about (None when it isn't one field)."""

    def __init__(self, message: str, reason: str = "invalid", field: Optional[str] = None):
        super().__init__(message)
        self.reason = reason
        self.field = field


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
    epub_books: Literal["none", "folder"] = "none"
    epub_book_order: Literal["modified", "created", "title"] = "modified"
    epub_book_subfolders: Literal["separate", "nested"] = "separate"
    schedule: Schedule = Field(default_factory=Schedule)
    # Clients with the `write` scope may change and create notes (notes_service/writes.py).
    allow_writes: bool = False
    # Before an update (and a delete that asks for it) the note is copied into this folder of
    # its account, beneath it the note's own folder path (writes.py).
    write_backup_folder: str = "Notes Exporter Backups"
    # Clients may not skip the backup of an update (backup: "none").
    write_backup_required: bool = True
    # Export the backup folder like any other (off: exports leave it out).
    write_backup_export: bool = False
    # Mass-change guard: changes (updates, new notes, deletes) allowed in any hour / day; 0 = no limit.
    write_max_changes_per_hour: int = 50
    write_max_changes_per_day: int = 200
    # The approval list (approvals.py): a write tripping one of these is held, not made, until
    # someone with the approve scope approves it. 0 turns a rule off.
    write_hold_batch_over: int = 3          # more than this many writes by one client within …
    write_hold_batch_seconds: int = 60      # … this many seconds
    write_hold_count_over: int = 5          # more than this many changes made within …
    write_hold_window_hours: int = 24       # … this many hours
    write_hold_change_percent: int = 50     # more than this share of a note's words changed …
    write_hold_min_lines: int = 2           # … for a note longer than this many lines (a delete: 100 %)
    write_hold_max_age_days: int = 0        # held writes older than this are dropped; 0 = kept
    # A one-off sign-in link for the web page (POST /api/auth/login-link) lasts this long.
    login_link_ttl_seconds: int = 60

    @field_validator("formats")
    @classmethod
    def _formats(cls, v):
        bad = [f for f in v if f not in ALL_FORMATS]
        if bad:
            raise ValueError(f"unknown formats {bad}; use {list(ALL_FORMATS)}")
        return [f for f in ALL_FORMATS if f in v] or ["html"]

    @field_validator("write_backup_folder")
    @classmethod
    def _backup_folder(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("write_backup_folder needs a folder name")
        if len(v) > 100 or any(c in v for c in "/,\n\r\t\0") or v.startswith("-"):
            raise ValueError("write_backup_folder: one folder name (up to 100 characters) without '/', commas "
                             "or line breaks, not starting with '-'")
        return v

    @field_validator("write_max_changes_per_hour", "write_max_changes_per_day", "write_hold_batch_over",
                     "write_hold_count_over", "write_hold_change_percent", "write_hold_min_lines",
                     "write_hold_max_age_days")
    @classmethod
    def _limits(cls, v):
        if v < 0:
            raise ValueError("write limits must be 0 (off) or more")
        return v

    @field_validator("write_hold_batch_seconds")
    @classmethod
    def _batch_seconds(cls, v):
        if not 1 <= v <= 86400:
            raise ValueError("write_hold_batch_seconds must be 1-86400")
        return v

    @field_validator("write_hold_window_hours")
    @classmethod
    def _window(cls, v):
        if not 1 <= v <= 24 * 31:
            raise ValueError("write_hold_window_hours must be 1-744")
        return v

    @field_validator("login_link_ttl_seconds")
    @classmethod
    def _link_ttl(cls, v):
        if not 10 <= v <= 600:
            raise ValueError("login_link_ttl_seconds must be 10-600")
        return v

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


_ismount = os.path.ismount  # tests replace it
_PROBE_PREFIX = ".notes-exporter-probe-"


def _drive_problem(root: str) -> Optional[str]:
    parts = Path(os.path.expanduser(str(root))).parts
    if len(parts) > 2 and parts[0] == "/" and parts[1] == "Volumes":
        volume = os.path.join("/Volumes", parts[2])
        if os.path.islink(volume) and os.path.realpath(volume) == "/":
            return None  # /Volumes/Macintosh HD is the startup disk
        if not _ismount(volume):
            return f"the drive \u201c{parts[2]}\u201d isn't connected ({volume} is not mounted)"
    return None


def service_python() -> str:
    """The program macOS's privacy settings must allow: the service's own Python, as a real path
    (a venv's python is a symlink, and System Settings lists the file it points at)."""
    return os.path.realpath(sys.executable)


def _probe_dir(root: str) -> Optional[str]:
    """Where an export would first write: the root, or (before the first export) the nearest folder
    above it that exists, since the export creates the rest."""
    path = os.path.expanduser(str(root))
    while path and not os.path.lexists(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return path or None


def _write_probe(folder: str) -> Optional[OSError]:
    """Create and remove a hidden empty file in ``folder``; the error, or None when it worked."""
    name = os.path.join(folder, f"{_PROBE_PREFIX}{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as e:
        return e
    os.close(fd)
    try:
        os.unlink(name)
    except OSError:
        pass
    return None


def export_root_check(root: str) -> dict:
    """How the export folder is now: ``{access, reason, problem}``.

    ``access`` is ``ok`` (a file can be created there), ``denied`` (macOS refuses the service —
    EPERM, or EACCES where the permission bits allow it: privacy settings, TCC), ``not_writable``
    (the folder's permissions or a read-only drive), ``missing`` (its drive isn't connected) or
    ``unknown``. ``reason`` is the machine-readable refusal (``drive_not_mounted``,
    ``not_a_folder``, ``not_writable``, ``access_denied``, ``probe_failed``) or None, ``problem``
    the same in words or None. Probed by creating and removing a hidden file, in the root or —
    before the first export made it — the nearest folder above it.
    """
    drive = _drive_problem(root)
    if drive:
        return {"access": "missing", "reason": "drive_not_mounted", "problem": drive}
    path = os.path.expanduser(str(root))
    if os.path.lexists(path) and not os.path.isdir(path):
        return {"access": "not_writable", "reason": "not_a_folder",
                "problem": f"{path} is a file, not a folder"}
    folder = _probe_dir(path)
    if not folder:
        return {"access": "unknown", "reason": "probe_failed", "problem": f"no folder above {path} exists"}
    if not os.path.isdir(folder):
        return {"access": "not_writable", "reason": "not_a_folder",
                "problem": f"{folder} is a file, not a folder"}
    err = _write_probe(folder)
    if err is None:
        return {"access": "ok", "reason": None, "problem": None}
    why = err.strerror or err.__class__.__name__
    if err.errno == errno.EROFS:
        return {"access": "not_writable", "reason": "not_writable",
                "problem": f"the service can't write to {folder}: {why} (the drive is read-only)"}
    if err.errno == errno.EPERM or (err.errno == errno.EACCES and os.access(folder, os.W_OK)):
        return {"access": "denied", "reason": "access_denied",
                "problem": (f"the service can't write to {folder}: {why} \u2014 macOS is refusing it. Allow "
                            f"{service_python()} in System Settings \u2192 Privacy & Security \u2192 Full Disk "
                            f"Access (or Files and Folders, for a drive: Removable Volumes / Network Volumes), "
                            f"then restart the service")}
    if err.errno == errno.EACCES:
        return {"access": "not_writable", "reason": "not_writable",
                "problem": f"the service can't write to {folder}: {why} (check the folder's permissions)"}
    return {"access": "unknown", "reason": "probe_failed",
            "problem": f"couldn't check that {folder} can be written: {why}"}


def export_root_problem(root: str) -> Optional[str]:
    """Why an export can't be written to ``root`` now, else None.

    A root on another drive (``/Volumes/<name>/…``) needs that drive mounted: otherwise
    creating the folder would make ``/Volumes/<name>`` on the internal disk and the whole
    export would quietly be written there instead. Only the drive is checked here (no disk
    writes); ``export_root_check`` also probes whether the folder can be written.
    """
    return _drive_problem(root)


def export_root_state(root: str) -> dict:
    """The fields /api/status and the settings endpoints report about the export folder:
    ``export_root_ok`` (exists and a file can be created in it), ``export_root_problem`` (why not,
    or None — a folder the first export hasn't made yet is no problem), ``export_root_access``
    (``export_root_check``'s ``access``) and ``export_root_reason``."""
    check = export_root_check(root)
    path = os.path.expanduser(str(root))
    return {"export_root_ok": check["access"] == "ok" and os.path.isdir(path),
            "export_root_problem": check["problem"],
            "export_root_access": check["access"],
            "export_root_reason": check["reason"]}


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
            raise SettingsError("export_root must be an absolute path", "not_absolute", "export_root")
        home = self.config.home.resolve()
        resolved = root.resolve()
        if _inside(resolved, home) or _inside(home, resolved):
            raise SettingsError("export_root may not contain, or be inside, the service's state directory",
                                "inside_state_dir", "export_root")
        if self.config.min_interval_minutes and settings.schedule.interval_minutes is not None \
                and settings.schedule.interval_minutes < self.config.min_interval_minutes:
            raise SettingsError(f"schedule.interval_minutes must be at least {self.config.min_interval_minutes}",
                                "invalid", "schedule")
        return settings.model_copy(update={"export_root": str(root)})

    def update(self, changes: dict, check_root: bool = False) -> Settings:
        """Merge ``changes`` (any subset of the fields) into the stored settings.

        ``check_root`` (the HTTP endpoints): a *new* ``export_root`` must also be writable now —
        its drive connected, the folder (or the nearest one above it) writable by the service —
        else SettingsError with ``export_root_check``'s reason. An unchanged one is never refused,
        so other settings can be saved while the drive is away.
        """
        changes = {k: v for k, v in changes.items() if k not in DERIVED_FIELDS}
        current = self.load().model_dump()
        if "schedule" in changes and isinstance(changes["schedule"], dict):
            merged_schedule = dict(current["schedule"])
            merged_schedule.update(changes["schedule"])
            changes = dict(changes, schedule=merged_schedule)
        unknown = set(changes) - set(Settings.model_fields)
        if unknown:
            raise SettingsError(f"unknown settings: {sorted(unknown)}", "unknown_settings")
        old_root = current["export_root"]
        current.update(changes)
        try:
            settings = Settings.model_validate(current)
        except ValidationError as e:
            fields = {str(err["loc"][0]) for err in e.errors() if err.get("loc")}
            raise SettingsError("; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors()),
                                "invalid", fields.pop() if len(fields) == 1 else None)
        settings = self.validate(settings)
        if check_root and settings.export_root != os.path.expanduser(old_root):
            check = export_root_check(settings.export_root)
            if check["reason"] in REFUSING_REASONS:
                raise SettingsError(f"export_root: {check['problem']}", check["reason"], "export_root")
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
    if wanted & {"md", "pdf", "docx", "epub"}:
        wanted.add("html")  # conversions are made from the HTML with its images
    return [f for f in ALL_FORMATS if f in wanted]


def effective_epub_books(settings: "Settings", requested: Optional[str] = None) -> str:
    """Folder books when the settings or the run ask for them (a union, like formats)."""
    return "folder" if "folder" in (settings.epub_books, requested) else "none"


def _tf(value: bool) -> str:
    return "true" if value else "false"


def exporter_args(config: Config, settings: Settings, *, json_log: Path, mode: str = "incremental",
                  folders: Optional[List[str]] = None, accounts: Optional[List[str]] = None,
                  formats: Optional[List[str]] = None, epub_books: Optional[str] = None) -> List[str]:
    """The exportnotes.zsh command line for one run (INTEGRATION.md "Recommended invocation")."""
    fmts = set(produced_formats(settings.formats, formats))
    books = effective_epub_books(settings, epub_books)
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
        "--convert-epub", _tf("epub" in fmts),
        "--epub-books", books,
        "--epub-book-order", settings.epub_book_order,
        "--epub-book-subfolders", settings.epub_book_subfolders,
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
    excluded = list(settings.exclude_folders)
    if not settings.write_backup_export:
        # The backups the service made in Notes stay out of the export (and so out of clients).
        from .write_state import WriteState
        state = WriteState(config)
        if settings.allow_writes or state.backup_folders():
            excluded += [f for f in state.backup_exclusions(settings.write_backup_folder) if f not in excluded]
    if excluded:
        args += ["--exclude-folders", ",".join(excluded)]
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
