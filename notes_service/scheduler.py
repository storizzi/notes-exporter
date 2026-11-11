"""The schedule: every N minutes, or daily at HH:MM (local time).

``next_run_at`` is a pure function so the rules are testable:

* interval: the last run's start (any trigger) + interval; with no runs yet,
  the service's start + interval (a fresh install doesn't export at once).
* daily_at: the first HH:MM after the last run's start, or after the
  service's start when there are none. A time missed while the Mac slept is
  run once when the service sees it, not once per missed day.

A due slot while a run is in progress is skipped: the next one is worked out
from that run's start once it has finished.
"""

import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

from .runs import RunBusy


def _parse_local(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone() if dt.tzinfo else dt.astimezone()


def next_run_at(schedule: dict, last_started: Optional[datetime], service_started: datetime) -> Optional[datetime]:
    if not schedule or not schedule.get("enabled"):
        return None
    base = last_started or service_started
    base = base.astimezone()
    if schedule.get("interval_minutes"):
        return base + timedelta(minutes=int(schedule["interval_minutes"]))
    if schedule.get("daily_at"):
        hh, mm = (int(x) for x in schedule["daily_at"].split(":"))
        candidate = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= base:
            candidate += timedelta(days=1)
        return candidate
    return None


class Scheduler:
    def __init__(self, tick_seconds: float, get_schedule: Callable[[], dict],
                 last_started: Callable[[], Optional[str]], start_run: Callable[[], None],
                 is_running: Callable[[], bool], clock: Callable[[], datetime] = None):
        self.tick = tick_seconds
        self.get_schedule = get_schedule
        self.last_started = last_started
        self.start_run = start_run
        self.is_running = is_running
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.service_started = self.clock()
        self.skipped = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def next_run_at(self) -> Optional[datetime]:
        return next_run_at(self.get_schedule(), _parse_local(self.last_started()), self.service_started)

    def check(self) -> Optional[str]:
        """One tick: start a run when one is due. Returns what happened (for tests)."""
        due = self.next_run_at()
        if due is None or due > self.clock():
            return None
        if self.is_running():
            self.skipped += 1
            return "skipped"
        try:
            self.start_run()
        except RunBusy:
            self.skipped += 1
            return "skipped"
        return "started"

    def _loop(self):
        while not self._stop.wait(self.tick):
            try:
                self.check()
            except Exception:
                pass

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
