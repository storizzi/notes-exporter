"""``notes-exporter mcp serve``: a Model Context Protocol server on stdio.

It lets an AI assistant (Claude Code, Claude Desktop, any MCP client) browse,
search and read the exported notes, follow and start exports, and (only with
the ``write`` scope, and only while the admin allows writes) change or create
notes. It is a client of the running service's HTTP API, authenticated with an
API key, so every fence the service has (scopes, ``allow_writes``, conflict
checks, one run at a time, locked notes) applies to it unchanged. It never
reads Apple Notes or the export folder itself.

Standard library only. JSON-RPC 2.0, one message per line on stdin / stdout;
anything else this process prints goes to stderr.

Configuration (command line first, then environment):

* ``--url`` / ``NOTES_EXPORTER_URL``: the service (default: this Mac's, from
  ``NOTES_SERVICE_PORT``, normally ``http://127.0.0.1:8790``).
* the key: ``NOTES_EXPORTER_API_KEY``, else ``NOTES_EXPORTER_API_KEY=`` in the env
  file ``--env-file`` / ``NOTES_EXPORTER_MCP_ENV_FILE`` (default
  ``<state dir>/mcp.env``, written by ``notes-exporter mcp setup``).
* ``--read-only`` / ``NOTES_EXPORTER_MCP_READ_ONLY=true``: offer only the
  reading tools, whatever the key's scopes.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

from . import __version__
from .mcp_client import ENV_FILE_VAR, KEY_VAR, URL_VAR, read_env_key

SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "notes-exporter"
DEFAULT_MAX_CHARS = 40000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
TEXT_CACHE_BYTES = 64 * 1024 * 1024
SCOPES_CACHE_SECONDS = 30

INSTRUCTIONS = """\
Apple Notes, as exported by notes-exporter on the user's Mac.
- A note's identity is its `id` (x-coredata://…/ICNote/p…); pass it exactly as given.
- Start with `search_notes` (words in titles, folders, tags and text) or `list_notes` /
  `list_folders`, then `read_note` for the text.
- The export is a copy made by the last export run: `notes_status` says when that was;
  `start_export` refreshes it (incremental by default, it takes a little while).
- Writing (`update_note`, `create_note`, `delete_note`) changes the user's real Apple Notes.
  Only do it when the user asked for that change. `update_note` replaces the whole note: read
  it first and pass the `modified` you read as `base_modified`. When the service reports a
  conflict, losses or a limit, tell the user instead of forcing it. A write answered
  `held: true` is waiting on the service's approval list: nothing has changed yet, don't send
  it again. Never approve your own held writes unless the user explicitly says so.
"""


class ApiError(Exception):
    def __init__(self, status: int, detail, body=None):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail, self.body = status, detail, body or {}


class Unreachable(Exception):
    pass


class Api:
    """A small client for the service's HTTP API (SERVICE-API.md)."""

    def __init__(self, base_url: str, key: Optional[str], timeout: float = 60.0,
                 opener: Optional[Callable] = None):
        self.base = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def call(self, method: str, path: str, params: Optional[dict] = None, body=None,
             headers: Optional[dict] = None, timeout: Optional[float] = None):
        """(status, headers, bytes). Raises ApiError for an error status, Unreachable without a service."""
        url = self.base + path
        if params:
            q = {k: ("true" if v is True else "false" if v is False else v)
                 for k, v in params.items() if v is not None}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        h = {"Accept": "application/json", "User-Agent": f"notes-exporter-mcp/{__version__}"}
        h.update(headers or {})
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with self._open(req, timeout=timeout or self.timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
            if e.code == 304:
                return 304, hdrs, b""
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {"detail": raw.decode("utf-8", "replace")[:500]}
            detail = parsed.get("detail") if isinstance(parsed, dict) else parsed
            raise ApiError(e.code, detail, parsed if isinstance(parsed, dict) else {})
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise Unreachable(f"the notes-exporter service isn't answering at {self.base} ({reason}). "
                              "Start it: notes-exporter service install (or notes-exporter serve).")

    def json(self, method: str, path: str, **kw):
        _, _, data = self.call(method, path, **kw)
        return json.loads(data) if data else None


def note_path(note_id: str) -> str:
    return "/api/notes/" + urllib.parse.quote(note_id, safe="")


def file_path(rel: str) -> str:
    return "/api/files/" + urllib.parse.quote(rel, safe="/")


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote",
             "ul", "ol", "table", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    p.close()
    text = "".join(p.out)
    text = re.sub(r"[ \t\xa0]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _folder(note: dict) -> str:
    return "/".join(note.get("folder_path") or [])


def compact(note: dict) -> dict:
    """What a listing needs to know about a note (the manifest entry is much bigger)."""
    return {
        "id": note.get("id"), "title": note.get("title"), "account": note.get("account"),
        "folder": _folder(note), "created": note.get("created"), "modified": note.get("modified"),
        "tags": note.get("tags") or [], "locked": bool(note.get("locked")),
        "formats": sorted((note.get("outputs") or {}).keys()),
        "attachments": len(note.get("attachments") or []),
    }


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _in_folder(note: dict, folder: Optional[str]) -> bool:
    if not folder:
        return True
    want = [p for p in folder.strip("/").split("/") if p]
    path = list(note.get("folder_path") or [])
    return [p.lower() for p in path[:len(want)]] == [p.lower() for p in want]


def _in_account(note: dict, account: Optional[str]) -> bool:
    if not account:
        return True
    a = account.lower()
    return a in ((note.get("account") or "").lower(), (note.get("account_id") or "").lower())


TOOLS: List[dict] = []


def tool(name: str, scope: str, description: str, properties: Optional[dict] = None,
         required: Optional[List[str]] = None, read_only: bool = True, destructive: bool = False,
         idempotent: bool = True, title: Optional[str] = None):
    def register(fn):
        TOOLS.append({
            "name": name, "scope": scope, "handler": fn,
            "spec": {
                "name": name, "title": title or name.replace("_", " ").capitalize(),
                "description": description,
                "inputSchema": {"type": "object", "properties": properties or {},
                                "required": required or [], "additionalProperties": False},
                "annotations": {"readOnlyHint": read_only, "destructiveHint": destructive,
                                "idempotentHint": idempotent, "openWorldHint": False},
            },
        })
        return fn
    return register


class ToolError(Exception):
    """A tool failed in a way the model should read (isError: true), not a protocol error."""

    def __init__(self, message: str, data: Optional[dict] = None):
        super().__init__(message)
        self.data = data


class NotesMcp:
    def __init__(self, api: Api, read_only: bool = False, clock=time.monotonic):
        self.api = api
        self.read_only = read_only
        self.clock = clock
        self._manifest = None
        self._etag = None
        self._scopes = None
        self._scopes_at = 0.0
        self._text: Dict[str, str] = {}
        self._text_bytes = 0

    # ---- what the key may do ----
    def scopes(self) -> set:
        now = self.clock()
        if self._scopes is None or now - self._scopes_at > SCOPES_CACHE_SECONDS:
            try:
                self._scopes = set(self.api.json("GET", "/api/auth/me").get("scopes", []))
            except (ApiError, Unreachable):
                self._scopes = None
                return {"read"}          # offer the reading tools; they explain what is wrong
            self._scopes_at = now
        return self._scopes

    def tools(self) -> List[dict]:
        allowed = self.scopes()
        if self.read_only:
            allowed = allowed & {"read"}
        return [t for t in TOOLS if t["scope"] in allowed]

    # ---- the export ----
    def manifest(self) -> dict:
        headers = {"If-None-Match": self._etag} if self._etag and self._manifest is not None else None
        try:
            status, hdrs, data = self.api.call("GET", "/api/manifest", headers=headers)
        except ApiError as e:
            if e.status == 404:
                raise ToolError("There is no export yet: run start_export (or wait for the scheduled run).")
            raise
        if status != 304:
            self._manifest = json.loads(data)
            self._etag = hdrs.get("etag")
        return self._manifest

    def notes(self) -> List[dict]:
        return list(self.manifest().get("notes", []))

    def find_note(self, note_id: str) -> dict:
        for n in self.notes():
            if n.get("id") == note_id:
                return n
        try:
            entry = self.api.json("GET", note_path(note_id))
        except ApiError as e:
            if e.status == 404:
                raise ToolError(f"No note with id {note_id!r} in the export. Find ids with search_notes or list_notes.")
            raise
        if entry.get("deleted"):
            raise ToolError(f"That note was deleted in Notes (last seen as {entry.get('title')!r}).")
        return entry

    def file_bytes(self, rel: str) -> bytes:
        return self.api.call("GET", file_path(rel))[2]

    def note_text(self, note: dict, fmt: str = "auto") -> Tuple[str, str]:
        """(format used, text) of a note's exported content."""
        outputs = note.get("outputs") or {}
        order = {"auto": ["md", "text", "html"], "markdown": ["md"], "md": ["md"], "text": ["text"],
                 "html": ["html"]}.get(fmt)
        if order is None:
            raise ToolError("format must be auto, markdown, text or html")
        for f in order:
            out = outputs.get(f)
            if not out or not out.get("path"):
                continue
            key = out.get("sha256") or f"{out['path']}:{out.get('bytes')}"
            text = self._text.get(key) if fmt == "auto" else None
            if text is None:
                raw = self.file_bytes(out["path"]).decode("utf-8", "replace")
                text = html_to_text(raw) if (f == "html" and fmt == "auto") else raw
                if fmt == "auto":
                    self._remember(key, text)
            return f, text
        have = ", ".join(sorted(outputs)) or "none"
        raise ToolError(f"This note has no {fmt} output in the export (it has: {have}). "
                        "Add the format in the service's settings, or use format auto.")

    def _remember(self, key: str, text: str) -> None:
        size = len(text)
        if size > TEXT_CACHE_BYTES // 4:
            return
        while self._text and self._text_bytes + size > TEXT_CACHE_BYTES:
            old = next(iter(self._text))
            self._text_bytes -= len(self._text.pop(old))
        self._text[key] = text
        self._text_bytes += size

    # ---- MCP ----
    def handle(self, msg: dict) -> Optional[dict]:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            if isinstance(msg, dict) and "id" in msg and "method" not in msg:
                return None          # a response to something we never ask: ignore
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method, mid, params = msg["method"], msg.get("id"), msg.get("params") or {}
        is_notification = "id" not in msg
        try:
            if method == "initialize":
                result = self.initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t["spec"] for t in self.tools()]}
            elif method == "tools/call":
                result = self.call_tool(params)
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            elif method.startswith("notifications/"):
                return None
            else:
                return None if is_notification else _error(mid, -32601, f"method not found: {method}")
        except _RpcError as e:
            return None if is_notification else _error(mid, e.code, str(e))
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}

    def initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {"protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "title": "Apple Notes (notes-exporter)",
                               "version": __version__},
                "instructions": INSTRUCTIONS}

    def call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        entry = next((t for t in TOOLS if t["name"] == name), None)
        if entry is None:
            raise _RpcError(-32602, f"unknown tool: {name}")
        if not isinstance(args, dict):
            raise _RpcError(-32602, "arguments must be an object")
        if entry not in self.tools():
            return _tool_error(f"{name} isn't available: it needs the {entry['scope']!r} scope"
                               + (" and this server runs --read-only" if self.read_only else
                                  ", which this server's API key doesn't have (notes-exporter mcp setup --write, or tick it on the web page's MCP tab)"))
        unknown = set(args) - set(entry["spec"]["inputSchema"]["properties"])
        if unknown:
            return _tool_error(f"unknown argument(s): {', '.join(sorted(unknown))}")
        missing = [k for k in entry["spec"]["inputSchema"]["required"] if args.get(k) in (None, "")]
        if missing:
            return _tool_error(f"missing argument(s): {', '.join(missing)}")
        try:
            out = entry["handler"](self, **args)
        except ToolError as e:
            return _tool_error(str(e), e.data)
        except Unreachable as e:
            return _tool_error(str(e))
        except ApiError as e:
            return _tool_error(_explain(e), e.body if isinstance(e.body, dict) else None)
        except (TypeError, ValueError) as e:
            return _tool_error(f"bad arguments: {e}")
        if isinstance(out, dict) and "content" in out:
            return out
        return {"content": [{"type": "text", "text": out if isinstance(out, str) else _dump(out)}],
                "isError": False}


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False)


def _tool_error(message: str, data: Optional[dict] = None) -> dict:
    text = message if not data else message + "\n" + _dump(data)
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _explain(e: ApiError) -> str:
    if e.status == 401:
        return ("The service refused the API key (revoked, expired or missing). Run "
                "notes-exporter mcp setup again, or create one on the web page's MCP tab.")
    if e.status == 403:
        return f"Not allowed: {e.detail}"
    return f"The service answered {e.status}: {e.detail}"


def _limit(value, default: int, top: int) -> int:
    n = default if value is None else int(value)
    return max(1, min(top, n))


def _clip(text: str, max_chars: Optional[int]) -> str:
    limit = _limit(max_chars, DEFAULT_MAX_CHARS, 500000)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[… cut at {limit} of {len(text)} characters; ask again with a larger max_chars]"


# ---------------------------------------------------------------- read tools
@tool("notes_status", "read",
      "The notes-exporter service: when the export last ran and how it went, whether one is running, the "
      "next scheduled run, how many notes the export holds, its formats, whether writing notes is allowed, "
      "the version, and what this server's key may do.",
      title="Export status")
def t_status(s: NotesMcp):
    st = s.api.json("GET", "/api/status")
    out = {"running_run_id": st.get("running_run_id"), "next_run_at": st.get("next_run_at"),
           "schedule": st.get("schedule"), "formats": st.get("formats"),
           "export_ok": st.get("export_root_ok"), "export_problem": st.get("export_root_problem"),
           "notes_automation": (st.get("permission") or {}).get("automation"),
           "version": st.get("version")}
    last = st.get("last_run")
    if last:
        out["last_run"] = {k: last.get(k) for k in ("id", "status", "mode", "finished_at", "counts", "message")}
    try:
        m = s.manifest()
        run = m.get("run") or {}
        out["export"] = {"notes": len(m.get("notes", [])), "sequence": run.get("sequence"),
                         "finished_at": run.get("finished_at"),
                         "accounts": [a.get("name") for a in m.get("accounts", [])]}
    except ToolError as e:
        out["export"] = str(e)
    try:
        w = s.api.json("GET", "/api/writes")
        out["writes"] = {"allowed_by_admin": w.get("allowed"), "this_key_can_write": w.get("can_write")}
    except ApiError:
        pass
    out["this_key_scopes"] = sorted(s.scopes())
    if s.read_only:
        out["this_server"] = "read-only"
    return out


@tool("list_folders", "read",
      "Every account and folder in the export, with how many notes each holds (directly and with its subfolders).",
      title="List folders")
def t_folders(s: NotesMcp):
    counts: Dict[tuple, List[int]] = {}
    for n in s.notes():
        path = list(n.get("folder_path") or [])
        acct = n.get("account") or ""
        for i in range(1, len(path) + 1):
            c = counts.setdefault((acct, "/".join(path[:i])), [0, 0])
            c[1] += 1
            if i == len(path):
                c[0] += 1
    return {"folders": [{"account": a, "folder": f, "notes": c[0], "notes_with_subfolders": c[1]}
                        for (a, f), c in sorted(counts.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower()))]}


@tool("list_notes", "read",
      "Notes in the export, newest first, optionally only one account, one folder (and its subfolders, "
      "e.g. 'Recipes/Baking'), modified after a date, or changed since an export sequence. Gives ids, "
      "titles, folders and dates; read the text with read_note.",
      {"account": {"type": "string", "description": "account name or id"},
       "folder": {"type": "string", "description": "folder path, '/' between levels"},
       "modified_after": {"type": "string", "description": "ISO date, e.g. 2026-11-01"},
       "changed_since_sequence": {"type": "integer", "description": "only notes changed by a later export run"},
       "title_contains": {"type": "string"},
       "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
       "offset": {"type": "integer", "minimum": 0, "default": 0}},
      title="List notes")
def t_list(s: NotesMcp, account=None, folder=None, modified_after=None, changed_since_sequence=None,
           title_contains=None, limit=None, offset=None):
    after = _parse_date(modified_after) if modified_after else None
    if modified_after and after is None:
        raise ToolError("modified_after must be an ISO date such as 2026-11-01")
    notes = []
    for n in s.notes():
        if not (_in_account(n, account) and _in_folder(n, folder)):
            continue
        if after and ((_parse_date(n.get("modified")) or datetime.min.replace(tzinfo=timezone.utc)) <= after):
            continue
        if changed_since_sequence is not None and int(n.get("changed_in_run") or 0) <= int(changed_since_sequence):
            continue
        if title_contains and title_contains.lower() not in (n.get("title") or "").lower():
            continue
        notes.append(n)
    notes.sort(key=lambda n: n.get("modified") or "", reverse=True)
    start = max(0, int(offset or 0))
    page = notes[start:start + _limit(limit, 50, 500)]
    return {"total": len(notes), "offset": start, "notes": [compact(n) for n in page]}


@tool("search_notes", "read",
      "Find notes by words: every word must appear in the note's title, folder, tags or text "
      "(case-insensitive; put a phrase in double quotes). Best matches first, with a snippet.",
      {"query": {"type": "string"},
       "account": {"type": "string"}, "folder": {"type": "string"},
       "titles_only": {"type": "boolean", "default": False,
                       "description": "search titles, folders and tags only (faster)"},
       "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
      required=["query"], title="Search notes")
def t_search(s: NotesMcp, query, account=None, folder=None, titles_only=False, limit=None):
    terms = [t.lower() for pair in re.findall(r'"([^"]+)"|(\S+)', query) for t in pair if t]
    if not terms:
        raise ToolError("query is empty")
    hits = []
    skipped = 0
    for n in s.notes():
        if not (_in_account(n, account) and _in_folder(n, folder)):
            continue
        title = (n.get("title") or "").lower()
        meta = " ".join([title, _folder(n).lower(), " ".join(n.get("tags") or []).lower()])
        body = ""
        if not titles_only and not all(t in meta for t in terms):
            try:
                body = s.note_text(n)[1].lower() if not n.get("locked") else ""
            except (ToolError, ApiError):
                skipped += 1
        hay = meta + "\n" + body
        if not all(t in hay for t in terms):
            continue
        score = sum(3 for t in terms if t in title) + sum(body.count(t) for t in terms)
        hit = compact(n)
        if body:
            i = min((body.find(t) for t in terms if t in body), default=-1)
            if i >= 0:
                snippet = body[max(0, i - 80): i + 160].replace("\n", " ").strip()
                hit["snippet"] = ("…" if i > 80 else "") + snippet + "…"
        hits.append((score, n.get("modified") or "", hit))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    result = {"query": query, "total": len(hits), "notes": [h[2] for h in hits[:_limit(limit, 20, 100)]]}
    if skipped:
        result["unreadable"] = skipped
    return result


@tool("read_note", "read",
      "A note's text and details (folder, dates, tags, attachments). format: auto (Markdown if exported, "
      "else plain text, else the HTML as text), markdown, text or html. `modified` is what update_note "
      "needs as base_modified.",
      {"id": {"type": "string", "description": "the note's id"},
       "format": {"type": "string", "enum": ["auto", "markdown", "text", "html"], "default": "auto"},
       "max_chars": {"type": "integer", "minimum": 1, "default": DEFAULT_MAX_CHARS}},
      required=["id"], title="Read a note")
def t_read(s: NotesMcp, id, format="auto", max_chars=None):
    n = s.find_note(id)
    if n.get("locked"):
        raise ToolError("That note is locked (password-protected) in Notes; its text isn't exported.")
    used, text = s.note_text(n, format or "auto")
    meta = compact(n)
    meta.update(format=used, shared=n.get("shared"), pinned=n.get("pinned"),
                attachments=[{"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"),
                              "media_type": a.get("media_type"), "bytes": a.get("bytes")}
                             for a in n.get("attachments") or []])
    return {"content": [{"type": "text", "text": _dump(meta)},
                        {"type": "text", "text": _clip(text, max_chars)}], "isError": False}


@tool("get_attachment", "read",
      "One attachment of a note (see read_note's attachments): a picture comes back as an image (up to 4 MB), "
      "a text file as text, anything else as its details.",
      {"note_id": {"type": "string"},
       "attachment": {"type": "string", "description": "the attachment's id or name"}},
      required=["note_id", "attachment"], title="Get an attachment")
def t_attachment(s: NotesMcp, note_id, attachment):
    n = s.find_note(note_id)
    att = next((a for a in n.get("attachments") or [] if attachment in (a.get("id"), a.get("name"))), None)
    if not att:
        names = ", ".join(a.get("name") or "?" for a in n.get("attachments") or []) or "none"
        raise ToolError(f"No attachment {attachment!r} in that note (it has: {names}).")
    info = {k: att.get(k) for k in ("id", "name", "kind", "media_type", "bytes")}
    mt = att.get("media_type") or ""
    size = int(att.get("bytes") or 0)
    if mt.startswith("image/") and size <= MAX_IMAGE_BYTES:
        data = s.file_bytes(att["path"])
        return {"content": [{"type": "text", "text": _dump(info)},
                            {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mt}],
                "isError": False}
    if (mt.startswith("text/") or mt in ("application/json", "application/xml")) and size <= 1024 * 1024:
        text = s.file_bytes(att["path"]).decode("utf-8", "replace")
        return {"content": [{"type": "text", "text": _dump(info)}, {"type": "text", "text": text}], "isError": False}
    info["note"] = "Not returned: too big, or not a picture or text."
    return info


@tool("list_runs", "read", "Recent export runs, newest first: status, trigger, counts, when.",
      {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}}, title="List export runs")
def t_runs(s: NotesMcp, limit=None):
    data = s.api.json("GET", "/api/runs", params={"limit": _limit(limit, 10, 100)})
    keep = ("id", "status", "trigger", "mode", "folders", "created_at", "finished_at", "counts", "message")
    return {"total": data.get("total"), "runs": [{k: r.get(k) for k in keep} for r in data.get("runs", [])]}


@tool("get_run", "read",
      "One export run: its status and progress, and optionally the last lines of its log.",
      {"run_id": {"type": "string"},
       "log_lines": {"type": "integer", "minimum": 0, "maximum": 500, "default": 0}},
      required=["run_id"], title="Get an export run")
def t_run(s: NotesMcp, run_id, log_lines=0):
    rid = urllib.parse.quote(run_id, safe="")
    run = s.api.json("GET", f"/api/runs/{rid}")
    if log_lines:
        text = s.api.call("GET", f"/api/runs/{rid}/log")[2].decode("utf-8", "replace")
        run["log_tail"] = "\n".join(text.splitlines()[-int(log_lines):])
    return run


# ---------------------------------------------------------------- run tools
@tool("start_export", "run",
      "Start an export run so the export catches up with Notes: incremental (changed notes, the default) or "
      "full (every note), optionally only some folders or accounts. Returns at once; follow it with get_run. "
      "Only one run at a time.",
      {"mode": {"type": "string", "enum": ["incremental", "full"], "default": "incremental"},
       "folders": {"type": "array", "items": {"type": "string"}},
       "accounts": {"type": "array", "items": {"type": "string"}},
       "formats": {"type": "array", "items": {"type": "string",
                                              "enum": ["html", "md", "pdf", "docx", "epub", "text"]},
                   "description": "extra formats for this run, on top of the settings'"}},
      read_only=False, idempotent=False, title="Start an export")
def t_start(s: NotesMcp, mode="incremental", folders=None, accounts=None, formats=None):
    body = {"mode": mode or "incremental", "trigger": "api"}
    for k, v in (("folders", folders), ("accounts", accounts), ("formats", formats)):
        if v:
            body[k] = list(v)
    try:
        run = s.api.json("POST", "/api/runs", body=body)["run"]
    except ApiError as e:
        if e.status == 409:
            raise ToolError(f"An export is already running ({e.body.get('running_run_id')}); follow it with get_run.")
        raise
    return {"started": True, "run": {k: run.get(k) for k in ("id", "status", "mode", "folders", "accounts", "formats")}}


@tool("cancel_export", "run", "Stop an export run that is in progress.",
      {"run_id": {"type": "string"}}, required=["run_id"], read_only=False, destructive=False,
      title="Cancel an export")
def t_cancel(s: NotesMcp, run_id):
    run = s.api.json("POST", f"/api/runs/{urllib.parse.quote(run_id, safe='')}/cancel")["run"]
    return {"id": run.get("id"), "status": run.get("status")}


# ---------------------------------------------------------------- write tools
def _write_refused(e: ApiError) -> ToolError:
    body = e.body if isinstance(e.body, dict) else {}
    reason = body.get("reason")
    words = {
        "off": "Writing notes is turned off: the admin allows it in the service's Settings (Allow clients to write notes).",
        "running": "An export is running; try again when it has finished.",
        "busy": "Another write is in progress; try again in a moment.",
        "export": "The note changed since you read it (a newer export). Read it again and redo the change.",
        "notes": "The note was changed in Notes after the last export. Read it again (after start_export) "
                 "and redo the change, or ask the user whether to overwrite it (force).",
        "losses": "Rewriting this note would lose things Notes can't get back from Markdown (listed below). "
                  "Tell the user; only with their agreement send accept_losses: true.",
        "permission": "The service isn't allowed to control Notes (System Settings → Privacy & Security → Automation).",
        "locked": "The note is locked in Notes; it can't be changed or deleted by a script.",
        "deleted": "The note was already deleted in Notes.",
        "backup_failed": "The service couldn't copy the note into its backup folder first, so it didn't change it. "
                         "Tell the user; don't retry without backup unless they say so.",
        "backup_required": "The admin requires a backup before every change: leave backup at its default.",
        "write_limit": "Too many changes to Notes for now (the admin's limit against mass changes). Stop and tell "
                       "the user; it opens again in retry_after seconds.",
        "approvals_full": "The approval list is full; the user must approve or reject held writes first.",
    }
    return ToolError(words.get(reason, _explain(e)), body)


def _held(r: dict) -> Optional[dict]:
    """A 202: the service held the write on its approval list — nothing changed yet."""
    if not (isinstance(r, dict) and r.get("held")):
        return None
    return {"written": False, "held": True, "approval_id": r.get("approval_id"), "reason": r.get("reason"),
            "detail": r.get("detail"),
            "message": "Held for approval: nothing has changed in Apple Notes yet. Tell the user it is waiting "
                       "on the notes-exporter approval list (the service's web page, Approvals tab). Don't "
                       "send it again."}


def _write(s: "NotesMcp", method: str, path: str, **kw) -> dict:
    try:
        return s.api.json(method, path, timeout=300, **kw)
    except ApiError as e:
        if e.status in (403, 409, 429, 502, 503):
            raise _write_refused(e)
        raise


@tool("update_note", "write",
      "Replace a note's whole content in Apple Notes with Markdown (a new title renames it). Read it first "
      "(read_note, format markdown) and pass its `modified` as base_modified. The service first copies the "
      "note as it is into its backup folder in Notes. Pictures linked inside the export stay; other attachments "
      "and checklist ticks would be lost, which the service reports first. A big change, or many changes, may "
      "be held for the user's approval instead (held: true). Then the folder is exported again.",
      {"id": {"type": "string"}, "markdown": {"type": "string"},
       "base_modified": {"type": "string", "description": "the note's `modified` when you read it"},
       "title": {"type": "string", "description": "a new title (default: keep, or the first heading)"},
       "force": {"type": "boolean", "default": False,
                 "description": "overwrite even if the note changed since — only when the user said so"},
       "accept_losses": {"type": "boolean", "default": False,
                         "description": "the user agreed to lose the attachments / ticks reported"}},
      required=["id", "markdown", "base_modified"], read_only=False, destructive=True, idempotent=False,
      title="Change a note")
def t_update(s: NotesMcp, id, markdown, base_modified, title=None, force=False, accept_losses=False):
    body = {"markdown": markdown, "base_modified": base_modified, "force": bool(force),
            "accept_losses": bool(accept_losses)}
    if title:
        body["title"] = title
    r = _write(s, "PUT", note_path(id), body=body)
    return _held(r) or {"written": True, "note_id": r.get("note_id"), "modified": r.get("modified"),
                        "backup_note_id": r.get("backup_note_id"), "export_run": (r.get("run") or {}).get("id")}


@tool("create_note", "write",
      "Make a new note in Apple Notes from Markdown, in a folder the export already holds notes in. "
      "It may be held for the user's approval instead (held: true). Then that folder is exported again.",
      {"account": {"type": "string", "description": "account name, e.g. iCloud"},
       "folder": {"type": "string", "description": "folder path, '/' between levels"},
       "markdown": {"type": "string"},
       "title": {"type": "string", "description": "default: the first heading"}},
      required=["account", "folder", "markdown"], read_only=False, destructive=False, idempotent=False,
      title="Create a note")
def t_create(s: NotesMcp, account, folder, markdown, title=None):
    body = {"account": account, "folder_path": [p for p in folder.strip("/").split("/") if p],
            "markdown": markdown}
    if title:
        body["title"] = title
    try:
        r = s.api.json("POST", "/api/notes", body=body, timeout=300)
    except ApiError as e:
        if e.status == 404:
            raise ToolError(f"No folder {folder!r} with notes in account {account!r} in the export (see list_folders).")
        if e.status in (403, 409, 429, 503):
            raise _write_refused(e)
        raise
    return _held(r) or {"created": True, "note_id": r.get("note_id"), "modified": r.get("modified"),
                        "export_run": (r.get("run") or {}).get("id")}


@tool("delete_note", "write",
      "Delete a note in Apple Notes: Notes moves it to Recently Deleted, where it can be recovered for about "
      "30 days. Only when the user asked for that note to be deleted. Read it first and pass its `modified` as "
      "base_modified. It may be held for the user's approval instead (held: true).",
      {"id": {"type": "string"},
       "base_modified": {"type": "string", "description": "the note's `modified` when you read it"},
       "backup": {"type": "boolean", "default": False,
                  "description": "also copy it into the service's backup folder first"}},
      required=["id", "base_modified"], read_only=False, destructive=True, idempotent=False,
      title="Delete a note")
def t_delete(s: NotesMcp, id, base_modified, backup=False):
    params = {"base": base_modified, "backup": "folder" if backup else "none"}
    r = _write(s, "DELETE", note_path(id), params=params)
    return _held(r) or {"deleted": True, "recently_deleted": True, "note_id": r.get("note_id"),
                        "backup_note_id": r.get("backup_note_id"), "export_run": (r.get("run") or {}).get("id")}


@tool("list_held_writes", "write",
      "Writes held on the service's approval list, waiting for the user (with a write key: only yours). "
      "Each has an id, what it would do, to which note, why it was held, and whether it is stale.",
      read_only=True, title="Held writes")
def t_held(s: NotesMcp):
    r = s.api.json("GET", "/api/approvals")
    return {"counts": r.get("counts"), "held": r.get("approvals", [])}


@tool("approve_held_write", "approve",
      "Make a held write in Apple Notes (backup first; refused if the note changed since). ONLY when the user, "
      "having seen the change, explicitly said to approve this one. Never approve your own writes on your own.",
      {"approval_id": {"type": "string"}}, required=["approval_id"], read_only=False, destructive=True,
      idempotent=False, title="Approve a held write")
def t_approve(s: NotesMcp, approval_id):
    try:
        return s.api.json("POST", f"/api/approvals/{urllib.parse.quote(approval_id, safe='')}/approve", timeout=300)
    except ApiError as e:
        if e.status in (403, 409, 429, 502, 503):
            raise _write_refused(e)
        raise


@tool("reject_held_write", "approve",
      "Drop a held write without changing Notes, when the user said so.",
      {"approval_id": {"type": "string"}}, required=["approval_id"], read_only=False, destructive=False,
      idempotent=True, title="Reject a held write")
def t_reject(s: NotesMcp, approval_id):
    return s.api.json("POST", f"/api/approvals/{urllib.parse.quote(approval_id, safe='')}/reject")


# ---------------------------------------------------------------- running it
def resolve(url: Optional[str], env_file: Optional[str], read_only: Optional[bool], environ=None):
    """(base url, key, env file used, read_only) from the arguments and the environment."""
    from .config import Config
    e = os.environ if environ is None else environ
    config = Config.from_env()
    base = url or e.get(URL_VAR) or config.local_url()
    path = env_file or e.get(ENV_FILE_VAR) or str(config.home / "mcp.env")
    key = e.get(KEY_VAR) or read_env_key(path)
    ro = read_only if read_only else str(e.get("NOTES_EXPORTER_MCP_READ_ONLY", "")).lower() in ("1", "true", "yes")
    return base, key, path, ro


def serve(server: NotesMcp, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            replies = [_error(None, -32700, "parse error")]
        else:
            if isinstance(msg, list):
                replies = [r for r in (server.handle(m) for m in msg) if r is not None]
                replies = [replies] if replies else []
            else:
                r = server.handle(msg)
                replies = [r] if r is not None else []
        for r in replies:
            stdout.write(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    return 0


def main(url=None, env_file=None, read_only=False) -> int:
    base, key, path, ro = resolve(url, env_file, read_only)
    protocol_out = sys.stdout.buffer
    sys.stdout = sys.stderr          # nothing but protocol messages on the real stdout
    if not key:
        print(f"notes-exporter mcp: no API key ({KEY_VAR} unset and not in {path}); "
              "run notes-exporter mcp setup. The tools will say so.", file=sys.stderr)
    return serve(NotesMcp(Api(base, key), read_only=ro), sys.stdin.buffer, protocol_out)
