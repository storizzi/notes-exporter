"""The HTTP API (SERVICE-API.md) and the web UI."""

import os
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
from .auth import ROLES, AuthError, AuthStore, LoginLimiter, Principal
from .config import Config
from .exports import ExportReader, PathRefused, content_type, iter_file, parse_range
from .permissions import PermissionChecker
from .runs import RunBusy, RunError, RunManager, RunStore, read_events
from .scheduler import Scheduler
from .settings import RUN_FORMATS, SettingsError, SettingsStore

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


class UserCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "reader"] = "reader"


class UserPatch(BaseModel):
    password: Optional[str] = None
    role: Optional[Literal["admin", "reader"]] = None


class KeyCreate(BaseModel):
    name: str
    scopes: List[Literal["read", "run", "admin"]] = Field(default_factory=lambda: ["read"])
    owner_user_id: Optional[str] = None
    expires_at: Optional[str] = None


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
                raise HTTPException(403, f"this needs the {scope!r} scope")
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
                "macos_version": platform.mac_ver()[0] or None}

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
            "next_run_at": nxt.isoformat(timespec="seconds") if nxt else None,
            "schedule": settings.schedule.model_dump(),
            "export_root": root,
            "export_root_ok": os.path.isdir(root) and os.access(root, os.W_OK),
            "manifest_present": os.path.isfile(os.path.join(root, "manifest.json")),
            "permission": ctx.permissions.get(),
            "formats": settings.formats,
            "epub_books": settings.epub_books,
            "version": __version__,
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

    # ---- admin ----
    @app.get("/api/admin/settings")
    def get_settings(p: Principal = Depends(need("admin"))):
        return ctx.settings.load().model_dump()

    @app.put("/api/admin/settings")
    async def put_settings(request: Request, p: Principal = Depends(need("admin"))):
        try:
            changes = await request.json()
        except ValueError:
            raise HTTPException(400, "send the settings as a JSON object")
        if not isinstance(changes, dict):
            raise HTTPException(400, "send the settings as a JSON object")
        try:
            return ctx.settings.update(changes).model_dump()
        except SettingsError as e:
            raise HTTPException(422, str(e))

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

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unknown(rest: str):
        raise HTTPException(404, "no such endpoint")

    # ---- web UI ----
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app


def _http_date(ts: float) -> str:
    from email.utils import formatdate
    return formatdate(ts, usegmt=True)
