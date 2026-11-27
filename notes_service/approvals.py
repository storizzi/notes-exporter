"""The approval list (SERVICE-API.md "The approval list"): writes held instead of made.

A write that trips one of the admin's rules (``write_hold_*``, checked by ``writes.py``) is
kept here — what it would do, the note's text before and the Markdown after, who asked —
until someone with the ``approve`` scope approves it (then it is made the normal way:
backup, conflict checks against the base it was asked on) or rejects it (it is dropped; the
client keeps its own copy).

One JSON file per held write under ``approvals/`` in the state directory (mode 0600: it
holds note text, as the export folder does)."""

import difflib
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

from .config import Config

KINDS = ("update", "create", "delete")
STATUSES = ("pending", "stale")
# More held writes than this and new ones are refused (429), so a flood can't fill the disk.
MAX_PENDING = 1000
_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---- measuring a change ----
class _Text(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_text(html: str) -> str:
    p = _Text()
    p.feed(html or "")
    return "".join(p.parts)


def line_count(text: str) -> int:
    return sum(1 for line in (text or "").splitlines() if line.strip())


def change_percent(before: str, after: str) -> float:
    """How much of the text changed, 0-100: one minus difflib's similarity of the words."""
    a, b = (before or "").split(), (after or "").split()
    if not a and not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return round((1 - ratio) * 100, 1)


def unified_diff(before: str, after: str, name: str = "note") -> str:
    return "".join(difflib.unified_diff((before or "").splitlines(keepends=True),
                                        (after or "").splitlines(keepends=True),
                                        fromfile=f"{name} (now)", tofile=f"{name} (requested)"))


# ---- the store ----
class ApprovalStore:
    def __init__(self, config: Config, clock=_now):
        self.config = config
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def folder(self) -> Path:
        return self.config.home / "approvals"

    def _path(self, approval_id: str) -> Optional[Path]:
        if not _ID.match(approval_id or ""):
            return None
        return self.folder / f"{approval_id}.json"

    def _write(self, item: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.folder, 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=str(self.folder), prefix=".approval.", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.folder / f"{item['id']}.json")

    def add(self, *, kind: str, note_id: Optional[str], account: str, folder_path: List[str], title: str,
            base: Optional[str], before: Optional[str], after: Optional[str], request: dict, client: dict,
            rule: dict, change: Optional[float]) -> dict:
        item = {"id": secrets.token_urlsafe(12), "kind": kind, "status": "pending", "note_id": note_id,
                "account": account, "folder_path": list(folder_path or []), "title": title, "base": base,
                "before": before, "after": after, "request": request, "client": client,
                "reason": rule["reason"], "rule": rule, "change_percent": change,
                "created_at": self._clock().isoformat(), "stale_reason": None, "tries": 0}
        with self._lock:
            self._write(item)
        return item

    def get(self, approval_id: str) -> Optional[dict]:
        path = self._path(approval_id)
        if not path or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def update(self, item: dict) -> None:
        with self._lock:
            if self._path(item["id"]) and (self.folder / f"{item['id']}.json").exists():
                self._write(item)

    def remove(self, approval_id: str) -> bool:
        path = self._path(approval_id)
        with self._lock:
            try:
                path.unlink()
                return True
            except (OSError, AttributeError):
                return False

    def all(self, max_age_days: int = 0) -> List[dict]:
        """Every held write, oldest first; older than ``max_age_days`` (when set) are dropped."""
        out = []
        if not self.folder.is_dir():
            return out
        cutoff = self._clock() - timedelta(days=max_age_days) if max_age_days else None
        for path in self.folder.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if cutoff:
                try:
                    created = datetime.fromisoformat(item.get("created_at"))
                except (TypeError, ValueError):
                    created = None
                if created and created < cutoff:
                    self.remove(item.get("id", ""))
                    continue
            out.append(item)
        return sorted(out, key=lambda i: (i.get("created_at") or "", i.get("id")))

    def count(self) -> int:
        return len(list(self.folder.glob("*.json"))) if self.folder.is_dir() else 0


def summary(item: dict) -> dict:
    """A held write without its texts (the list)."""
    return {k: item.get(k) for k in ("id", "kind", "status", "note_id", "account", "folder_path", "title",
                                     "base", "reason", "rule", "change_percent", "created_at",
                                     "stale_reason", "client")} | {
        "before_lines": line_count(item.get("before") or ""), "after_lines": line_count(item.get("after") or "")}


def detail(item: dict) -> dict:
    name = item.get("title") or "note"
    return summary(item) | {"before": item.get("before"), "after": item.get("after"),
                            "diff": unified_diff(item.get("before") or "", item.get("after") or "", name),
                            "request": {k: v for k, v in (item.get("request") or {}).items() if k != "markdown"}}
