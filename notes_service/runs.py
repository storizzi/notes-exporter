"""Runs: one export at a time, recorded in runs/runs.sqlite.

A run spawns ``exportnotes.zsh --json-log runs/<id>.ndjson --non-interactive``
in its own process group with a clean environment. A watcher thread follows
the event file for progress and the result; cancel signals the whole group.
"""

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config
from .db import Database
from .settings import (SettingsStore, _clean_names, effective_epub_books, exporter_args, exporter_env,
                       produced_formats)

STATUSES = ("queued", "running", "ok", "partial", "failed", "cancelled")
FINISHED = ("ok", "partial", "failed", "cancelled")
TRIGGERS = ("schedule", "api", "ui", "cli")
MODES = ("incremental", "full")

EXIT_MESSAGES = {
    1: "the exporter could not start (bad option, Python or dependencies); see the run log",
    3: "Notes automation is not allowed for the service yet, or macOS would ask: "
       "run one supervised export and click Allow (see SERVICE-API.md)",
    4: "another export holds the lock on the export folder",
    5: "the export failed (an AppleScript error stopped it)",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL,
    mode TEXT NOT NULL,
    folders TEXT NOT NULL DEFAULT '[]',
    accounts TEXT NOT NULL DEFAULT '[]',
    formats TEXT NOT NULL DEFAULT '[]',
    epub_books TEXT NOT NULL DEFAULT 'none',
    requested_by TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    counts TEXT NOT NULL DEFAULT '{}',
    progress TEXT NOT NULL DEFAULT '{}',
    message TEXT,
    exporter_run_id TEXT,
    manifest_sequence INTEGER,
    permission TEXT,
    pid INTEGER
);
CREATE INDEX IF NOT EXISTS runs_seq ON runs(seq);
"""


class RunBusy(Exception):
    def __init__(self, running_run_id: str):
        super().__init__("a run is already in progress")
        self.running_run_id = running_run_id


class RunError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status_for_exit(code: Optional[int]) -> str:
    if code == 0:
        return "ok"
    if code == 2:
        return "partial"
    return "failed"


def apply_event(state: dict, event: dict) -> dict:
    """Fold one --json-log event into a run's live state (INTEGRATION.md events)."""
    t = event.get("type")
    if t == "start":
        state["exporter_run_id"] = event.get("run_id")
        if isinstance(event.get("formats"), list):
            state["formats"] = event["formats"]
    elif t == "permission":
        state["permission"] = event.get("state")
    elif t == "progress":
        state["progress"] = {k: event[k] for k in ("stage", "done", "total", "unit", "account", "folder",
                                                   "notes_exported", "failed") if k in event}
    elif t == "stage":
        prog = dict(state.get("progress") or {})
        prog["stage"] = event.get("stage")
        prog["stage_status"] = event.get("status")
        state["progress"] = prog
    elif t == "manifest":
        state["counts"] = {k: event[k] for k in ("notes", "changed", "deleted", "deleted_this_run", "skipped")
                           if k in event}
    elif t == "message" and event.get("level") == "error":
        state["last_error"] = event.get("message")
    elif t == "result":
        state["result"] = {k: event.get(k) for k in ("status", "exit_code", "message", "elapsed_seconds")}
    return state


def read_events(path: Path, after: int = 0) -> List[str]:
    """Lines of an event file after the first ``after`` lines (complete lines only)."""
    if not path.exists():
        return []
    with open(path, "rb") as f:
        data = f.read()
    lines = data.split(b"\n")
    complete = lines[:-1]  # the last element is "" or a partial line still being written
    return [l.decode("utf-8", "replace") for l in complete[after:] if l.strip()]


class RunStore:
    def __init__(self, config: Config):
        self.config = config
        config.ensure_home()
        self.db = Database(config.runs_db, SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after a runs.sqlite was first made."""
        have = {r["name"] for r in self.db.all("PRAGMA table_info(runs)")}
        for name, ddl in (("epub_books", "TEXT NOT NULL DEFAULT 'none'"),):
            if name not in have:
                self.db.run(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")

    @staticmethod
    def to_public(row: dict) -> dict:
        if not row:
            return row
        out = dict(row)
        for k in ("folders", "accounts", "formats"):
            out[k] = json.loads(out[k] or "[]")
        for k in ("counts", "progress"):
            out[k] = json.loads(out[k] or "{}")
        out.pop("seq", None)
        out.pop("pid", None)
        return out

    def create(self, *, trigger: str, mode: str, folders, accounts, formats, requested_by,
               epub_books: str = "none") -> dict:
        with self.db.connect() as conn:
            seq = (conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM runs").fetchone()[0])
            run_id = uuid.uuid4().hex
            conn.execute("INSERT INTO runs(id, seq, status, trigger, mode, folders, accounts, formats, epub_books,"
                         " requested_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (run_id, seq, "queued", trigger, mode, json.dumps(folders or []),
                          json.dumps(accounts or []), json.dumps(formats or []), epub_books, requested_by, now_iso()))
        return self.get(run_id)

    def update(self, run_id: str, **fields) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            if k in ("counts", "progress", "folders", "accounts", "formats"):
                v = json.dumps(v or ({} if k in ("counts", "progress") else []))
            cols.append(f"{k}=?")
            vals.append(v)
        self.db.run(f"UPDATE runs SET {', '.join(cols)} WHERE id=?", (*vals, run_id))

    def get(self, run_id: str) -> Optional[dict]:
        return self.to_public(self.db.one("SELECT * FROM runs WHERE id=?", (run_id,)))

    def list(self, limit: int = 50, offset: int = 0):
        rows = self.db.all("SELECT * FROM runs ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset))
        total = self.db.one("SELECT COUNT(*) AS n FROM runs")["n"]
        return [self.to_public(r) for r in rows], total

    def latest(self, finished_only: bool = False) -> Optional[dict]:
        where = f"WHERE status IN ({','.join('?' * len(FINISHED))})" if finished_only else ""
        row = self.db.one(f"SELECT * FROM runs {where} ORDER BY seq DESC LIMIT 1",
                          FINISHED if finished_only else ())
        return self.to_public(row)

    def active(self) -> Optional[dict]:
        return self.to_public(self.db.one("SELECT * FROM runs WHERE status IN ('queued','running') "
                                          "ORDER BY seq DESC LIMIT 1"))

    def events_path(self, run_id: str) -> Path:
        return self.config.runs_dir / f"{run_id}.ndjson"

    def log_path(self, run_id: str) -> Path:
        return self.config.runs_dir / f"{run_id}.log"

    def recover(self) -> int:
        """Runs left queued/running by a service that stopped are recorded as failed."""
        return self.db.run("UPDATE runs SET status='failed', finished_at=?, "
                           "message='interrupted: the service stopped during the run' "
                           "WHERE status IN ('queued','running')", (now_iso(),))

    def prune(self, keep: int) -> int:
        if keep <= 0:
            return 0
        old = self.db.all("SELECT id FROM runs WHERE status IN ('ok','partial','failed','cancelled') "
                          "ORDER BY seq DESC LIMIT -1 OFFSET ?", (keep,))
        for row in old:
            for p in (self.events_path(row["id"]), self.log_path(row["id"])):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
            self.db.run("DELETE FROM runs WHERE id=?", (row["id"],))
        return len(old)


class _Active:
    def __init__(self, run_id: str, proc: subprocess.Popen):
        self.run_id = run_id
        self.proc = proc
        self.cancel_requested = False
        self.thread: Optional[threading.Thread] = None


class RunManager:
    def __init__(self, config: Config, store: RunStore, settings: SettingsStore,
                 on_finish: Optional[Callable[[dict], None]] = None):
        self.config = config
        self.store = store
        self.settings = settings
        self.on_finish = on_finish
        self._lock = threading.Lock()
        self._active: Optional[_Active] = None

    @property
    def running_run_id(self) -> Optional[str]:
        a = self._active
        return a.run_id if a else None

    def start(self, *, trigger: str, mode: str = "incremental", folders=None, accounts=None,
              formats=None, epub_books: Optional[str] = None, requested_by: Optional[str] = None,
              epub_book_order: Optional[str] = None, epub_book_subfolders: Optional[str] = None) -> dict:
        if trigger not in TRIGGERS:
            raise RunError(f"trigger must be one of {list(TRIGGERS)}")
        if mode not in MODES:
            raise RunError(f"mode must be one of {list(MODES)}")
        try:
            folders = _clean_names(folders or [], "folder")
            accounts = _clean_names(accounts or [], "account")
        except ValueError as e:
            raise RunError(str(e))
        with self._lock:
            if self._active is not None:
                raise RunBusy(self._active.run_id)
            settings = self.settings.load()
            # A client's folder-book layout for this run, over the settings' (books are rebuilt
            # when their order changes, so a client should send the same values every run).
            overrides = {k: v for k, v in (("epub_book_order", epub_book_order),
                                           ("epub_book_subfolders", epub_book_subfolders)) if v}
            if overrides:
                settings = settings.model_copy(update=overrides)
            produced = produced_formats(settings.formats, formats)
            books = effective_epub_books(settings, epub_books)
            run = self.store.create(trigger=trigger, mode=mode, folders=folders, accounts=accounts,
                                    formats=produced, requested_by=requested_by, epub_books=books)
            events = self.store.events_path(run["id"])
            try:
                args = exporter_args(self.config, settings, json_log=events, mode=mode,
                                     folders=folders, accounts=accounts, formats=formats,
                                     epub_books=epub_books)
                Path(settings.export_root).mkdir(parents=True, exist_ok=True)
                events.touch()
                log = open(self.store.log_path(run["id"]), "ab")
                try:
                    proc = subprocess.Popen(["/bin/zsh", *args] if str(args[0]).endswith(".zsh") else args,
                                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            env=exporter_env(self.config), cwd=str(self.config.exporter.parent),
                                            start_new_session=True)
                finally:
                    log.close()
            except (OSError, ValueError) as e:
                self.store.update(run["id"], status="failed", finished_at=now_iso(),
                                  message=f"could not start the exporter: {e}")
                return self.store.get(run["id"])
            self.store.update(run["id"], status="running", started_at=now_iso(), pid=proc.pid)
            active = _Active(run["id"], proc)
            active.thread = threading.Thread(target=self._watch, args=(active,), daemon=True,
                                             name=f"run-{run['id'][:8]}")
            self._active = active
            active.thread.start()
            return self.store.get(run["id"])

    def _watch(self, active: _Active) -> None:
        events = self.store.events_path(active.run_id)
        state: dict = {}
        seen = 0
        last_write = 0.0

        def drain():
            nonlocal seen
            for line in read_events(events, seen):
                seen += 1
                try:
                    apply_event(state, json.loads(line))
                except (ValueError, TypeError):
                    continue

        def write_live():
            fields = {}
            for k in ("progress", "counts", "exporter_run_id", "permission", "formats"):
                if k in state:
                    fields[k] = state[k]
            self.store.update(active.run_id, **fields)

        try:
            while active.proc.poll() is None:
                time.sleep(0.2)
                before = seen
                drain()
                if seen != before and time.monotonic() - last_write >= self.config.progress_write_seconds:
                    write_live()
                    last_write = time.monotonic()
            # The file is written by the exporter's children too; read what's left.
            drain()
            code = active.proc.returncode
            result = state.get("result") or {}
            if active.cancel_requested:
                status, message = "cancelled", "cancelled"
            else:
                exit_code = code if code is not None and code >= 0 else None
                status = result.get("status") if exit_code is None and result.get("status") else status_for_exit(exit_code)
                if code is not None and code < 0:
                    status = "failed"
                message = result.get("message") or state.get("last_error") or EXIT_MESSAGES.get(code) \
                    or (f"the exporter was stopped by signal {-code}" if code is not None and code < 0 else None)
                if status in ("ok",):
                    message = result.get("message")
            write_live()
            fields = dict(status=status, exit_code=code, finished_at=now_iso(), message=message)
            self.store.update(active.run_id, **fields)
            manifest_seq = self._manifest_sequence()
            if manifest_seq is not None:
                self.store.update(active.run_id, manifest_sequence=manifest_seq)
        except Exception as e:  # never leave a run "running"
            self.store.update(active.run_id, status="failed", finished_at=now_iso(),
                              message=f"the service lost track of the run: {e}")
        finally:
            with self._lock:
                if self._active is active:
                    self._active = None
            try:
                self.store.prune(self.config.runs_keep)
            except Exception:
                pass
            if self.on_finish:
                try:
                    self.on_finish(self.store.get(active.run_id))
                except Exception:
                    pass

    def _manifest_sequence(self) -> Optional[int]:
        try:
            root = Path(self.settings.load().export_root)
            with open(root / "manifest.json", encoding="utf-8") as f:
                return int(json.load(f).get("run", {}).get("sequence"))
        except Exception:
            return None

    def cancel(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        if not run:
            raise KeyError(run_id)
        with self._lock:
            active = self._active
            if not active or active.run_id != run_id:
                return run  # already finished: nothing to do
            active.cancel_requested = True
        self._signal(active, signal.SIGTERM)
        threading.Thread(target=self._kill_later, args=(active,), daemon=True).start()
        return self.store.get(run_id)

    def _signal(self, active: _Active, sig) -> None:
        try:
            os.killpg(active.proc.pid, sig)  # start_new_session: pgid == pid
        except (ProcessLookupError, PermissionError):
            pass

    def _kill_later(self, active: _Active) -> None:
        try:
            active.proc.wait(timeout=self.config.cancel_grace_seconds)
        except subprocess.TimeoutExpired:
            self._signal(active, signal.SIGKILL)

    def wait(self, timeout: Optional[float] = None) -> bool:
        active = self._active
        if active and active.thread:
            active.thread.join(timeout)
            return not active.thread.is_alive()
        return True

    def shutdown(self) -> None:
        """Stop a run in progress when the service stops (it would otherwise run unsupervised)."""
        active = self._active
        if active:
            self.cancel(active.run_id)
            self.wait(self.config.cancel_grace_seconds + 5)
