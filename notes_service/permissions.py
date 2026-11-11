"""macOS permissions the exporter needs, checked without ever prompting.

* automation: ``notes_permission.py`` (AEDeterminePermissionToAutomateTarget
  with askUserIfNeeded=false), run as a subprocess of the service so the
  answer is for the same responsible process the exporter will run as.
* full_disk_access (only needed for ``--tags``): opening the TCC database
  read-only succeeds only with Full Disk Access; nothing is read from it, and
  a refusal is a plain EPERM, never a prompt.

Results are cached for ``permission_cache_seconds``.

``request()`` is the one call that may prompt: it runs the helper with
``--ask`` so macOS shows its "wants to control Notes" dialog on the Mac. The
grant belongs to the process that asks, which is why the service asks itself
rather than leaving it to a terminal. One request at a time.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import Config

class PermissionRequestBusy(RuntimeError):
    """Another permission request is already waiting for an answer."""


def _run_helper(config: Config, args, timeout: float) -> str:
    try:
        r = subprocess.run([config.python, str(config.permission_helper), *args], capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unknown({e.__class__.__name__})"
    word = (r.stdout or "").strip().split("\n")[-1].strip() if r.stdout else ""
    return word or f"unknown(exit {r.returncode})"


def automation_state(config: Config) -> str:
    return _run_helper(config, [], config.permission_timeout_seconds)


def request_automation(config: Config) -> str:
    """Ask macOS (the dialog appears on the Mac); waits for the answer or the timeout."""
    return _run_helper(config, ["--ask", "--wait", str(config.permission_launch_wait_seconds)],
                       config.permission_request_timeout_seconds)


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
                 disk: Callable[[], Optional[bool]] = None, requester: Callable[[], str] = None):
        self.config = config
        self._automation = automation or (lambda: automation_state(config))
        self._requester = requester or (lambda: request_automation(config))
        self._request_lock = threading.Lock()
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

    @property
    def requesting(self) -> bool:
        return self._request_lock.locked()

    def request(self) -> dict:
        """Ask macOS for automation of Notes, then check again. Raises PermissionRequestBusy."""
        if not self._request_lock.acquire(blocking=False):
            raise PermissionRequestBusy("a permission request is already waiting for an answer on the Mac")
        try:
            asked = self._requester()
            result = self.get(refresh=True) if self.config.permission_check else \
                {"automation": asked, "full_disk_access": self._disk(),
                 "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            return dict(result, asked=asked)
        finally:
            self._request_lock.release()

    def note_run_state(self, state: Optional[str]) -> None:
        """A run's own permission event is fresher than the cache."""
        if not state:
            return
        with self._lock:
            if self._cached:
                self._cached = dict(self._cached, automation=state)
