"""Service configuration: tunables from the environment, with defaults.

Everything an operator may want to change (ports, timeouts, rate limits,
session length, grace periods) is a ``NOTES_SERVICE_*`` variable. These are
process settings, not the export settings in ``service.json`` that an admin
edits over the API: the exporter's path, the Python it runs with and the
environment handed to it can't be changed from the web, because that would
let an API call choose what program runs.
"""

import os
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import List

REPO_DIR = Path(__file__).resolve().parent.parent

DEFAULT_EXPORTER_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def default_home() -> Path:
    return Path.home() / "Library" / "Application Support" / "notes-exporter"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    home: Path = field(default_factory=default_home)
    host: str = "127.0.0.1"
    port: int = 8790
    allow_remote: bool = False
    session_hours: float = 24.0
    login_max_attempts: int = 10
    login_window_seconds: float = 300.0
    min_password_length: int = 8
    bcrypt_rounds: int = 12
    cancel_grace_seconds: float = 10.0
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = 30.0
    min_interval_minutes: int = 5
    permission_check: bool = True
    permission_cache_seconds: float = 300.0
    permission_timeout_seconds: float = 10.0
    permission_helper: Path = REPO_DIR / "notes_permission.py"
    permission_request_timeout_seconds: float = 180.0
    permission_launch_wait_seconds: float = 20.0
    security_bin: str = "/usr/bin/security"
    keychain: str = ""
    keychain_service: str = "notes-exporter"
    generated_password_bytes: int = 24
    cli_session_minutes: float = 10.0
    exporter: Path = REPO_DIR / "exportnotes.zsh"
    python: str = sys.executable
    exporter_path: str = DEFAULT_EXPORTER_PATH
    pass_env: List[str] = field(default_factory=list)
    file_chunk_bytes: int = 256 * 1024
    runs_keep: int = 200
    progress_write_seconds: float = 1.0
    key_touch_seconds: float = 60.0
    docs: bool = False

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        e = os.environ
        cfg = cls(
            home=Path(_env("NOTES_SERVICE_HOME", str(default_home()))).expanduser(),
            host=_env("NOTES_SERVICE_HOST", "127.0.0.1"),
            port=int(_env("NOTES_SERVICE_PORT", "8790")),
            allow_remote=_bool("NOTES_SERVICE_ALLOW_REMOTE", False),
            session_hours=float(_env("NOTES_SERVICE_SESSION_HOURS", "24")),
            login_max_attempts=int(_env("NOTES_SERVICE_LOGIN_MAX_ATTEMPTS", "10")),
            login_window_seconds=float(_env("NOTES_SERVICE_LOGIN_WINDOW_SECONDS", "300")),
            min_password_length=int(_env("NOTES_SERVICE_MIN_PASSWORD_LENGTH", "8")),
            bcrypt_rounds=int(_env("NOTES_SERVICE_BCRYPT_ROUNDS", "12")),
            cancel_grace_seconds=float(_env("NOTES_SERVICE_CANCEL_GRACE_SECONDS", "10")),
            scheduler_enabled=_bool("NOTES_SERVICE_SCHEDULER", True),
            scheduler_tick_seconds=float(_env("NOTES_SERVICE_SCHEDULER_TICK_SECONDS", "30")),
            min_interval_minutes=int(_env("NOTES_SERVICE_MIN_INTERVAL_MINUTES", "5")),
            permission_check=_bool("NOTES_SERVICE_PERMISSION_CHECK", True),
            permission_cache_seconds=float(_env("NOTES_SERVICE_PERMISSION_CACHE_SECONDS", "300")),
            permission_timeout_seconds=float(_env("NOTES_SERVICE_PERMISSION_TIMEOUT_SECONDS", "10")),
            permission_helper=Path(_env("NOTES_SERVICE_PERMISSION_HELPER",
                                        str(REPO_DIR / "notes_permission.py"))).expanduser(),
            permission_request_timeout_seconds=float(_env("NOTES_SERVICE_PERMISSION_REQUEST_TIMEOUT_SECONDS", "180")),
            permission_launch_wait_seconds=float(_env("NOTES_SERVICE_PERMISSION_LAUNCH_WAIT_SECONDS", "20")),
            security_bin=_env("NOTES_SERVICE_SECURITY_BIN", "/usr/bin/security"),
            keychain=_env("NOTES_SERVICE_KEYCHAIN", ""),
            keychain_service=_env("NOTES_SERVICE_KEYCHAIN_SERVICE", "notes-exporter"),
            generated_password_bytes=int(_env("NOTES_SERVICE_GENERATED_PASSWORD_BYTES", "24")),
            cli_session_minutes=float(_env("NOTES_SERVICE_CLI_SESSION_MINUTES", "10")),
            exporter=Path(_env("NOTES_SERVICE_EXPORTER", str(REPO_DIR / "exportnotes.zsh"))).expanduser(),
            python=_env("NOTES_SERVICE_PYTHON", sys.executable),
            exporter_path=_env("NOTES_SERVICE_EXPORTER_PATH", DEFAULT_EXPORTER_PATH),
            pass_env=[n.strip() for n in e.get("NOTES_SERVICE_PASS_ENV", "").split(",") if n.strip()],
            file_chunk_bytes=int(_env("NOTES_SERVICE_FILE_CHUNK_BYTES", str(256 * 1024))),
            runs_keep=int(_env("NOTES_SERVICE_RUNS_KEEP", "200")),
            progress_write_seconds=float(_env("NOTES_SERVICE_PROGRESS_WRITE_SECONDS", "1")),
            key_touch_seconds=float(_env("NOTES_SERVICE_KEY_TOUCH_SECONDS", "60")),
            docs=_bool("NOTES_SERVICE_DOCS", False),
        )
        known = {f.name for f in fields(cls)}
        return replace(cfg, **{k: v for k, v in overrides.items() if k in known and v is not None})

    # ---- paths in the state directory ----
    @property
    def settings_file(self) -> Path:
        return self.home / "service.json"

    @property
    def auth_db(self) -> Path:
        return self.home / "auth.sqlite"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def runs_db(self) -> Path:
        return self.runs_dir / "runs.sqlite"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    def ensure_home(self) -> None:
        for d in (self.home, self.runs_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass

    def is_loopback_bind(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    def local_url(self) -> str:
        """Where a command on this Mac reaches the service (loopback even for a wildcard bind)."""
        host = self.host
        if host in ("0.0.0.0", "", "localhost"):
            host = "127.0.0.1"
        elif host == "::":
            host = "::1"
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{self.port}"
