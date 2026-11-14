"""Writing notes back to Apple Notes (SERVICE-API.md "Writing notes").

The only part of the service that changes Notes, so it is fenced in:

* off until an admin turns on ``allow_writes`` (a ``settings`` key can't: it is read-only
  to it), and every request needs the ``write`` scope;
* never while an export runs, and one write at a time;
* an update names the note's ``modified`` the client edited from: when the export has moved
  on since (``reason: export``), or Notes itself has a newer change than the export
  (``reason: notes``, asked of Notes just before writing), it is a 409 unless ``force``;
* writing replaces a note's whole body, so a note with attachments that aren't pictures,
  or a checklist, is refused (``reason: losses``) unless the client says ``accept_losses``
  after showing what goes; a locked or deleted note is never written;
* a new note goes only into a folder the export knows.

The work is done by ``notes_write_helper.py`` (pandoc + osascript) in a subprocess with the
exporter's clean environment. Each write is appended to ``writes.ndjson`` in the state
directory — who, what, which note, the outcome; never the note's text."""

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config
from .settings import exporter_env


class WriteRefused(Exception):
    """A write that must not happen: ``status`` is the HTTP answer, ``info`` extra fields."""

    def __init__(self, status: int, message: str, **info):
        super().__init__(message)
        self.status = status
        self.info = info


def _instant(value: Optional[str]):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def same_time(a: Optional[str], b: Optional[str]) -> bool:
    """Two timestamps name the same second (offsets and formats aside)."""
    ta, tb = _instant(a), _instant(b)
    if ta is None or tb is None:
        return (a or "") == (b or "")
    return ta == tb


def losses(entry: dict) -> List[str]:
    """What rewriting this note's body would lose, in words (empty: nothing)."""
    out = []
    others = [a for a in entry.get("attachments") or [] if (a.get("kind") or "") != "image"]
    if others:
        names = ", ".join(sorted({a.get("name") or "?" for a in others})[:5])
        out.append(f"{len(others)} attachment{'s' if len(others) != 1 else ''} that "
                   f"{'aren’t pictures' if len(others) != 1 else 'isn’t a picture'} ({names})")
    if entry.get("checklist"):
        out.append("its checklist (ticks become a plain list)")
    return out


class WriteManager:
    def __init__(self, config: Config, *, load_settings: Callable, note_entry: Callable,
                 known_folder: Callable, export_root: Callable, running_run_id: Callable, start_run: Callable):
        self.config = config
        self._load_settings = load_settings
        self._note_entry = note_entry          # note id -> manifest entry (or None)
        self._known_folder = known_folder      # (account, [folders]) -> bool
        self._export_root = export_root
        self._running = running_run_id
        self._start_run = start_run            # (account, [folders], formats) -> run | None
        self._lock = threading.Lock()

    # ---- the fences ----
    def state(self) -> dict:
        settings = self._load_settings()
        return {"allowed": bool(getattr(settings, "allow_writes", False)), "busy": self._lock.locked(),
                "running_run_id": self._running()}

    def _guard(self) -> None:
        if not getattr(self._load_settings(), "allow_writes", False):
            raise WriteRefused(403, "writing to Apple Notes is off — an admin turns it on in the service's "
                                    "Settings (Allow clients to write notes)", reason="off")
        running = self._running()
        if running:
            raise WriteRefused(409, "an export is running; write when it has finished", reason="running",
                               running_run_id=running)

    def _helper(self, request: dict) -> dict:
        try:
            r = subprocess.run([self.config.python, str(self.config.writer_helper)], input=json.dumps(request),
                               capture_output=True, text=True, timeout=self.config.write_timeout_seconds,
                               env=exporter_env(self.config), stdin=None)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Notes didn't answer in time", "code": "timeout"}
        except OSError as e:
            return {"ok": False, "error": f"couldn't run the writer: {e.__class__.__name__}", "code": "failed"}
        try:
            out = json.loads((r.stdout or "").strip() or "{}")
        except ValueError:
            out = {}
        if not isinstance(out, dict) or "ok" not in out:
            return {"ok": False, "error": (r.stderr or "the writer gave no answer").strip()[:300], "code": "failed"}
        return out

    def _log(self, **fields) -> None:
        path: Path = self.config.home / "writes.ndjson"
        fields = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(fields) + "\n")
        except OSError:
            pass

    def _base_dir(self, entry: Optional[dict]) -> str:
        root = Path(self._export_root())
        md = ((entry or {}).get("outputs") or {}).get("md") or {}
        if md.get("path"):
            return str((root / md["path"]).parent)
        return str(root)

    def _after(self, account: str, folders: List[str], formats: Optional[List[str]], export: bool):
        if not export:
            return None
        try:
            return self._start_run(account, folders, formats)
        except Exception:  # noqa: BLE001 - the write happened; the next export picks it up
            return None

    def _failed(self, out: dict) -> WriteRefused:
        code = out.get("code") or "failed"
        status = {"permission": 503, "not_found": 404, "bad_request": 400, "platform": 501,
                  "pandoc": 500, "timeout": 504}.get(code, 502)
        message = out.get("error") or "Notes refused the change"
        if code == "permission":
            message = ("the service isn't allowed to control Notes: allow it in System Settings → Privacy & "
                       "Security → Automation (" + message + ")")
        return WriteRefused(status, message, reason=code)

    # ---- the writes ----
    def update(self, note_id: str, *, markdown: str, base_modified: Optional[str], title: str = "",
               force: bool = False, accept_losses: bool = False, by: str = "",
               export: bool = True, formats: Optional[List[str]] = None) -> dict:
        self._guard()
        entry = self._note_entry(note_id)
        if not entry:
            raise WriteRefused(404, "no such note in the export", reason="not_found")
        if entry.get("deleted"):
            raise WriteRefused(409, "that note was deleted in Notes", reason="deleted")
        if entry.get("locked"):
            raise WriteRefused(409, "that note is locked; Notes doesn't let a script change it", reason="locked")
        lost = losses(entry)
        if lost and not accept_losses:
            raise WriteRefused(409, "writing this note would lose " + "; ".join(lost), reason="losses", losses=lost)
        if not force and base_modified is not None and not same_time(base_modified, entry.get("modified")):
            raise WriteRefused(409, "the note changed since you opened it (a newer export has it)", reason="export",
                               modified=entry.get("modified"))
        if not self._lock.acquire(blocking=False):
            raise WriteRefused(409, "another write is in progress", reason="busy")
        try:
            if not force:
                live = self._helper({"operation": "modified", "note_id": note_id})
                if not live.get("ok"):
                    raise self._failed(live)
                if not same_time(live.get("modified"), entry.get("modified")):
                    raise WriteRefused(409, "the note was changed in Notes after the last export — export, then "
                                            "edit the new version", reason="notes", notes_modified=live.get("modified"),
                                       modified=entry.get("modified"))
            out = self._helper({"operation": "update", "note_id": note_id, "title": title, "markdown": markdown,
                                "base_dir": self._base_dir(entry), "root": str(self._export_root())})
            self._log(by=by, operation="update", note_id=note_id, ok=bool(out.get("ok")), force=force,
                      accept_losses=accept_losses, error=None if out.get("ok") else out.get("error"))
            if not out.get("ok"):
                raise self._failed(out)
        finally:
            self._lock.release()
        run = self._after(entry.get("account") or "", list(entry.get("folder_path") or []), formats, export)
        return {"note_id": out.get("note_id") or note_id, "modified": out.get("modified"), "run": run}

    def create(self, *, account: str, folder_path: List[str], markdown: str, title: str = "", by: str = "",
               export: bool = True, formats: Optional[List[str]] = None) -> dict:
        self._guard()
        folders = [str(f).strip() for f in folder_path or [] if str(f).strip()]
        account = (account or "").strip()
        if not account or not folders:
            raise WriteRefused(400, "a new note needs an account and a folder", reason="bad_request")
        if not self._known_folder(account, folders):
            raise WriteRefused(404, "the export has no such folder — new notes go into folders it already holds",
                               reason="not_found")
        if not (markdown or "").strip():
            raise WriteRefused(400, "a new note needs some text", reason="bad_request")
        if not self._lock.acquire(blocking=False):
            raise WriteRefused(409, "another write is in progress", reason="busy")
        try:
            out = self._helper({"operation": "create", "account": account, "folder_path": folders, "title": title,
                                "markdown": markdown, "base_dir": str(self._export_root()),
                                "root": str(self._export_root())})
            self._log(by=by, operation="create", note_id=out.get("note_id"), ok=bool(out.get("ok")),
                      error=None if out.get("ok") else out.get("error"))
            if not out.get("ok"):
                raise self._failed(out)
        finally:
            self._lock.release()
        run = self._after(account, folders, formats, export)
        return {"note_id": out.get("note_id"), "modified": out.get("modified"), "run": run}
