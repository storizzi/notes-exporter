"""Reading an export: the manifest (with ETag), note queries and files.

File paths come from clients, so every one is resolved with realpath and must
stay inside the export root's realpath (a symlink pointing out is refused).
"""

import hashlib
import json
import mimetypes
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

EXTRA_TYPES = {
    ".md": "text/markdown", ".markdown": "text/markdown", ".heic": "image/heic", ".heif": "image/heif",
    ".webp": "image/webp", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".epub": "application/epub+zip", ".ndjson": "application/x-ndjson", ".json": "application/json",
    ".txt": "text/plain", ".html": "text/html", ".htm": "text/html", ".svg": "image/svg+xml",
}


def content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    ctype = EXTRA_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
        ctype += "; charset=utf-8"
    return ctype


class PathRefused(Exception):
    """403: the path leaves the export root."""


@dataclass
class ManifestView:
    raw: bytes
    data: dict
    etag: str
    hashes: Dict[str, Tuple[str, int]]   # relative path -> (sha256, bytes)


class ExportReader:
    def __init__(self, root_getter):
        self._root_getter = root_getter
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[tuple, ManifestView]] = None

    @property
    def root(self) -> Path:
        return Path(self._root_getter())

    def manifest(self) -> Optional[ManifestView]:
        path = self.root / "manifest.json"
        try:
            st = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        key = (str(path), st.st_mtime_ns, st.st_size)
        with self._lock:
            if self._cache and self._cache[0] == key:
                return self._cache[1]
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        hashes: Dict[str, Tuple[str, int]] = {}
        for note in data.get("notes", []):
            for out in (note.get("outputs") or {}).values():
                if isinstance(out, dict) and out.get("path") and out.get("sha256"):
                    hashes[out["path"]] = (out["sha256"], int(out.get("bytes") or -1))
            for att in note.get("attachments") or []:
                if att.get("path") and att.get("sha256"):
                    hashes[att["path"]] = (att["sha256"], int(att.get("bytes") or -1))
        view = ManifestView(raw, data, '"' + hashlib.sha256(raw).hexdigest() + '"', hashes)
        with self._lock:
            self._cache = (key, view)
        return view

    # ---- notes ----
    @staticmethod
    def _folder_matches(path: List[str], folder: str) -> bool:
        joined = "/".join(path or [])
        return joined == folder or joined.startswith(folder.rstrip("/") + "/") or (path and path[-1] == folder)

    def notes(self, view: ManifestView, *, changed_since_sequence: Optional[int] = None,
              account: Optional[str] = None, folder: Optional[str] = None,
              include_deleted: bool = False) -> dict:
        data = view.data
        accounts = {a.get("id"): a.get("name") for a in data.get("accounts", [])}

        def account_ok(entry):
            if not account:
                return True
            return account in (entry.get("account_id"), entry.get("account"), accounts.get(entry.get("account_id")))

        notes = []
        for n in data.get("notes", []):
            if changed_since_sequence is not None and int(n.get("changed_in_run") or 0) <= changed_since_sequence:
                continue
            if not account_ok(n) or (folder and not self._folder_matches(n.get("folder_path"), folder)):
                continue
            notes.append(n)
        deleted = []
        if include_deleted:
            for d in data.get("deleted", []):
                seq = d.get("deleted_in_run")
                if changed_since_sequence is not None and seq is not None and int(seq) <= changed_since_sequence:
                    continue
                if not account_ok(d) or (folder and not self._folder_matches(d.get("folder_path"), folder)):
                    continue
                deleted.append(d)
        return {"sequence": data.get("run", {}).get("sequence"), "notes": notes, "deleted": deleted}

    @staticmethod
    def note(view: ManifestView, note_id: str) -> Optional[dict]:
        for n in view.data.get("notes", []):
            if n.get("id") == note_id:
                return n
        for d in view.data.get("deleted", []):
            if d.get("id") == note_id:
                return dict(d, deleted=True)
        return None

    # ---- files ----
    def resolve(self, rel: str) -> Path:
        if "\0" in rel:
            raise PathRefused("bad path")
        root = os.path.realpath(self.root)
        target = os.path.realpath(os.path.join(root, rel.lstrip("/")))
        if os.path.commonpath([root, target]) != root or target == root:
            raise PathRefused("outside the export")
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise PathRefused("outside the export")
        return Path(target)

    def etag_for(self, rel: str, path: Path, st: os.stat_result) -> str:
        view = None
        try:
            view = self.manifest()
        except (ValueError, OSError):
            pass
        if view:
            known = view.hashes.get(rel)
            if known and known[1] in (-1, st.st_size):
                return f'"sha256:{known[0]}"'
        return f'"{st.st_size:x}-{st.st_mtime_ns:x}"'


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: Optional[str], size: int):
    """(start, end) inclusive, None for the whole file, or 'unsatisfiable'.

    Only single ranges are honoured; a multi-range request gets the whole
    file (RFC 9110 allows ignoring Range).
    """
    if not header:
        return None
    header = header.strip()
    if "," in header:
        return None
    m = _RANGE.match(header)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    first, last = m.group(1), m.group(2)
    if first == "":
        n = int(last)
        if n == 0:
            return "unsatisfiable"
        return max(0, size - n), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or (last and end < start):
        return "unsatisfiable"
    return start, min(end, size - 1)


def iter_file(path: Path, start: int, length: int, chunk: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
