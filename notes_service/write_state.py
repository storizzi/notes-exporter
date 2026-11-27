"""What the write fences remember across restarts (SERVICE-API.md "Writing notes").

``write_state.json`` in the state directory holds:

* ``changes``: when each change to Notes was made (updates, new notes, deletes — not the
  backups the service makes itself), kept for a day, so the mass-change limits
  (``write_max_changes_per_hour`` / ``_per_day``) survive a restart;
* ``backup_folders``: every folder path the service has made backups in
  (``["FunHoard Backups", "Food", "Baking"]``, with its account), so exports leave them out
  (``write_backup_export`` off) — the exporter only matches whole folder paths.

Never a note's text or title."""

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .config import Config

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse(value) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class WriteState:
    def __init__(self, config: Config, clock=_now):
        self.config = config
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.config.home / "write_state.json"

    # ---- storage ----
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"changes": [], "backup_folders": []}
        if not isinstance(data, dict):
            return {"changes": [], "backup_folders": []}
        data.setdefault("changes", [])
        data.setdefault("backup_folders", [])
        return data

    def _write(self, data: dict) -> None:
        self.config.ensure_home()
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".write_state.", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
            f.write("\n")
        os.replace(tmp, self.path)

    def _changes(self, data: dict, now: datetime) -> List[datetime]:
        out = []
        for c in data.get("changes") or []:
            dt = _parse(c)
            if dt and now - dt < DAY:
                out.append(dt)
        return sorted(out)

    # ---- the limits ----
    def counts(self, per_hour: int = 0, per_day: int = 0) -> dict:
        """Changes made in the last hour / day, the limits, and when writing opens again if it
        is at a limit now (``limited_until``, else None)."""
        now = self._clock()
        with self._lock:
            changes = self._changes(self._read(), now)
        hour = [c for c in changes if now - c < HOUR]
        out = {"changes_last_hour": len(hour), "changes_last_day": len(changes),
               "max_per_hour": per_hour, "max_per_day": per_day, "limited_until": None}
        refusal = self._over(now, hour, changes, per_hour, per_day)
        if refusal:
            out["limited_until"] = (now + timedelta(seconds=refusal["retry_after"])).isoformat()
        return out

    @staticmethod
    def _over(now, hour, day, per_hour, per_day) -> Optional[dict]:
        waits = []
        if per_hour and len(hour) >= per_hour:
            # Open again when enough of the hour's changes have aged out to leave room for one.
            oldest = hour[len(hour) - per_hour]
            waits.append(("hour", per_hour, len(hour), oldest + HOUR - now))
        if per_day and len(day) >= per_day:
            oldest = day[len(day) - per_day]
            waits.append(("day", per_day, len(day), oldest + DAY - now))
        if not waits:
            return None
        window, limit, count, wait = max(waits, key=lambda w: w[3])
        return {"window": window, "max": limit, "count": count,
                "retry_after": max(1, int(wait.total_seconds() + 0.999))}

    def check(self, per_hour: int = 0, per_day: int = 0) -> Optional[dict]:
        """None when one more change is allowed, else ``{window, max, count, retry_after}``."""
        now = self._clock()
        with self._lock:
            changes = self._changes(self._read(), now)
        return self._over(now, [c for c in changes if now - c < HOUR], changes, per_hour, per_day)

    def record_change(self) -> None:
        now = self._clock()
        with self._lock:
            data = self._read()
            data["changes"] = [c.isoformat() for c in self._changes(data, now)] + [now.isoformat()]
            self._write(data)

    # ---- backup folders ----
    def record_backup_folder(self, account: str, path: List[str]) -> None:
        """Remember the backup folder and every folder above it (each is a folder of its own)."""
        with self._lock:
            data = self._read()
            known = {(f.get("account"), tuple(f.get("path") or [])) for f in data["backup_folders"]}
            for i in range(1, len(path) + 1):
                key = (account, tuple(path[:i]))
                if key not in known:
                    data["backup_folders"].append({"account": account, "path": list(path[:i])})
                    known.add(key)
            self._write(data)

    def backup_folders(self) -> List[dict]:
        with self._lock:
            return list(self._read().get("backup_folders") or [])

    def backup_exclusions(self, root_name: str) -> List[str]:
        """Folder paths (``A/B/C``) an export leaves out: the backup folder's name and every
        backup folder made under it. A path holding a comma can't be named to the exporter
        (its list is comma separated) and is skipped."""
        names = [root_name] if root_name else []
        for f in self.backup_folders():
            names.append("/".join(f.get("path") or []))
        out = []
        for n in names:
            if n and "," not in n and "\n" not in n and not n.startswith("-") and n not in out:
                out.append(n)
        return out
