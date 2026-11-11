"""macOS permissions the exporter needs, checked without ever prompting.

* automation: ``notes_permission.py`` (AEDeterminePermissionToAutomateTarget
  with askUserIfNeeded=false), run as a subprocess of the service so the
  answer is for the same responsible process the exporter will run as.
* full_disk_access (only needed for ``--tags``): opening the TCC database
  read-only succeeds only with Full Disk Access; nothing is read from it, and
  a refusal is a plain EPERM, never a prompt.

Results are cached for ``permission_cache_seconds``.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import REPO_DIR, Config

def automation_state(config: Config) -> str:
    try:
        r = subprocess.run([config.python, str(REPO_DIR / "notes_permission.py")], capture_output=True,
                           text=True, timeout=config.permission_timeout_seconds, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unknown({e.__class__.__name__})"
    word = (r.stdout or "").strip().split("\n")[-1].strip() if r.stdout else ""
    return word or f"unknown(exit {r.returncode})"


def full_disk_access(path: Path = None) -> Optional[bool]:
    path = path or (Path(os.path.expanduser("~")) / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db")
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except PermissionError:
        return False
    except FileNotFoundError:
        return None
    except OSError:
        return None
    os.close(fd)
    return True


class PermissionChecker:
    def __init__(self, config: Config, automation: Callable[[], str] = None,
                 disk: Callable[[], Optional[bool]] = None):
        self.config = config
        self._automation = automation or (lambda: automation_state(config))
        self._disk = disk or full_disk_access
        self._lock = threading.Lock()
        self._cached = None
        self._at = 0.0

    def get(self, refresh: bool = False) -> dict:
        if not self.config.permission_check:
            return {"automation": "unchecked", "full_disk_access": None, "checked_at": None}
        with self._lock:
            if not refresh and self._cached and time.monotonic() - self._at < self.config.permission_cache_seconds:
                return self._cached
        result = {"automation": self._automation(), "full_disk_access": self._disk(),
                  "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with self._lock:
            self._cached, self._at = result, time.monotonic()
        return result

    def note_run_state(self, state: Optional[str]) -> None:
        """A run's own permission event is fresher than the cache."""
        if not state:
            return
        with self._lock:
            if self._cached:
                self._cached = dict(self._cached, automation=state)
