"""Updating the service from a client (SERVICE-API.md "Updates").

The service runs from a git checkout of notes-exporter. A client (FunHoard, the web page)
can ask which version is running, which is installed on disk, and the newest release — the
highest ``vX.Y.Z`` tag on the checkout's ``origin`` — and an admin can move the checkout to
a release and restart the service.

Fenced in:

* an update only ever fast-forwards to a release tag: never with uncommitted changes in
  tracked files, never when the branch holds commits the remote doesn't, never when the tag
  isn't ahead of what is checked out, never while an export runs, one at a time, and not at
  all when ``NOTES_SERVICE_ALLOW_UPDATE`` is false;
* after the merge (and ``pip install -r requirements.txt`` when that file changed) a
  self-check imports the service and asks the command line for its version in a fresh
  process; any failure puts the checkout back where it was (``git reset --hard``) and the
  requirements with it, so a bad release never stays installed;
* a restart only exits the process when launchd will start it again (the LaunchAgent has
  ``KeepAlive``), and not while an export runs unless forced.

Every git / pip / Python call goes through ``runner`` (``args, cwd, timeout`` →
``CompletedProcess``-like), so tests replace it. Each update is appended to
``updates.ndjson`` in the state directory: who, from, to and the result.
"""

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import __version__
from .config import REPO_DIR, Config

TAG_RE = re.compile(r"^refs/tags/v(\d+)\.(\d+)\.(\d+)(\^\{\})?$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class UpdateRefused(Exception):
    def __init__(self, status: int, message: str, **info):
        super().__init__(message)
        self.status = status
        self.info = info


def _semver(v: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not v or not VERSION_RE.match(v.strip()):
        return None
    a, b, c = v.strip().split(".")
    return int(a), int(b), int(c)


def newer(a: Optional[str], b: Optional[str]) -> bool:
    """``a`` is a later version than ``b`` (an unreadable one is never later)."""
    sa, sb = _semver(a), _semver(b)
    return bool(sa and (sb is None or sa > sb))


def parse_tags(ls_remote: str) -> dict:
    """``{version: commit}`` from ``git ls-remote --tags`` output (annotated tags peeled)."""
    plain, peeled = {}, {}
    for line in (ls_remote or "").splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        m = TAG_RE.match(ref)
        if not m:
            continue
        version = ".".join(m.group(i) for i in (1, 2, 3))
        (peeled if m.group(4) else plain)[version] = sha
    return {**plain, **peeled}


def latest_of(tags: dict) -> Optional[str]:
    best = None
    for v in tags:
        if best is None or _semver(v) > _semver(best):
            best = v
    return best


def default_runner(args: List[str], cwd: Path, timeout: float):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def under_launchd() -> bool:
    """Started by launchd (so an exit is followed by a fresh start under KeepAlive)."""
    xpc = os.environ.get("XPC_SERVICE_NAME", "")
    return os.getppid() == 1 or (xpc not in ("", "0") and not xpc.startswith("application."))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class UpdateManager:
    def __init__(self, config: Config, *, running_run_id: Callable[[], Optional[str]],
                 repo_dir: Path = REPO_DIR, loaded_version: str = __version__,
                 runner: Callable = default_runner, exit_process: Optional[Callable[[], None]] = None,
                 is_under_launchd: Callable[[], bool] = under_launchd, clock: Callable[[], float] = time.time):
        self.config = config
        self.repo_dir = Path(repo_dir)
        self.loaded_version = loaded_version
        self.runner = runner
        self.exit_process = exit_process or (lambda: os.kill(os.getpid(), signal.SIGTERM))
        self.is_under_launchd = is_under_launchd
        self.clock = clock
        self._running_run_id = running_run_id
        self._lock = threading.Lock()
        self._check_lock = threading.Lock()
        self._latest: Optional[str] = None
        self._tags: dict = {}
        self._checked_at: Optional[float] = None
        self._check_error: Optional[str] = None
        self.updating = False
        self.restarting = False

    # ---- small helpers ----
    def _git(self, *args: str, timeout: Optional[float] = None):
        return self.runner(["git", *args], self.repo_dir, timeout or self.config.update_git_timeout_seconds)

    def _python(self) -> str:
        if self.config.update_python:
            return self.config.update_python
        venv = self.repo_dir / ".venv" / "bin" / "python"
        return str(venv) if venv.exists() else sys.executable

    def installed(self) -> Optional[str]:
        try:
            return (self.repo_dir / "VERSION").read_text().strip() or None
        except OSError:
            return None

    def _requirements_hash(self) -> Optional[str]:
        try:
            return hashlib.sha256((self.repo_dir / "requirements.txt").read_bytes()).hexdigest()
        except OSError:
            return None

    def _log(self, entry: dict) -> None:
        try:
            self.config.ensure_home()
            with open(self.config.home / "updates.ndjson", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": _now(), **entry}) + "\n")
        except OSError:
            pass

    # ---- the newest release ----
    def check(self, refresh: bool = False) -> None:
        with self._check_lock:
            now = self.clock()
            age = None if self._checked_at is None else now - self._checked_at
            if age is not None:
                if not refresh and age < self.config.update_check_hours * 3600:
                    return
                if refresh and age < self.config.update_check_min_seconds:
                    return
            self._checked_at = now
            try:
                r = self._git("ls-remote", "--tags", "origin")
            except (OSError, subprocess.SubprocessError) as exc:
                self._check_error = f"couldn't ask the remote: {exc}"
                self._latest = None
                return
            if r.returncode != 0:
                self._check_error = (r.stderr or r.stdout or "git ls-remote failed").strip().splitlines()[-1][:300]
                self._latest = None
                return
            self._tags = parse_tags(r.stdout)
            self._latest = latest_of(self._tags)
            self._check_error = None if self._latest else "the remote has no release tags"

    # ---- may it update? ----
    def _blocker(self) -> Optional[str]:
        """Why no update can be made now, or None (the remote's tag is judged separately)."""
        if not self.config.allow_update:
            return "Updates from clients are turned off on this Mac (NOTES_SERVICE_ALLOW_UPDATE)."
        if self.updating:
            return "An update is already being made."
        if self._running_run_id():
            return "An export is running; update when it has finished."
        try:
            inside = self._git("rev-parse", "--is-inside-work-tree")
        except (OSError, subprocess.SubprocessError):
            inside = None
        if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
            return "The service isn't running from a git checkout, so it can't update itself."
        dirty = self._git("status", "--porcelain", "--untracked-files=no")
        if dirty.returncode != 0 or dirty.stdout.strip():
            return "The checkout has uncommitted changes; commit or discard them first."
        ahead = self._git("rev-list", "--count", "@{u}..HEAD")
        if ahead.returncode != 0:
            return "The checkout's branch doesn't track a remote branch."
        if ahead.stdout.strip() not in ("", "0"):
            return "The checkout has commits the remote doesn't; push them first."
        return None

    def _fast_forward_problem(self, version: str) -> Optional[str]:
        """None when HEAD can fast-forward to the tag's commit (or that can't be told before
        fetching: the commit isn't here yet), else why not."""
        commit = self._tags.get(version)
        if not commit:
            return None
        r = self._git("merge-base", "--is-ancestor", "HEAD", commit)
        if r.returncode == 1:
            return f"Version {version} isn't ahead of what is checked out, so it can't be fast-forwarded to."
        return None

    def view(self, refresh: bool = False) -> dict:
        self.check(refresh=refresh)
        installed = self.installed()
        latest = self._latest
        available = newer(latest, installed)
        why_not = self._blocker()
        if why_not is None:
            if latest is None:
                why_not = "The newest release isn't known: " + (self._check_error or "not checked yet")
            elif not available:
                why_not = "This is the newest release."
            else:
                why_not = self._fast_forward_problem(latest)
        out = {
            "version": self.loaded_version,
            "installed": installed,
            "restart_needed": bool(installed and installed != self.loaded_version),
            "latest": latest,
            "latest_checked_at": (datetime.fromtimestamp(self._checked_at, timezone.utc).replace(microsecond=0)
                                  .isoformat() if self._checked_at else None),
            "update_available": available,
            "can_update": why_not is None,
            "why_not": why_not,
            "updating": self.updating,
            "can_restart": self.is_under_launchd(),
        }
        if self._check_error:
            out["check_error"] = self._check_error
        return out

    # ---- update ----
    def update(self, to: Optional[str] = None, *, who: str = "") -> dict:
        if to is not None and not VERSION_RE.match(str(to).strip()):
            raise UpdateRefused(400, "to must be a version like 1.6.0")
        if not self._lock.acquire(blocking=False):
            raise UpdateRefused(409, "An update is already being made.")
        try:
            blocker = self._blocker()
            if blocker:
                raise UpdateRefused(409, blocker)
            self.updating = True
            self.check(refresh=True)
            target = (to or "").strip() or self._latest
            installed = self.installed()
            if not target:
                raise UpdateRefused(409, "The newest release isn't known: " + (self._check_error or "no release tags"))
            if not newer(target, installed):
                raise UpdateRefused(409, f"Version {target} isn't newer than the installed {installed}.")
            if self._tags and target not in self._tags:
                raise UpdateRefused(404, f"There is no release {target}.")
            problem = self._fast_forward_problem(target)
            if problem:
                raise UpdateRefused(409, problem)
            return self._apply(target, installed, who)
        finally:
            self.updating = False
            self._lock.release()

    def _apply(self, target: str, installed: Optional[str], who: str) -> dict:
        head = self._git("rev-parse", "HEAD")
        if head.returncode != 0:
            raise UpdateRefused(409, "Couldn't read the checkout's current commit.")
        previous = head.stdout.strip()
        req_before = self._requirements_hash()
        tag = f"v{target}"
        fetched = self._git("fetch", "--tags", "origin", timeout=self.config.update_timeout_seconds)
        if fetched.returncode != 0:
            msg = "Couldn't fetch the release: " + (fetched.stderr or fetched.stdout or "").strip()[-300:]
            self._log({"who": who, "from": installed, "to": target, "result": "fetch_failed"})
            raise UpdateRefused(502, msg)
        if self._git("rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}").returncode != 0:
            raise UpdateRefused(404, f"There is no release {target}.")
        if self._git("merge-base", "--is-ancestor", "HEAD", tag).returncode != 0:
            raise UpdateRefused(409, f"Version {target} isn't ahead of what is checked out, so it can't be "
                                     "fast-forwarded to.")
        merged = self._git("merge", "--ff-only", tag)
        if merged.returncode != 0:
            self._git("reset", "--hard", previous)
            reason = "the merge failed: " + (merged.stderr or merged.stdout or "").strip()[-300:]
            return self._failed(installed, target, who, reason, requirements_changed=False)
        requirements_changed = self._requirements_hash() != req_before
        if requirements_changed:
            pip = self._pip()
            if pip:
                return self._rollback(previous, installed, target, who, pip, requirements_changed)
        problem = self._self_check(target)
        if problem:
            return self._rollback(previous, installed, target, who, problem, requirements_changed)
        self._log({"who": who, "from": installed, "to": target, "result": "ok",
                   "requirements_changed": requirements_changed})
        return {"ok": True, "from": installed, "to": target, "restart_needed": True,
                "requirements_changed": requirements_changed}

    def _pip(self) -> Optional[str]:
        """None when ``pip install -r requirements.txt`` worked, else why not."""
        try:
            r = self.runner([self._python(), "-m", "pip", "install", "-r", "requirements.txt"],
                            self.repo_dir, self.config.update_timeout_seconds)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"installing its requirements failed: {exc}"
        if r.returncode != 0:
            return "installing its requirements failed: " + (r.stderr or r.stdout or "").strip()[-300:]
        return None

    def _self_check(self, target: str) -> Optional[str]:
        python = self._python()
        timeout = self.config.update_timeout_seconds
        try:
            imp = self.runner([python, "-c", "import notes_service.app"], self.repo_dir, timeout)
            if imp.returncode != 0:
                return "the new version doesn't load: " + (imp.stderr or imp.stdout or "").strip()[-300:]
            ver = self.runner([python, "-m", "notes_service", "--version"], self.repo_dir, timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"the self-check failed: {exc}"
        if ver.returncode != 0:
            return "the new version's command line fails: " + (ver.stderr or ver.stdout or "").strip()[-300:]
        said = (ver.stdout or "").strip().split()[-1:] or [""]
        if said[0] != target:
            return f"the new version reports itself as {said[0] or 'nothing'}, not {target}"
        return None

    def _rollback(self, previous: str, installed, target, who, reason: str, requirements_changed: bool) -> dict:
        self._git("reset", "--hard", previous)
        if requirements_changed:
            self._pip()
        return self._failed(installed, target, who, reason, requirements_changed)

    def _failed(self, installed, target, who, reason: str, requirements_changed: bool) -> dict:
        self._log({"who": who, "from": installed, "to": target, "result": "rolled_back", "reason": reason})
        return {"ok": False, "from": installed, "to": target, "rolled_back": True, "reason": reason,
                "restart_needed": False, "requirements_changed": requirements_changed}

    # ---- restart ----
    def restart(self, *, force: bool = False, who: str = "") -> dict:
        if not self.is_under_launchd():
            raise UpdateRefused(409, "The service isn't running under launchd, so it wouldn't start again; "
                                     "restart it yourself.")
        if self._running_run_id() and not force:
            raise UpdateRefused(409, "An export is running; restarting would stop it (send force to do it anyway).")
        if self.updating:
            raise UpdateRefused(409, "An update is being made; restart when it has finished.")
        self.restarting = True
        self._log({"who": who, "result": "restart", "version": self.loaded_version, "installed": self.installed()})
        timer = threading.Timer(self.config.restart_delay_seconds, self.exit_process)
        timer.daemon = True
        timer.start()
        return {"restarting": True}
