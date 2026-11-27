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
* a new note goes only into a folder the export knows;
* an update first copies the note as it is into the backup folder (``write_backup_folder``,
  beneath it the note's folder path) and isn't made when that fails (``reason:
  backup_failed``); a client may skip it (``backup: "none"``) only while the admin's
  ``write_backup_required`` is off;
* a delete is Notes' own (Recently Deleted, recoverable for about 30 days), after the same
  conflict checks as an update, with a backup copy when asked;
* at most ``write_max_changes_per_hour`` / ``_per_day`` changes (``write_state.py`` keeps the
  count across restarts): beyond, **429** ``reason: write_limit`` with ``retry_after``;
* the approval list (``approvals.py``): a write tripping one of the ``write_hold_*`` rules —
  a burst from one client, many changes in a window, a big change to one note — is held
  (**202** ``held: true``) until someone with the ``approve`` scope approves it, which then
  makes it the normal way (backup, conflict checks against its base; the hold rules and the
  hard limits don't apply to an approved write).

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
from .approvals import MAX_PENDING, ApprovalStore
from .approvals import change_percent as _change_percent
from .approvals import line_count as _line_count
from .write_state import WriteState

BACKUP_CHOICES = ("folder", "none")
# What GET /api/version (and /api/health) advertise, so a client can tell these are here.
FEATURES = ("write", "write_backup", "delete", "write_limit", "approvals", "login_link")
# An approval that fails for one of these stays listed, marked stale: the note moved on.
STALE_REASONS = ("export", "notes", "deleted", "not_found", "locked", "losses")


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
                 known_folder: Callable, export_root: Callable, running_run_id: Callable, start_run: Callable,
                 state: Optional[WriteState] = None, local_now: Optional[Callable] = None,
                 note_text: Optional[Callable] = None, approvals: Optional[ApprovalStore] = None):
        self.config = config
        self.limits = state or WriteState(config)
        self.approvals = approvals or ApprovalStore(config)
        self._note_text = note_text or (lambda entry: None)   # manifest entry -> its text now (or None)
        self._local_now = local_now or (lambda: datetime.now().astimezone())
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
                "running_run_id": self._running(), **self.fences(settings)}

    def fences(self, settings=None) -> dict:
        """The backup settings and the mass-change counts (GET /api/writes, /api/status)."""
        settings = settings or self._load_settings()
        return {"backup": {"folder": settings.write_backup_folder, "required": settings.write_backup_required,
                           "exported": settings.write_backup_export},
                "limits": self.limits.counts(settings.write_max_changes_per_hour,
                                             settings.write_max_changes_per_day),
                "holds": {"batch_over": settings.write_hold_batch_over,
                          "batch_seconds": settings.write_hold_batch_seconds,
                          "count_over": settings.write_hold_count_over,
                          "window_hours": settings.write_hold_window_hours,
                          "changes_in_window": self.limits.changes_within(settings.write_hold_window_hours),
                          "change_percent": settings.write_hold_change_percent,
                          "min_lines": settings.write_hold_min_lines,
                          "max_age_days": settings.write_hold_max_age_days,
                          "held": self.approvals.count()}}

    def _guard(self) -> None:
        if not getattr(self._load_settings(), "allow_writes", False):
            raise WriteRefused(403, "writing to Apple Notes is off — an admin turns it on in the service's "
                                    "Settings (Allow clients to write notes)", reason="off")
        running = self._running()
        if running:
            raise WriteRefused(409, "an export is running; write when it has finished", reason="running",
                               running_run_id=running)

    def _check_limit(self, settings) -> None:
        over = self.limits.check(settings.write_max_changes_per_hour, settings.write_max_changes_per_day)
        if over:
            per = "an hour" if over["window"] == "hour" else "a day"
            raise WriteRefused(429, f"too many changes to Notes: at most {over['max']} {per} (the admin's limit "
                                    f"against mass changes); try again in {over['retry_after']} s",
                               reason="write_limit", retry_after=over["retry_after"], window=over["window"],
                               max=over["max"], count=over["count"])

    def _backup_choice(self, settings, backup: Optional[str], default: str) -> str:
        choice = (backup or default).strip().lower()
        if choice not in BACKUP_CHOICES:
            raise WriteRefused(400, f"backup must be one of {list(BACKUP_CHOICES)}", reason="bad_request")
        if choice == "none" and default == "folder" and settings.write_backup_required:
            raise WriteRefused(403, "the admin requires a backup before a note is changed (write_backup_required)",
                               reason="backup_required")
        return choice

    def _writable_entry(self, note_id: str) -> dict:
        entry = self._note_entry(note_id)
        if not entry:
            raise WriteRefused(404, "no such note in the export", reason="not_found")
        if entry.get("deleted"):
            raise WriteRefused(409, "that note was deleted in Notes", reason="deleted")
        if entry.get("locked"):
            raise WriteRefused(409, "that note is locked; Notes doesn't let a script change it", reason="locked")
        return entry

    def _check_export(self, entry: dict, base_modified: Optional[str], force: bool) -> None:
        if not force and base_modified is not None and not same_time(base_modified, entry.get("modified")):
            raise WriteRefused(409, "the note changed since you opened it (a newer export has it)", reason="export",
                               modified=entry.get("modified"))

    def _check_live(self, note_id: str, entry: dict) -> None:
        live = self._helper({"operation": "modified", "note_id": note_id})
        if not live.get("ok"):
            raise self._failed(live)
        if not same_time(live.get("modified"), entry.get("modified")):
            raise WriteRefused(409, "the note was changed in Notes after the last export — export, then "
                                    "edit the new version", reason="notes", notes_modified=live.get("modified"),
                               modified=entry.get("modified"))

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
                  "pandoc": 500, "timeout": 504, "locked": 409}.get(code, 502)
        message = out.get("error") or "Notes refused the change"
        if code == "permission":
            message = ("the service isn't allowed to control Notes: allow it in System Settings → Privacy & "
                       "Security → Automation (" + message + ")")
        return WriteRefused(status, message, reason=code)

    def _backup(self, note_id: str, entry: dict, settings, by: str) -> str:
        """Copy the note as it is into the backup folder; the copy's id, or WriteRefused (and the
        caller changes nothing)."""
        account = entry.get("account") or ""
        path = [str(p) for p in entry.get("folder_path") or [] if str(p)]
        when = self._local_now().strftime("%Y-%m-%d %H:%M")
        out = self._helper({"operation": "backup", "note_id": note_id, "account": account,
                            "backup_folder": settings.write_backup_folder, "folder_path": path,
                            "suffix": f" (before {when})"})
        self._log(by=by, operation="backup", note_id=note_id, backup_note_id=out.get("note_id"),
                  ok=bool(out.get("ok")), error=None if out.get("ok") else out.get("error"))
        if not out.get("ok"):
            failed = self._failed(out)
            if failed.info.get("reason") in ("permission", "timeout", "platform", "locked"):
                raise failed
            raise WriteRefused(502, "the note couldn't be backed up, so it wasn't changed: " + str(failed),
                               reason="backup_failed")
        self.limits.record_backup_folder(account, [settings.write_backup_folder, *path])
        return out.get("note_id")

    # ---- the approval list ----
    def _hold_rule(self, settings, *, client_label: str, before: Optional[str], after: Optional[str],
                   kind: str) -> Optional[dict]:
        """The first of the admin's rules this write trips (``{reason, …}``), or None."""
        s = settings
        if s.write_hold_batch_over:
            n = self.limits.requests_within(client_label, s.write_hold_batch_seconds)
            if n >= s.write_hold_batch_over:
                return {"reason": "batch", "detail": f"more than {s.write_hold_batch_over} writes from one client "
                                                     f"within {s.write_hold_batch_seconds} s",
                        "over": s.write_hold_batch_over, "seconds": s.write_hold_batch_seconds, "count": n + 1}
        if s.write_hold_count_over:
            n = self.limits.changes_within(s.write_hold_window_hours)
            if n >= s.write_hold_count_over:
                return {"reason": "count", "detail": f"more than {s.write_hold_count_over} changes within "
                                                     f"{s.write_hold_window_hours} h",
                        "over": s.write_hold_count_over, "hours": s.write_hold_window_hours, "count": n + 1}
        if s.write_hold_change_percent and kind in ("update", "delete") and before is not None:
            lines = _line_count(before)
            pct = 100.0 if kind == "delete" else _change_percent(before, after or "")
            if lines > s.write_hold_min_lines and pct > s.write_hold_change_percent:
                return {"reason": "big_change", "detail": f"{pct:g} % of a {lines}-line note changes (more than "
                                                          f"{s.write_hold_change_percent} %)",
                        "percent": pct, "lines": lines, "over_percent": s.write_hold_change_percent,
                        "min_lines": s.write_hold_min_lines}
        return None

    def _held(self, settings, *, kind: str, client: dict, entry: Optional[dict], note_id: Optional[str],
              account: str, folder_path: List[str], title: str, base: Optional[str], before: Optional[str],
              after: Optional[str], request: dict, rule: dict) -> dict:
        if self.approvals.count() >= MAX_PENDING:
            raise WriteRefused(429, f"the approval list is full ({MAX_PENDING} held writes): approve or reject "
                                    "some first", reason="approvals_full", retry_after=3600)
        pct = None
        if before is not None and kind != "create":
            pct = 100.0 if kind == "delete" else _change_percent(before, after or "")
        item = self.approvals.add(kind=kind, note_id=note_id, account=account, folder_path=folder_path,
                                  title=title or ((entry or {}).get("title") or ""), base=base, before=before,
                                  after=after, request=request, client=client, rule=rule, change=pct)
        self.limits.record_request(client.get("label", ""), settings.write_hold_batch_seconds)
        self._log(by=client.get("label", ""), operation=kind, note_id=note_id, ok=True, held=True,
                  approval_id=item["id"], hold_reason=rule["reason"])
        return {"held": True, "approval_id": item["id"], "reason": rule["reason"], "detail": rule["detail"],
                "kind": kind, "note_id": note_id, "modified": None, "backup_note_id": None, "run": None}

    def _applied(self, settings, client_label: str) -> None:
        self.limits.record_change(settings.write_hold_window_hours)
        self.limits.record_request(client_label, settings.write_hold_batch_seconds)

    # ---- the writes ----
    def update(self, note_id: str, *, markdown: str, base_modified: Optional[str], title: str = "",
               force: bool = False, accept_losses: bool = False, by: str = "",
               export: bool = True, formats: Optional[List[str]] = None, backup: Optional[str] = None,
               client: Optional[dict] = None, _approved_by: Optional[str] = None) -> dict:
        self._guard()
        settings = self._load_settings()
        choice = self._backup_choice(settings, backup, "folder")
        entry = self._writable_entry(note_id)
        lost = losses(entry)
        if lost and not accept_losses:
            raise WriteRefused(409, "writing this note would lose " + "; ".join(lost), reason="losses", losses=lost)
        self._check_export(entry, base_modified, force)
        client = client or {"label": by}
        if not _approved_by:
            before = self._note_text(entry)
            rule = self._hold_rule(settings, client_label=client.get("label", ""), before=before, after=markdown,
                                   kind="update")
            if rule:
                return self._held(settings, kind="update", client=client, entry=entry, note_id=note_id,
                                  account=entry.get("account") or "", folder_path=list(entry.get("folder_path") or []),
                                  title=title, base=base_modified or entry.get("modified"), before=before,
                                  after=markdown, rule=rule,
                                  request={"markdown": markdown, "title": title, "force": force,
                                           "accept_losses": accept_losses, "backup": choice, "export": export,
                                           "formats": list(formats or [])})
        if not self._lock.acquire(blocking=False):
            raise WriteRefused(409, "another write is in progress", reason="busy")
        backup_id = None
        try:
            if not _approved_by:
                self._check_limit(settings)
            if not force:
                self._check_live(note_id, entry)
            if choice == "folder":
                backup_id = self._backup(note_id, entry, settings, by)
            out = self._helper({"operation": "update", "note_id": note_id, "title": title, "markdown": markdown,
                                "base_dir": self._base_dir(entry), "root": str(self._export_root())})
            self._log(by=by, operation="update", note_id=note_id, ok=bool(out.get("ok")), force=force,
                      accept_losses=accept_losses, backup_note_id=backup_id, approved_by=_approved_by,
                      error=None if out.get("ok") else out.get("error"))
            if not out.get("ok"):
                raise self._failed(out)
            self._applied(settings, client.get("label", ""))
        finally:
            self._lock.release()
        run = self._after(entry.get("account") or "", list(entry.get("folder_path") or []), formats, export)
        return {"note_id": out.get("note_id") or note_id, "modified": out.get("modified"),
                "backup_note_id": backup_id, "run": run}

    def delete(self, note_id: str, *, base_modified: Optional[str], force: bool = False, by: str = "",
               backup: Optional[str] = None, export: bool = True, formats: Optional[List[str]] = None,
               client: Optional[dict] = None, _approved_by: Optional[str] = None) -> dict:
        """Notes' own delete — the note goes to Recently Deleted — after the update's checks."""
        self._guard()
        settings = self._load_settings()
        choice = self._backup_choice(settings, backup, "none")
        if base_modified is None and not force:
            raise WriteRefused(400, "send base, the note's modified when you read it, to delete it",
                               reason="bad_request")
        entry = self._writable_entry(note_id)
        self._check_export(entry, base_modified, force)
        client = client or {"label": by}
        if not _approved_by:
            before = self._note_text(entry)
            rule = self._hold_rule(settings, client_label=client.get("label", ""), before=before, after=None,
                                   kind="delete")
            if rule:
                return self._held(settings, kind="delete", client=client, entry=entry, note_id=note_id,
                                  account=entry.get("account") or "", folder_path=list(entry.get("folder_path") or []),
                                  title="", base=base_modified or entry.get("modified"), before=before, after="",
                                  rule=rule, request={"force": force, "backup": choice, "export": export,
                                                      "formats": list(formats or [])})
        if not self._lock.acquire(blocking=False):
            raise WriteRefused(409, "another write is in progress", reason="busy")
        backup_id = None
        try:
            if not _approved_by:
                self._check_limit(settings)
            if not force:
                self._check_live(note_id, entry)
            if choice == "folder":
                backup_id = self._backup(note_id, entry, settings, by)
            out = self._helper({"operation": "delete", "note_id": note_id})
            self._log(by=by, operation="delete", note_id=note_id, ok=bool(out.get("ok")), force=force,
                      backup_note_id=backup_id, approved_by=_approved_by,
                      error=None if out.get("ok") else out.get("error"))
            if not out.get("ok"):
                raise self._failed(out)
            self._applied(settings, client.get("label", ""))
        finally:
            self._lock.release()
        run = self._after(entry.get("account") or "", list(entry.get("folder_path") or []), formats, export)
        return {"note_id": note_id, "deleted": True, "recently_deleted": True, "backup_note_id": backup_id,
                "run": run}

    def create(self, *, account: str, folder_path: List[str], markdown: str, title: str = "", by: str = "",
               export: bool = True, formats: Optional[List[str]] = None, client: Optional[dict] = None,
               _approved_by: Optional[str] = None) -> dict:
        self._guard()
        settings = self._load_settings()
        folders = [str(f).strip() for f in folder_path or [] if str(f).strip()]
        account = (account or "").strip()
        if not account or not folders:
            raise WriteRefused(400, "a new note needs an account and a folder", reason="bad_request")
        if not self._known_folder(account, folders):
            raise WriteRefused(404, "the export has no such folder — new notes go into folders it already holds",
                               reason="not_found")
        if not (markdown or "").strip():
            raise WriteRefused(400, "a new note needs some text", reason="bad_request")
        client = client or {"label": by}
        if not _approved_by:
            rule = self._hold_rule(settings, client_label=client.get("label", ""), before=None, after=markdown,
                                   kind="create")
            if rule:
                return self._held(settings, kind="create", client=client, entry=None, note_id=None, account=account,
                                  folder_path=folders, title=title, base=None, before="", after=markdown, rule=rule,
                                  request={"markdown": markdown, "title": title, "export": export,
                                           "formats": list(formats or [])})
        if not self._lock.acquire(blocking=False):
            raise WriteRefused(409, "another write is in progress", reason="busy")
        try:
            if not _approved_by:
                self._check_limit(settings)
            out = self._helper({"operation": "create", "account": account, "folder_path": folders, "title": title,
                                "markdown": markdown, "base_dir": str(self._export_root()),
                                "root": str(self._export_root())})
            self._log(by=by, operation="create", note_id=out.get("note_id"), ok=bool(out.get("ok")),
                      approved_by=_approved_by, error=None if out.get("ok") else out.get("error"))
            if not out.get("ok"):
                raise self._failed(out)
            self._applied(settings, client.get("label", ""))
        finally:
            self._lock.release()
        run = self._after(account, folders, formats, export)
        return {"note_id": out.get("note_id"), "modified": out.get("modified"), "run": run}

    # ---- approving and rejecting ----
    def approve(self, approval_id: str, *, by: str, export: Optional[bool] = None) -> dict:
        """Make a held write the normal way (backup, conflict checks against the base it was asked
        on — never forced past a change made meanwhile). A conflict marks it ``stale`` and keeps it."""
        item = self.approvals.get(approval_id)
        if not item:
            raise WriteRefused(404, "no such held write", reason="not_found")
        req = item.get("request") or {}
        client = item.get("client") or {}
        label = client.get("label", "")
        do_export = req.get("export", True) if export is None else export
        try:
            if item["kind"] == "update":
                out = self.update(item["note_id"], markdown=req.get("markdown") or "", base_modified=item.get("base"),
                                  title=req.get("title") or "", force=False,
                                  accept_losses=bool(req.get("accept_losses")), by=label, export=do_export,
                                  formats=req.get("formats"), backup=req.get("backup") or "folder",
                                  client=client, _approved_by=by)
            elif item["kind"] == "delete":
                out = self.delete(item["note_id"], base_modified=item.get("base") or "", force=False, by=label,
                                  backup=req.get("backup") or "none", export=do_export, formats=req.get("formats"),
                                  client=client, _approved_by=by)
            else:
                out = self.create(account=item.get("account") or "", folder_path=item.get("folder_path") or [],
                                  markdown=req.get("markdown") or "", title=req.get("title") or "", by=label,
                                  export=do_export, formats=req.get("formats"), client=client, _approved_by=by)
        except WriteRefused as e:
            reason = e.info.get("reason")
            if reason in STALE_REASONS:
                item.update(status="stale", stale_reason=reason, tries=int(item.get("tries") or 0) + 1)
                self.approvals.update(item)
                e.info["stale"] = True
            e.info["approval_id"] = approval_id
            raise
        self.approvals.remove(approval_id)
        self._log(by=by, operation="approve", approval_id=approval_id, kind=item["kind"], note_id=item.get("note_id"),
                  ok=True, client=label)
        return dict(out, approval_id=approval_id, approved=True, kind=item["kind"])

    def reject(self, approval_id: str, *, by: str) -> dict:
        item = self.approvals.get(approval_id)
        if not item or not self.approvals.remove(approval_id):
            raise WriteRefused(404, "no such held write", reason="not_found")
        self._log(by=by, operation="reject", approval_id=approval_id, kind=item["kind"], note_id=item.get("note_id"),
                  ok=True, client=(item.get("client") or {}).get("label"))
        return {"approval_id": approval_id, "rejected": True}
