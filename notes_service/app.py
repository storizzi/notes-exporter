"""The HTTP API (SERVICE-API.md) and the web UI."""

import os
import subprocess
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import API_VERSION, MANIFEST_VERSION, __version__
from .auth import ROLES, SCOPES, AuthError, AuthStore, LoginLimiter, Principal
from .config import Config, default_home
from .exports import ExportReader, PathRefused, content_type, iter_file, parse_range
from .permissions import PermissionChecker, PermissionRequestBusy
from .runs import RunBusy, RunError, RunManager, RunStore, read_events
from .scheduler import Scheduler
from .settings import CLIENT_READ_ONLY, RUN_FORMATS, SettingsError, SettingsStore, export_root_state
from .updates import UpdateManager, UpdateRefused
from .approvals import detail as approval_detail, html_text, summary as approval_summary
from .writes import FEATURES, WriteManager, WriteRefused
from . import mcp_client

WEB_DIR = Path(__file__).parent / "web"
# Query parameters that look like credentials: refused, so a key never ends up in a log or history.
CREDENTIAL_PARAMS = {"token", "apikey", "api_key", "api-key", "access_token", "key", "password", "jwt", "auth"}
FORWARD_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host")
LOOPBACK_CLIENTS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
          "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
# Exported note HTML is served as data: no scripts, its own opaque origin.
FILE_CSP = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; media-src 'self'"

RunFormat = Literal[RUN_FORMATS]  # type: ignore[valid-type]
Scope = Literal[SCOPES]  # type: ignore[valid-type]


class Context:
    def __init__(self, config: Config, permissions: Optional[PermissionChecker] = None):
        self.config = config
        config.ensure_home()
        self.auth = AuthStore(config)
        self.settings = SettingsStore(config)
        self.runs = RunStore(config)
        self.permissions = permissions or PermissionChecker(config)
        self.manager = RunManager(config, self.runs, self.settings, on_finish=self._finished)
        self.exports = ExportReader(lambda: self.settings.load().export_root)
        self.limiter = LoginLimiter(config.login_max_attempts, config.login_window_seconds)
        self.scheduler = Scheduler(
            config.scheduler_tick_seconds,
            get_schedule=lambda: self.settings.load().schedule.model_dump(),
            last_started=self._last_started,
            start_run=lambda: self.manager.start(trigger="schedule", requested_by="schedule"),
            is_running=lambda: self.manager.running_run_id is not None)
        self.writes = WriteManager(
            config, load_settings=self.settings.load, note_entry=self._note_entry,
            known_folder=self._known_folder, export_root=lambda: self.settings.load().export_root,
            running_run_id=lambda: self.manager.running_run_id, start_run=self._export_folder,
            note_text=self._note_text)
        self.updates = UpdateManager(config, running_run_id=lambda: self.manager.running_run_id)

    def _note_entry(self, note_id: str) -> Optional[dict]:
        try:
            view = self.exports.manifest()
        except ValueError:
            return None
        return self.exports.note(view, note_id) if view else None

    def _note_text(self, entry: dict) -> Optional[str]:
        """The note's text as the export has it now — its Markdown, else plain text, else the
        HTML's words — for the approval list's before / after (None when none can be read)."""
        outputs = (entry or {}).get("outputs") or {}
        for fmt in ("md", "text", "html", "raw"):
            rel = (outputs.get(fmt) or {}).get("path")
            if not rel:
                continue
            try:
                path = self.exports.resolve(rel)
                text = path.read_text(encoding="utf-8", errors="replace")
            except (PathRefused, OSError, ValueError):
                continue
            return html_text(text) if fmt in ("html", "raw") else text
        return None

    def _known_folder(self, account: str, folders: List[str]) -> bool:
        """Whether the export holds a note in that folder (or under it) of that account (name or id)."""
        try:
            view = self.exports.manifest()
        except ValueError:
            return False
        if not view:
            return False
        for n in view.data.get("notes", []):
            path = list(n.get("folder_path") or [])
            if account in (n.get("account"), n.get("account_id")) and path[:len(folders)] == folders:
                return True
        return False

    def _export_folder(self, account: str, folders: List[str], formats: Optional[List[str]]):
        """After a write: export that folder so the manifest has the new version."""
        try:
            return self.manager.start(trigger="api", folders=["/".join(folders)] if folders else [],
                                      accounts=[account] if account else [],
                                      formats=[f for f in formats or [] if f in RUN_FORMATS],
                                      requested_by="write")
        except RunBusy:
            return None

    def _last_started(self) -> Optional[str]:
        last = self.runs.latest()
        return (last.get("started_at") or last.get("created_at")) if last else None

    def _finished(self, run: dict) -> None:
        if run:
            self.permissions.note_run_state(run.get("permission"))


# ---- request models ----
class Login(BaseModel):
    username: str
    password: str


class Setup(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class RunRequest(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"
    folders: List[str] = Field(default_factory=list)
    accounts: List[str] = Field(default_factory=list)
    formats: List[RunFormat] = Field(default_factory=list)  # type: ignore[valid-type]
    epub_books: Optional[Literal["none", "folder"]] = None
    epub_book_order: Optional[Literal["modified", "created", "title"]] = None
    epub_book_subfolders: Optional[Literal["separate", "nested"]] = None
    trigger: Literal["api", "ui", "cli"] = "api"


class NoteUpdate(BaseModel):
    markdown: str
    base_modified: Optional[str] = None
    title: str = ""
    force: bool = False
    accept_losses: bool = False
    export: bool = True
    formats: List[RunFormat] = Field(default_factory=list)  # type: ignore[valid-type]
    # 1.7.0: copy the note into the backup folder first (default), or not (only while the
    # admin's write_backup_required is off).
    backup: Optional[Literal["folder", "none"]] = None


class NoteCreate(BaseModel):
    account: str
    folder_path: List[str]
    markdown: str
    title: str = ""
    export: bool = True
    formats: List[RunFormat] = Field(default_factory=list)  # type: ignore[valid-type]


class ApprovalBulk(BaseModel):
    action: Literal["approve", "reject"]
    ids: List[str] = Field(default_factory=list)
    all: bool = False


class LoginLinkRequest(BaseModel):
    next: Optional[str] = None


class LoginLinkExchange(BaseModel):
    token: str


def _safe_next(value: str) -> Optional[str]:
    """A path on this service (``/approvals``, ``/``), or None: never another site."""
    v = (value or "/").strip()
    if not v.startswith("/") or v.startswith("//") or "\\" in v or any(c in v for c in "\r\n\t\0") or len(v) > 200:
        return None
    if "://" in v.split("?")[0]:
        return None
    return v


class UserCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "reader"] = "reader"


class UserPatch(BaseModel):
    password: Optional[str] = None
    role: Optional[Literal["admin", "reader"]] = None


class PermissionRequest(BaseModel):
    wait: Optional[bool] = None


class Refusal(Exception):
    """An error answered as ``{detail, reason, …}`` (a plain HTTPException has only ``detail``)."""

    def __init__(self, status: int, detail: str, reason: str, **info):
        super().__init__(detail)
        self.status, self.detail, self.reason, self.info = status, detail, reason, info


def _settings_error(e: SettingsError) -> JSONResponse:
    """422 for an invalid setting: the message as ``detail`` (as before), plus ``reason`` and ``field``."""
    return JSONResponse({"detail": str(e), "reason": e.reason, "field": e.field}, status_code=422)


def _run_summary(prefix: str, run: Optional[dict]) -> dict:
    return {f"{prefix}_id": run["id"] if run else None,
            f"{prefix}_status": run["status"] if run else None,
            f"{prefix}_finished_at": run.get("finished_at") if run else None,
            f"{prefix}_message": run.get("message") if run else None}


class UpdateRequest(BaseModel):
    to: Optional[str] = None


class RestartRequest(BaseModel):
    force: bool = False


class KeyCreate(BaseModel):
    name: str
    scopes: List[Scope] = Field(default_factory=lambda: ["read"])  # type: ignore[valid-type]
    owner_user_id: Optional[str] = None
    expires_at: Optional[str] = None


class McpKeyCreate(BaseModel):
    """A key for the MCP server: kept in the state directory's mcp.env (clients on this Mac read it),
    or shown once for a client on another computer."""
    name: str = mcp_client.DEFAULT_KEY_NAME
    scopes: List[Literal["read", "run", "write"]] = Field(default_factory=lambda: ["read", "run"])
    keep: Literal["env_file", "show"] = "env_file"
    expires_at: Optional[str] = None
    read_only: bool = False


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_loopback(request: Request) -> bool:
    if any(h in request.headers for h in FORWARD_HEADERS):
        return False  # through a proxy: the real client is not known to be local
    return _client_ip(request) in LOOPBACK_CLIENTS


def create_app(config: Optional[Config] = None, permissions: Optional[PermissionChecker] = None) -> FastAPI:
    config = config or Config.from_env()
    ctx = Context(config, permissions)

    @asynccontextmanager
    async def lifespan(app):
        ctx.runs.recover()
        if config.scheduler_enabled:
            ctx.scheduler.start()
        try:
            yield
        finally:
            ctx.scheduler.stop()
            ctx.manager.shutdown()

    app = FastAPI(title="notes-exporter service", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if config.docs else None, redoc_url=None,
                  openapi_url="/openapi.json" if config.docs else None)
    app.state.ctx = ctx

    @app.exception_handler(Refusal)
    async def refusal(request: Request, e: Refusal):
        return JSONResponse({"detail": e.detail, "reason": e.reason, **e.info}, status_code=e.status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        names = {k.lower() for k in request.query_params.keys()}
        if names & CREDENTIAL_PARAMS:
            return JSONResponse({"detail": "credentials are not accepted in the URL; "
                                           "send Authorization: Bearer … or X-API-Key"}, status_code=400)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", UI_CSP)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ---- auth dependencies ----
    def principal(request: Request) -> Principal:
        cred = None
        header = request.headers.get("authorization", "")
        if header[:7].lower() == "bearer ":
            cred = header[7:].strip()
        elif request.headers.get("x-api-key"):
            cred = request.headers["x-api-key"].strip()
        p = ctx.auth.authenticate(cred) if cred else None
        if not p:
            raise HTTPException(401, "not signed in, or the token or key is not valid",
                                headers={"WWW-Authenticate": "Bearer"})
        return p

    def need(scope: str):
        def dep(p: Principal = Depends(principal)) -> Principal:
            if scope not in p.scopes:
                raise Refusal(403, f"this needs the {scope!r} scope",
                              "not_admin" if scope == "admin" else "scope", scope=scope)
            return p
        return dep

    def _auth_error(e: AuthError):
        msg = str(e)
        code = 404 if msg == "no such user" else 409 if "last admin" in msg or "already exists" in msg else 400
        raise HTTPException(code, msg)

    # ---- public ----
    @app.get("/api/health")
    def health():
        return {"service": "notes-exporter", "version": __version__, "api_version": API_VERSION,
                "manifest_version": MANIFEST_VERSION, "platform": sys.platform,
                "macos_version": platform.mac_ver()[0] or None, "features": list(FEATURES)}

    @app.get("/api/setup")
    def setup_state(request: Request):
        return {"needed": ctx.auth.user_count() == 0, "allowed_here": _is_loopback(request)}

    @app.post("/api/setup", status_code=201)
    def setup(body: Setup, request: Request):
        if not _is_loopback(request):
            raise HTTPException(403, "setup only answers on this Mac (a loopback connection)")
        if ctx.auth.user_count():
            raise HTTPException(409, "setup is already done; sign in")
        try:
            user = ctx.auth.create_first_admin(body.username, body.password)
        except AuthError as e:
            if "already done" in str(e):
                raise HTTPException(409, str(e))
            raise HTTPException(400, str(e))
        session = ctx.auth.create_session(ctx.auth.get_user(user["id"]))
        return {"user": user, **session}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request):
        ip = _client_ip(request)
        if ctx.limiter.blocked(ip):
            raise HTTPException(429, "too many failed sign-ins; try again later")
        user = ctx.auth.verify_password(body.username, body.password)
        if not user:
            ctx.limiter.failed(ip)
            raise HTTPException(401, "wrong username or password")
        ctx.limiter.succeeded(ip)
        return {**ctx.auth.create_session(user), "user": ctx.auth.public_user(user)}

    @app.post("/api/auth/logout")
    def logout(p: Principal = Depends(principal)):
        if p.session_id:
            ctx.auth.revoke_session(p.session_id)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(p: Principal = Depends(principal)):
        return p.public()

    @app.post("/api/auth/password")
    def change_password(body: PasswordChange, p: Principal = Depends(principal)):
        if p.kind != "user":
            raise HTTPException(403, "an API key can't change a password")
        user = ctx.auth.get_user(p.user_id)
        if not ctx.auth.verify_password(user["username"], body.current_password):
            raise HTTPException(403, "the current password is wrong")
        try:
            ctx.auth.set_password(p.user_id, body.new_password)
        except AuthError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    # ---- read ----
    @app.get("/api/status")
    def status(p: Principal = Depends(need("read"))):
        settings = ctx.settings.load()
        last = ctx.runs.latest(finished_only=True)
        nxt = ctx.scheduler.next_run_at()
        root = settings.export_root
        return {
            "running_run_id": ctx.manager.running_run_id,
            "last_run": last,
            # The same as flat fields, so a client needn't read the history: the last finished run,
            # the last that failed and the last that succeeded (ok or partial). A failure is
            # still current when last_failed_run_id == last_run_id.
            **_run_summary("last_run", last),
            **_run_summary("last_failed_run", ctx.runs.latest_with_status("failed")),
            **_run_summary("last_success_run", ctx.runs.latest_with_status("ok", "partial")),
            "next_run_at": nxt.isoformat(timespec="seconds") if nxt else None,
            "schedule": settings.schedule.model_dump(),
            "export_root": root,
            **export_root_state(root),
            "manifest_present": os.path.isfile(os.path.join(root, "manifest.json")),
            "permission": dict(ctx.permissions.get(), requesting=ctx.permissions.requesting),
            "formats": settings.formats,
            "epub_books": settings.epub_books,
            "version": __version__,
            "writes": {"allowed": settings.allow_writes, **ctx.writes.fences(settings)},
        }

    def _manifest_or_404():
        try:
            view = ctx.exports.manifest()
        except ValueError:
            raise HTTPException(503, "manifest.json could not be read")
        if not view:
            raise HTTPException(404, "no manifest yet: no export has run in this folder")
        return view

    @app.get("/api/manifest")
    def manifest(request: Request, p: Principal = Depends(need("read"))):
        view = _manifest_or_404()
        headers = {"ETag": view.etag, "Cache-Control": "no-cache"}
        inm = request.headers.get("if-none-match", "")
        if view.etag in [t.strip() for t in inm.split(",")] or inm.strip() == "*":
            return Response(status_code=304, headers=headers)
        return Response(view.raw, media_type="application/json", headers=headers)

    @app.get("/api/notes")
    def notes(changed_since_sequence: Optional[int] = None, account: Optional[str] = None,
              folder: Optional[str] = None, include_deleted: bool = False,
              p: Principal = Depends(need("read"))):
        view = _manifest_or_404()
        return ctx.exports.notes(view, changed_since_sequence=changed_since_sequence, account=account,
                                 folder=folder, include_deleted=include_deleted)

    # ---- writing to Notes (the `write` scope; writes.py has the fences) ----
    def _write_error(e: WriteRefused):
        headers = {"Retry-After": str(e.info["retry_after"])} if e.info.get("retry_after") else None
        return JSONResponse({"detail": str(e), **e.info}, status_code=e.status, headers=headers)

    def _client(p: Principal) -> dict:
        """Who asked, for a held write: the key's name (or the user), never the key."""
        out = {"label": p.label, "kind": p.kind, "user_id": p.user_id, "username": p.username}
        if p.kind == "key":
            row = ctx.auth.find_key(p.key_id) or {}
            out.update(key_id=p.key_id, name=row.get("name") or p.label)
        else:
            out["name"] = p.username
        return out

    def _written(result: dict, status: int):
        # A held write is 202 {held: true, approval_id, reason}: accepted, not made.
        return JSONResponse(result, status_code=202 if result.get("held") else status)

    @app.get("/api/writes")
    def write_state(p: Principal = Depends(need("read"))):
        return dict(ctx.writes.state(), can_write="write" in p.scopes, can_approve="approve" in p.scopes)

    @app.post("/api/notes", status_code=201)
    def create_note(body: NoteCreate, p: Principal = Depends(need("write"))):
        try:
            return _written(ctx.writes.create(account=body.account, folder_path=body.folder_path,
                                              markdown=body.markdown, title=body.title, by=p.label,
                                              export=body.export, formats=list(body.formats), client=_client(p)), 201)
        except WriteRefused as e:
            return _write_error(e)

    @app.put("/api/notes/{note_id:path}")
    def update_note(note_id: str, body: NoteUpdate, p: Principal = Depends(need("write"))):
        try:
            return _written(ctx.writes.update(note_id, markdown=body.markdown, base_modified=body.base_modified,
                                              title=body.title, force=body.force, accept_losses=body.accept_losses,
                                              by=p.label, export=body.export, formats=list(body.formats),
                                              backup=body.backup, client=_client(p)), 200)
        except WriteRefused as e:
            return _write_error(e)

    @app.delete("/api/notes/{note_id:path}")
    def delete_note(note_id: str, base: Optional[str] = None, base_modified: Optional[str] = None,
                    backup: Optional[Literal["folder", "none"]] = None, force: bool = False, export: bool = True,
                    p: Principal = Depends(need("write"))):
        try:
            return _written(ctx.writes.delete(note_id, base_modified=base if base is not None else base_modified,
                                              force=force, backup=backup, by=p.label, export=export,
                                              client=_client(p)), 200)
        except WriteRefused as e:
            return _write_error(e)

    # ---- the approval list (scope approve; a write key sees only its own held writes) ----
    def _approver_or_own(p: Principal) -> Principal:
        if "approve" not in p.scopes and "write" not in p.scopes:
            raise Refusal(403, "this needs the 'approve' scope (or 'write', for your own held writes)", "scope",
                          scope="approve")
        return p

    def _own(p: Principal, item: dict) -> bool:
        client = item.get("client") or {}
        if p.kind == "key":
            return client.get("key_id") == p.key_id
        return client.get("kind") == "user" and client.get("user_id") == p.user_id

    def _visible(p: Principal, item: dict) -> bool:
        return "approve" in p.scopes or _own(p, item)

    def _held_items(p: Principal) -> list:
        items = ctx.writes.approvals.all(ctx.settings.load().write_hold_max_age_days)
        return [i for i in items if _visible(p, i)]

    @app.get("/api/approvals")
    def approvals(p: Principal = Depends(principal)):
        _approver_or_own(p)
        items = _held_items(p)
        counts = {"total": len(items), "pending": sum(1 for i in items if i.get("status") == "pending"),
                  "stale": sum(1 for i in items if i.get("status") == "stale")}
        for kind in ("update", "create", "delete"):
            counts[kind] = sum(1 for i in items if i.get("kind") == kind)
        return {"approvals": [approval_summary(i) for i in items], "counts": counts,
                "can_approve": "approve" in p.scopes}

    @app.get("/api/approvals/{approval_id}")
    def approval(approval_id: str, p: Principal = Depends(principal)):
        _approver_or_own(p)
        item = ctx.writes.approvals.get(approval_id)
        if not item:
            # Decided already (here or by someone else): what became of it, without the texts.
            gone = ctx.writes.approvals.decided(approval_id)
            if gone and _visible(p, gone):
                return gone
            raise Refusal(404, "no such held write", "not_found")
        if not _visible(p, item):
            raise Refusal(404, "no such held write", "not_found")
        return approval_detail(item)

    def _approve_one(approval_id: str, p: Principal, export: Optional[bool] = None):
        try:
            result = ctx.writes.approve(approval_id, by=p.label, export=export)
        except WriteRefused as e:
            return False, {"detail": str(e), **e.info, "status": e.status}
        return True, result

    @app.post("/api/approvals/{approval_id}/approve")
    def approve(approval_id: str, p: Principal = Depends(need("approve"))):
        ok, result = _approve_one(approval_id, p)
        if ok:
            return result
        status = result.pop("status")
        return JSONResponse(result, status_code=status)

    @app.post("/api/approvals/{approval_id}/reject")
    def reject(approval_id: str, p: Principal = Depends(need("approve"))):
        try:
            return ctx.writes.reject(approval_id, by=p.label)
        except WriteRefused as e:
            return _write_error(e)

    @app.post("/api/approvals/bulk")
    def approvals_bulk(body: ApprovalBulk, p: Principal = Depends(need("approve"))):
        items = ctx.writes.approvals.all(ctx.settings.load().write_hold_max_age_days)
        if body.all:
            ids = [i["id"] for i in items if body.action == "reject" or i.get("status") == "pending"]
        else:
            ids = list(dict.fromkeys(body.ids or []))
        if not ids and not body.all:
            raise Refusal(400, "send ids, or all: true", "bad_request")
        results, folders, accounts, formats = [], set(), set(), set()
        for approval_id in ids:
            if body.action == "reject":
                try:
                    results.append(dict(ctx.writes.reject(approval_id, by=p.label), ok=True))
                except WriteRefused as e:
                    results.append({"approval_id": approval_id, "ok": False, "detail": str(e), **e.info})
                continue
            item = ctx.writes.approvals.get(approval_id) or {}
            # One export afterwards for all of them, not one each (a running export refuses writes).
            ok, result = _approve_one(approval_id, p, export=False)
            if ok:
                if (item.get("request") or {}).get("export", True):
                    folders.add("/".join(item.get("folder_path") or []))
                    accounts.add(item.get("account") or "")
                    formats.update((item.get("request") or {}).get("formats") or [])
                results.append(dict(result, ok=True))
            else:
                result.pop("status", None)
                results.append(dict(result, approval_id=approval_id, ok=False))
        run = None
        if folders:
            try:
                run = ctx.manager.start(trigger="api", folders=sorted(f for f in folders if f),
                                        accounts=sorted(a for a in accounts if a),
                                        formats=[f for f in formats if f in RUN_FORMATS], requested_by="approve")
            except RunBusy:
                run = None
        return {"results": results, "approved": sum(1 for r in results if r.get("ok") and r.get("approved")),
                "rejected": sum(1 for r in results if r.get("ok") and r.get("rejected")),
                "failed": sum(1 for r in results if not r.get("ok")), "run": run}

    # ---- a one-off sign-in link for the web page ----
    @app.post("/api/auth/login-link")
    def login_link(request: Request, body: Optional[LoginLinkRequest] = None, p: Principal = Depends(principal)):
        if not ({"admin", "approve"} & p.scopes):
            raise Refusal(403, "a sign-in link needs the 'admin' or 'approve' scope", "scope", scope="approve")
        nxt = _safe_next((body.next if body else None) or "/")
        if nxt is None:
            raise Refusal(400, "next must be a path on this service, such as /approvals", "bad_request",
                          field="next")
        ttl = ctx.settings.load().login_link_ttl_seconds
        link = ctx.auth.create_login_link(p.user_id, set(p.scopes), nxt, ttl, p.label)
        base = str(request.base_url).rstrip("/")
        # The token is in the fragment: browsers never send it, so it is in no server or proxy log.
        return {"url": f"{base}/login-link#{link['token']}", "expires_at": link["expires_at"], "next": nxt,
                "ttl_seconds": ttl}

    @app.post("/api/auth/login-link/exchange")
    def login_link_exchange(body: LoginLinkExchange, request: Request):
        ip = _client_ip(request)
        if ctx.limiter.blocked(ip):
            raise HTTPException(429, "too many failed sign-ins; try again later")
        session = ctx.auth.redeem_login_link(body.token)
        if not session:
            ctx.limiter.failed(ip)
            raise Refusal(401, "this sign-in link isn't valid any more (it works once, for a short time)",
                          "link_invalid")
        ctx.limiter.succeeded(ip)
        return session

    @app.get("/api/notes/{note_id:path}")
    def note(note_id: str, p: Principal = Depends(need("read"))):
        view = _manifest_or_404()
        entry = ctx.exports.note(view, note_id)
        if not entry:
            raise HTTPException(404, "no such note")
        return entry

    @app.api_route("/api/files/{rel:path}", methods=["GET", "HEAD"])
    def files(rel: str, request: Request, p: Principal = Depends(need("read"))):
        try:
            path = ctx.exports.resolve(rel)
        except PathRefused as e:
            raise HTTPException(403, str(e))
        if not path.is_file():
            raise HTTPException(404, "no such file")
        st = path.stat()
        etag = ctx.exports.etag_for(rel, path, st)
        headers = {"ETag": etag, "Accept-Ranges": "bytes", "Cache-Control": "no-cache",
                   "Content-Security-Policy": FILE_CSP,
                   "Last-Modified": _http_date(st.st_mtime)}
        inm = request.headers.get("if-none-match")
        if inm and (etag in [t.strip() for t in inm.split(",")] or inm.strip() == "*"):
            return Response(status_code=304, headers=headers)
        size = st.st_size
        rng = request.headers.get("range")
        if_range = request.headers.get("if-range")
        if rng and if_range and if_range.strip() != etag:
            rng = None  # the file changed: send it whole
        r = parse_range(rng, size)
        ctype = content_type(path.name)
        if r == "unsatisfiable":
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        if r is None:
            start, end, code = 0, size - 1, 200
        else:
            (start, end), code = r, 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = max(0, end - start + 1)
        headers["Content-Length"] = str(length)
        if request.method == "HEAD":
            return Response(status_code=code, headers=headers, media_type=ctype)
        return StreamingResponse(iter_file(path, start, length, config.file_chunk_bytes), status_code=code,
                                 headers=headers, media_type=ctype)

    # ---- runs ----
    @app.post("/api/runs", status_code=202)
    def start_run(body: Optional[RunRequest] = None, p: Principal = Depends(need("run"))):
        body = body or RunRequest()
        try:
            run = ctx.manager.start(trigger=body.trigger, mode=body.mode, folders=body.folders,
                                    accounts=body.accounts, formats=list(body.formats),
                                    epub_books=body.epub_books, requested_by=p.label,
                                    epub_book_order=body.epub_book_order,
                                    epub_book_subfolders=body.epub_book_subfolders)
        except RunBusy as e:
            return JSONResponse({"detail": "a run is already in progress", "running_run_id": e.running_run_id},
                                status_code=409)
        except (RunError, ValueError) as e:
            raise HTTPException(400, str(e))
        return {"run": run}

    @app.get("/api/runs")
    def list_runs(limit: int = Query(20, ge=1, le=500), offset: int = Query(0, ge=0),
                  p: Principal = Depends(need("read"))):
        runs, total = ctx.runs.list(limit, offset)
        return {"runs": runs, "total": total}

    def _run_or_404(run_id: str) -> dict:
        run = ctx.runs.get(run_id)
        if not run:
            raise HTTPException(404, "no such run")
        return run

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, p: Principal = Depends(need("read"))):
        return _run_or_404(run_id)

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str, after: int = Query(0, ge=0), p: Principal = Depends(need("read"))):
        run = _run_or_404(run_id)
        lines = read_events(ctx.runs.events_path(run_id), after)
        body = "".join(line + "\n" for line in lines)
        return Response(body, media_type="application/x-ndjson",
                        headers={"X-Next-After": str(after + len(lines)), "X-Run-Status": run["status"]})

    @app.get("/api/runs/{run_id}/log")
    def run_log(run_id: str, p: Principal = Depends(need("read"))):
        _run_or_404(run_id)
        path = ctx.runs.log_path(run_id)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        return PlainTextResponse(text)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, p: Principal = Depends(need("run"))):
        _run_or_404(run_id)
        return {"run": ctx.manager.cancel(run_id)}

    # ---- settings (the `settings` scope: everything but where the export goes) ----
    def _update_error(e: UpdateRefused):
        return JSONResponse({"detail": str(e), **e.info}, status_code=e.status)

    @app.get("/api/version")
    def version(refresh: bool = False, p: Principal = Depends(need("read"))):
        return dict(ctx.updates.view(refresh=refresh), features=list(FEATURES))

    @app.post("/api/admin/update")
    def update(body: Optional[UpdateRequest] = None, p: Principal = Depends(need("admin"))):
        try:
            return ctx.updates.update((body.to if body else None), who=p.label)
        except UpdateRefused as e:
            return _update_error(e)

    @app.post("/api/admin/restart", status_code=202)
    def restart(body: Optional[RestartRequest] = None, p: Principal = Depends(need("admin"))):
        try:
            return ctx.updates.restart(force=bool(body and body.force), who=p.label)
        except UpdateRefused as e:
            return _update_error(e)

    def _client_settings(settings) -> dict:
        # The export folder's state beside the settings (not in them), so they can be sent back as they are.
        return {"settings": settings.model_dump(), "read_only": list(CLIENT_READ_ONLY),
                **export_root_state(settings.export_root)}

    @app.get("/api/settings")
    def get_client_settings(p: Principal = Depends(need("settings"))):
        return _client_settings(ctx.settings.load())

    @app.put("/api/settings")
    async def put_client_settings(request: Request, p: Principal = Depends(need("settings"))):
        try:
            changes = await request.json()
        except ValueError:
            raise HTTPException(400, "send the settings as a JSON object")
        if not isinstance(changes, dict):
            raise HTTPException(400, "send the settings as a JSON object")
        current = ctx.settings.load().model_dump()
        moved = [k for k in CLIENT_READ_ONLY if k in changes and changes[k] != current.get(k)]
        if moved and "admin" not in p.scopes:
            raise Refusal(403, f"{', '.join(moved)} can only be changed by an admin, on the service's "
                               "Settings page", "not_admin", field=moved[0], fields=moved)
        changes = {k: v for k, v in changes.items() if k not in CLIENT_READ_ONLY or "admin" in p.scopes}
        try:
            saved = ctx.settings.update(changes, check_root=True)
        except SettingsError as e:
            return _settings_error(e)
        return _client_settings(saved)

    # ---- admin ----
    def _admin_settings(settings) -> dict:
        # The settings plus how the export folder is now (DERIVED_FIELDS: dropped when sent back).
        return {**settings.model_dump(), **export_root_state(settings.export_root)}

    @app.get("/api/admin/settings")
    def get_settings(p: Principal = Depends(need("admin"))):
        return _admin_settings(ctx.settings.load())

    @app.put("/api/admin/settings")
    async def put_settings(request: Request, p: Principal = Depends(need("admin"))):
        try:
            changes = await request.json()
        except ValueError:
            raise HTTPException(400, "send the settings as a JSON object")
        if not isinstance(changes, dict):
            raise HTTPException(400, "send the settings as a JSON object")
        try:
            return _admin_settings(ctx.settings.update(changes, check_root=True))
        except SettingsError as e:
            return _settings_error(e)

    @app.post("/api/admin/export-folder/open")
    def open_export_folder(request: Request, p: Principal = Depends(need("admin"))):
        """Show the (saved) export folder in the Finder — on the Mac running the service,
        whoever asks; the answer says so when the asker is elsewhere."""
        root = os.path.realpath(os.path.expanduser(ctx.settings.load().export_root))
        if not os.path.isdir(root):
            raise HTTPException(404, f"the export folder {root} doesn't exist yet (it is made by the first export)")
        try:
            r = subprocess.run([ctx.config.open_bin, root], capture_output=True,  # root is absolute: never an option
                               text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HTTPException(500, f"couldn't run {ctx.config.open_bin}: {e.__class__.__name__}")
        if r.returncode != 0:
            raise HTTPException(500, f"the Finder couldn't open {root}: {(r.stderr or '').strip() or r.returncode}")
        return {"opened": root, "on_this_mac": _is_loopback(request)}

    def _permission_view(refresh: bool = False) -> dict:
        return dict(ctx.permissions.get(refresh=refresh), requesting=ctx.permissions.requesting,
                    last_request=ctx.permissions.last_request)

    @app.get("/api/admin/permission")
    def get_permission(refresh: bool = False, p: Principal = Depends(need("admin"))):
        return _permission_view(refresh)

    @app.post("/api/admin/permission/request")
    def request_permission(body: Optional[PermissionRequest] = None, wait: Optional[bool] = None,
                           p: Principal = Depends(need("admin"))):
        # Waiting (the default, as before 1.7.0) is a sync endpoint, so it waits in the thread pool
        # while macOS shows its dialog. ?wait=false (or {"wait": false}) answers 202 at once; the
        # permission then says requesting: true until macOS answers.
        if wait is None:
            wait = body.wait if body and body.wait is not None else True
        try:
            if not wait:
                ctx.permissions.start_request()
                return JSONResponse(_permission_view(), status_code=202)
            result = ctx.permissions.request()
        except PermissionRequestBusy as e:
            raise Refusal(409, str(e), "busy")
        return {k: result.get(k) for k in ("automation", "full_disk_access", "checked_at")}

    @app.get("/api/admin/users")
    def users(p: Principal = Depends(need("admin"))):
        return {"users": ctx.auth.list_users()}

    @app.post("/api/admin/users", status_code=201)
    def create_user(body: UserCreate, p: Principal = Depends(need("admin"))):
        try:
            return ctx.auth.create_user(body.username, body.password, body.role)
        except AuthError as e:
            _auth_error(e)

    @app.patch("/api/admin/users/{user_id}")
    def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(need("admin"))):
        if not ctx.auth.get_user(user_id):
            raise HTTPException(404, "no such user")
        try:
            if body.role is not None:
                ctx.auth.set_role(user_id, body.role)
            if body.password is not None:
                ctx.auth.set_password(user_id, body.password)
        except AuthError as e:
            _auth_error(e)
        return ctx.auth.public_user(ctx.auth.get_user(user_id))

    @app.delete("/api/admin/users/{user_id}")
    def delete_user(user_id: str, p: Principal = Depends(need("admin"))):
        try:
            ctx.auth.delete_user(user_id)
        except AuthError as e:
            _auth_error(e)
        return {"ok": True}

    @app.get("/api/admin/api-keys")
    def keys(p: Principal = Depends(need("admin"))):
        return {"api_keys": ctx.auth.list_keys()}

    @app.post("/api/admin/api-keys", status_code=201)
    def create_key(body: KeyCreate, p: Principal = Depends(need("admin"))):
        try:
            record, key = ctx.auth.create_key(body.name, body.scopes, body.owner_user_id or p.user_id,
                                              body.expires_at)
        except AuthError as e:
            raise HTTPException(400, str(e))
        return {"api_key": record, "key": key}

    @app.delete("/api/admin/api-keys/{key_id}")
    def delete_key(key_id: str, p: Principal = Depends(need("admin"))):
        if not ctx.auth.delete_key(key_id):
            raise HTTPException(404, "no such API key")
        return {"ok": True}

    # ---- MCP (MCP.md): a key for the MCP server and what to paste into a client ----
    def _mcp_env_file():
        return mcp_client.default_env_file(config.home)

    def _mcp_snippets(read_only: bool = False) -> dict:
        url = config.local_url()
        args = mcp_client.server_args(url=None if url == "http://127.0.0.1:8790" else url,
                                      env_file=None if config.home == default_home() else str(_mcp_env_file()),
                                      read_only=read_only)
        return mcp_client.snippets(mcp_client.DEFAULT_SERVER_NAME, args)

    @app.get("/api/admin/mcp")
    def mcp_state(p: Principal = Depends(need("admin"))):
        path = _mcp_env_file()
        key = mcp_client.read_env_key(path)
        record = ctx.auth.key_record(key) if key else None
        return {"env_file": str(path), "env_file_present": path.exists(), "key": record,
                "key_problem": None if record else ("no key yet" if not key else
                                                    "the key in the file has been revoked or has expired"),
                "url": config.local_url(), "clients": _mcp_snippets()}

    @app.post("/api/admin/mcp", status_code=201)
    def mcp_key(body: McpKeyCreate, request: Request, p: Principal = Depends(need("admin"))):
        scopes = sorted(set(body.scopes) | {"read"}, key=["read", "run", "write"].index)
        try:
            record, key = ctx.auth.create_key(body.name, scopes, p.user_id, body.expires_at)
        except AuthError as e:
            raise HTTPException(400, str(e))
        out = {"api_key": record}
        if body.keep == "show":
            origin = str(request.base_url).rstrip("/")
            out.update(key=key, remote_setup=f"./notes-exporter mcp setup --url {origin} --key-stdin",
                       clients=_mcp_snippets(body.read_only))
            return out
        from .envfile import write_env_var
        path = _mcp_env_file()
        try:
            write_env_var(str(path), mcp_client.KEY_VAR, key)
        except (OSError, ValueError) as e:
            ctx.auth.delete_key(record["id"])
            raise HTTPException(500, f"couldn't write {path} ({e.__class__.__name__}); the key was not kept")
        # The file holds one key: the older ones of this name (this admin's) are revoked, so running it
        # again rotates the key.
        old = [k for k in ctx.auth.list_keys()
               if k["name"] == record["name"] and k["owner_user_id"] == p.user_id and k["id"] != record["id"]]
        for k in old:
            ctx.auth.delete_key(k["id"])
        out.update(env_file=str(path), revoked=[k["prefix"] for k in old], clients=_mcp_snippets(body.read_only))
        return out

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unknown(rest: str):
        raise HTTPException(404, "no such endpoint")

    # ---- web UI ----
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/approvals", include_in_schema=False)
    def approvals_page():
        return index()

    @app.get("/login-link", include_in_schema=False)
    def login_link_page():
        # The token arrives in the URL's fragment, which only link.js reads (and then removes).
        return FileResponse(WEB_DIR / "link.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app


def _http_date(ts: float) -> str:
    from email.utils import formatdate
    return formatdate(ts, usegmt=True)
