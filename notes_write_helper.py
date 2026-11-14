#!/usr/bin/env python3
"""The service's writer (SERVICE-API.md "Writing notes"): one request as JSON on stdin,
one answer as JSON on stdout. Run by notes_service/writes.py as a subprocess with a clean
environment; nothing else in the project calls it.

Requests::

    {"operation": "modified", "note_id": "x-coredata://…"}
    {"operation": "update", "note_id": "…", "title": "…", "markdown": "…", "base_dir": "…", "root": "…"}
    {"operation": "create", "account": "iCloud", "folder_path": ["Food", "Baking"], "title": "…",
     "markdown": "…", "base_dir": "…", "root": "…"}

Answers ``{"ok": true, "note_id", "modified"}`` (``modified`` aware ISO 8601, as the
manifest has it) or ``{"ok": false, "error", "code"}``.

The Markdown becomes HTML with pandoc; a picture it links is embedded (Notes takes pictures
only inline) when the file is under ``root`` (the export folder) — anything else, a
``..`` path or a link out of the folder, is left as it is, so a note's text can't pull
other files of the Mac into Notes."""

import base64
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCRIPT = HERE / "notes_write.applescript"
OSASCRIPT = os.environ.get("NOTES_WRITE_OSASCRIPT", "osascript")
PANDOC = os.environ.get("NOTES_WRITE_PANDOC", "pandoc")
TIMEOUT = float(os.environ.get("NOTES_WRITE_TIMEOUT_SECONDS", "120"))
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
               "webp": "image/webp", "tiff": "image/tiff", "tif": "image/tiff", "heic": "image/heic"}


class WriteFailed(Exception):
    def __init__(self, message, code="failed"):
        super().__init__(message)
        self.code = code


def markdown_to_html(markdown: str) -> str:
    try:
        r = subprocess.run([PANDOC, "-f", "markdown", "-t", "html"], input=markdown, capture_output=True,
                           text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise WriteFailed("pandoc isn't installed (brew install pandoc)", "pandoc")
    except subprocess.TimeoutExpired:
        raise WriteFailed("pandoc took too long", "pandoc")
    if r.returncode != 0:
        raise WriteFailed(f"pandoc failed: {r.stderr.strip()[:300]}", "pandoc")
    return r.stdout


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def embed_images(html: str, base_dir: str, root: str) -> str:
    """Inline every <img> whose file lies inside ``root`` (realpath)."""
    from bs4 import BeautifulSoup
    if not base_dir or not root:
        return html
    real_root = Path(os.path.realpath(root))
    base = Path(os.path.realpath(base_dir))
    if not _inside(base, real_root):
        return html
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src or src.startswith(("data:", "http:", "https:", "/")) or "://" in src:
            continue
        found = None
        for variant in dict.fromkeys([src, unquote(src)]):
            candidate = Path(os.path.realpath(base / variant))
            if _inside(candidate, real_root) and candidate.is_file():
                found = candidate
                break
        if not found:
            continue
        ext = found.suffix.lower().lstrip(".")
        mime = IMAGE_TYPES.get(ext) or mimetypes.guess_type(found.name)[0]
        if not mime or not mime.startswith("image/"):
            continue
        img["src"] = f"data:{mime};base64,{base64.b64encode(found.read_bytes()).decode('ascii')}"
    return str(soup)


def run_script(args):
    try:
        r = subprocess.run([OSASCRIPT, str(SCRIPT), *args], capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise WriteFailed("osascript isn't available (writing to Notes needs macOS)", "platform")
    except subprocess.TimeoutExpired:
        raise WriteFailed("Notes didn't answer in time", "timeout")
    line = (r.stdout or "").strip().splitlines()[-1:] or [""]
    parts = line[0].split("\t")
    if r.returncode != 0 or parts[0] != "ok" or len(parts) < 3:
        if parts[0] == "error" and len(parts) >= 3:
            num = parts[1]
            code = "permission" if num in ("-1743", "-10004") else "not_found" if num in ("-1728", "-1719") else "failed"
            raise WriteFailed(parts[2] or "Notes refused", code)
        raise WriteFailed((r.stderr or "osascript failed").strip()[:300])
    import tracker_io
    return {"ok": True, "note_id": parts[1], "modified": tracker_io.local_to_aware(parts[2]) or parts[2]}


def handle(req):
    op = req.get("operation")
    if op == "modified":
        return run_script(["modified", str(req["note_id"])])
    if op not in ("update", "create"):
        raise WriteFailed(f"unknown operation {op!r}", "bad_request")
    html = embed_images(markdown_to_html(req.get("markdown") or ""), req.get("base_dir") or "", req.get("root") or "")
    fd, body_path = tempfile.mkstemp(prefix="notes_write_", suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        title = (req.get("title") or "").replace("\n", " ").strip()
        if op == "update":
            return run_script(["update", str(req["note_id"]), title, body_path])
        folders = [str(p) for p in (req.get("folder_path") or []) if str(p)]
        if not folders:
            raise WriteFailed("a new note needs a folder", "bad_request")
        return run_script(["create", str(req.get("account") or ""), title, body_path, *folders])
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
        out = handle(req)
    except WriteFailed as e:
        out = {"ok": False, "error": str(e), "code": e.code}
    except Exception as e:  # noqa: BLE001 - always answer in JSON
        out = {"ok": False, "error": f"{e.__class__.__name__}: {e}", "code": "failed"}
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
