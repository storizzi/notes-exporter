"""Scheduler rules: interval, daily time, catch-up once, skip while running."""

from datetime import datetime, timedelta

from notes_service.runs import RunBusy
from notes_service.scheduler import Scheduler, next_run_at

T0 = datetime(2026, 11, 11, 12, 0).astimezone()


def test_disabled_or_empty():
    assert next_run_at({"enabled": False, "interval_minutes": 5}, None, T0) is None
    assert next_run_at({}, None, T0) is None


def test_interval_from_last_start_or_service_start():
    s = {"enabled": True, "interval_minutes": 60}
    assert next_run_at(s, None, T0) == T0 + timedelta(minutes=60)
    last = T0 + timedelta(minutes=10)
    assert next_run_at(s, last, T0) == last + timedelta(minutes=60)


def test_daily_at():
    s = {"enabled": True, "daily_at": "00:13"}
    assert next_run_at(s, None, T0) == (T0 + timedelta(days=1)).replace(hour=0, minute=13)
    early = T0.replace(hour=0, minute=5)
    assert next_run_at(s, early, early) == early.replace(minute=13)
    # last run yesterday at 00:13, service restarted today at 09:00: today's 00:13 is due (catch up once)
    yesterday = (T0 - timedelta(days=1)).replace(hour=0, minute=13)
    due = next_run_at(s, yesterday, T0.replace(hour=9))
    assert due == T0.replace(hour=0, minute=13, second=0, microsecond=0)
    # ...and after that catch-up run at 09:00, the next is tomorrow's
    assert next_run_at(s, T0.replace(hour=9), T0) == (T0 + timedelta(days=1)).replace(hour=0, minute=13)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(schedule, running=False, last=None, busy=False):
    started = []
    clock = Clock(T0)

    def start():
        if busy:
            raise RunBusy("x")
        started.append(clock())
    s = Scheduler(30, lambda: schedule, lambda: last, start, lambda: running, clock=clock)
    return s, clock, started


def test_check_starts_when_due():
    s, clock, started = make({"enabled": True, "interval_minutes": 10})
    assert s.check() is None
    clock.t = T0 + timedelta(minutes=11)
    assert s.check() == "started" and started


def test_check_skips_while_running():
    s, clock, started = make({"enabled": True, "interval_minutes": 10}, running=True)
    clock.t = T0 + timedelta(minutes=11)
    assert s.check() == "skipped" and not started and s.skipped == 1
    s2, clock2, _ = make({"enabled": True, "interval_minutes": 10}, busy=True)
    clock2.t = T0 + timedelta(minutes=11)
    assert s2.check() == "skipped"


def test_scheduled_run_through_service(service, export_root):
    client, ctx = service
    ctx.settings.update({"schedule": {"enabled": True, "interval_minutes": 5}})
    ctx.scheduler.service_started = datetime.now().astimezone() - timedelta(minutes=6)
    assert ctx.scheduler.check() == "started"
    run = client.get("/api/runs").json()["runs"][0]
    assert run["trigger"] == "schedule" and run["requested_by"] == "schedule"
    assert ctx.scheduler.check() in ("skipped", None)  # running, or not due again
    ctx.manager.wait(20)
    assert ctx.scheduler.check() is None  # next slot is 5 minutes after that run's start
