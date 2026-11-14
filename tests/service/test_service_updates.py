"""Updating the service from a client (updates.py): every fence, through the API too. git,
pip and the self-check are a fake runner over a pretend checkout in tmp_path, the restart a
fake exit — nothing here touches the real checkout, the network or launchd."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from notes_service.app import create_app
from notes_service.updates import UpdateManager, latest_of, newer, parse_tags

from .conftest import PASSWORD, fake_permissions, make_key

LS_REMOTE = """\
aaa\trefs/tags/v1.5.0
bbb\trefs/tags/v1.5.0^{}
ccc\trefs/tags/v1.6.0
ddd\trefs/tags/v1.6.0^{}
eee\trefs/tags/v1.10.0-beta
fff\trefs/tags/notes
"""


def done(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


class FakeGit:
    """A pretend checkout: VERSION (and requirements.txt) in `repo` change as git commands
    say; `calls` records every command."""

    def __init__(self, repo: Path, version="1.5.0"):
        self.repo = repo
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "VERSION").write_text(version + "\n")
        (repo / "requirements.txt").write_text("fastapi\n")
        self.ls_remote = LS_REMOTE
        self.ls_fails = False
        self.dirty = ""
        self.ahead = "0"
        self.tracking = True
        self.is_git = True
        self.ancestor = True           # HEAD is an ancestor of the target tag
        self.fetch_fails = False
        self.merge_fails = False
        self.new_requirements = False
        self.pip_fails = False
        self.import_fails = False
        self.reports = None            # what --version says (default: the merged VERSION)
        self.head = "bbb"
        self.calls = []

    def __call__(self, args, cwd, timeout):
        self.calls.append(list(args))
        if args[0] == "git":
            return self.git(args[1:])
        if "pip" in args:
            return done(1, err="no wheel") if self.pip_fails else done()
        if args[1:3] == ["-c", "import notes_service.app"]:
            return done(1, err="ImportError: boom") if self.import_fails else done()
        if args[-1] == "--version":
            said = self.reports or (self.repo / "VERSION").read_text().strip()
            return done(out=f"notes-exporter {said}\n")
        raise AssertionError(args)

    def git(self, a):
        if a[0] == "ls-remote":
            return done(128, err="fatal: could not read from remote") if self.ls_fails else done(out=self.ls_remote)
        if a[0] == "rev-parse" and a[1] == "--is-inside-work-tree":
            return done(out="true\n") if self.is_git else done(128, err="not a git repository")
        if a[0] == "status":
            return done(out=self.dirty)
        if a[0] == "rev-list":
            return done(out=self.ahead + "\n") if self.tracking else done(128, err="no upstream")
        if a[0] == "merge-base":
            return done(0 if self.ancestor else 1)
        if a[0] == "rev-parse" and a[1] == "HEAD":
            return done(out=self.head + "\n")
        if a[0] == "fetch":
            return done(1, err="network down") if self.fetch_fails else done()
        if a[0] == "rev-parse" and a[1] == "--verify":
            version = a[-1].split("^")[0].lstrip("v")
            return done() if version in parse_tags(self.ls_remote) else done(1)
        if a[0] == "merge":
            if self.merge_fails:
                return done(1, err="not possible to fast-forward")
            self.saved = ((self.repo / "VERSION").read_text(), (self.repo / "requirements.txt").read_text())
            (self.repo / "VERSION").write_text(a[-1].lstrip("v") + "\n")
            if self.new_requirements:
                (self.repo / "requirements.txt").write_text("fastapi\nnewdep\n")
            self.head = "merged"
            return done()
        if a[0] == "reset":
            if hasattr(self, "saved"):
                (self.repo / "VERSION").write_text(self.saved[0])
                (self.repo / "requirements.txt").write_text(self.saved[1])
            self.head = a[-1]
            return done()
        raise AssertionError(a)

    def ran(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


@pytest.fixture
def git(tmp_path):
    return FakeGit(tmp_path / "checkout")


@pytest.fixture
def mgr(make_config, git):
    exits = []
    state = SimpleNamespace(run=None, launchd=True, now=1000.0, exits=exits)
    m = UpdateManager(make_config(update_python=sys.executable, restart_delay_seconds=0.0),
                      running_run_id=lambda: state.run, repo_dir=git.repo, loaded_version="1.5.0",
                      runner=git, exit_process=lambda: exits.append(True),
                      is_under_launchd=lambda: state.launchd, clock=lambda: state.now)
    m.state = state
    return m


# ---- pure helpers ----

def test_tags_and_versions():
    tags = parse_tags(LS_REMOTE)
    assert tags == {"1.5.0": "bbb", "1.6.0": "ddd"}      # peeled commits, no pre-releases or other tags
    assert latest_of(tags) == "1.6.0"
    assert latest_of({"1.9.0": "a", "1.10.0": "b"}) == "1.10.0"
    assert newer("1.6.0", "1.5.1") and not newer("1.5.1", "1.5.1") and not newer(None, "1.0.0")
    assert newer("1.0.0", None) and not newer("junk", "1.0.0")


# ---- the view ----

def test_view_says_what_is_running_installed_and_newest(mgr, git):
    v = mgr.view()
    assert v["version"] == "1.5.0" and v["installed"] == "1.5.0" and not v["restart_needed"]
    assert v["latest"] == "1.6.0" and v["update_available"] and v["can_update"] and v["why_not"] is None
    assert v["can_restart"] and v["latest_checked_at"]


def test_restart_needed_when_the_disk_moved_on(mgr, git):
    (git.repo / "VERSION").write_text("1.5.1\n")
    v = mgr.view()
    assert v["restart_needed"] and v["installed"] == "1.5.1"


def test_check_is_cached_and_a_refresh_rate_limited(mgr, git):
    mgr.view(); mgr.view()
    assert len(git.ran("git", "ls-remote")) == 1
    mgr.view(refresh=True)                      # too soon after the last check
    assert len(git.ran("git", "ls-remote")) == 1
    mgr.state.now += 61
    mgr.view(refresh=True)
    assert len(git.ran("git", "ls-remote")) == 2
    mgr.state.now += 25 * 3600                  # older than update_check_hours
    mgr.view()
    assert len(git.ran("git", "ls-remote")) == 3


def test_a_failed_check_is_reported(mgr, git):
    git.ls_fails = True
    v = mgr.view()
    assert v["latest"] is None and not v["update_available"] and not v["can_update"]
    assert "could not read from remote" in v["check_error"]


def test_up_to_date(mgr, git):
    (git.repo / "VERSION").write_text("1.6.0\n")
    v = mgr.view()
    assert not v["update_available"] and v["why_not"] == "This is the newest release."


@pytest.mark.parametrize("setup, words", [
    (lambda m, g: setattr(m.config, "allow_update", False), "turned off"),
    (lambda m, g: setattr(m.state, "run", "r1"), "export is running"),
    (lambda m, g: setattr(g, "is_git", False), "git checkout"),
    (lambda m, g: setattr(g, "dirty", " M notes_service/app.py\n"), "uncommitted"),
    (lambda m, g: setattr(g, "ahead", "2"), "push them"),
    (lambda m, g: setattr(g, "tracking", False), "doesn't track"),
    (lambda m, g: setattr(g, "ancestor", False), "fast-forward"),
])
def test_why_no_update(mgr, git, setup, words):
    setup(mgr, git)
    v = mgr.view()
    assert not v["can_update"] and words in v["why_not"]


# ---- update ----

def test_update_fast_forwards_and_checks_itself(mgr, git):
    r = mgr.update(who="key")
    assert r == {"ok": True, "from": "1.5.0", "to": "1.6.0", "restart_needed": True, "requirements_changed": False}
    assert (git.repo / "VERSION").read_text().strip() == "1.6.0"
    assert git.ran("git", "fetch") and git.ran("git", "merge", "--ff-only", "v1.6.0")
    assert not [c for c in git.calls if "pip" in c]          # requirements unchanged: no pip
    log = (mgr.config.home / "updates.ndjson").read_text()
    assert '"result": "ok"' in log and '"to": "1.6.0"' in log
    assert mgr.view()["restart_needed"]


def test_update_installs_changed_requirements(mgr, git):
    git.new_requirements = True
    r = mgr.update()
    assert r["ok"] and r["requirements_changed"]
    assert [c for c in git.calls if c[1:5] == ["-m", "pip", "install", "-r"]]


@pytest.mark.parametrize("break_it, words", [
    ("import_fails", "doesn't load"),
    ("pip_fails", "requirements failed"),
    ("merge_fails", "merge failed"),
])
def test_a_bad_update_is_rolled_back(mgr, git, break_it, words):
    setattr(git, break_it, True)
    if break_it == "pip_fails":
        git.new_requirements = True
    r = mgr.update()
    assert not r["ok"] and r["rolled_back"] and words in r["reason"] and not r["restart_needed"]
    assert (git.repo / "VERSION").read_text().strip() == "1.5.0"
    assert (git.repo / "requirements.txt").read_text() == "fastapi\n"
    assert git.ran("git", "reset", "--hard", "bbb")
    assert '"result": "rolled_back"' in (mgr.config.home / "updates.ndjson").read_text()


def test_a_version_that_reports_itself_wrongly_is_rolled_back(mgr, git):
    git.reports = "1.5.0"
    r = mgr.update()
    assert not r["ok"] and "reports itself as 1.5.0" in r["reason"]
    assert (git.repo / "VERSION").read_text().strip() == "1.5.0"


@pytest.mark.parametrize("to, status", [("latest", 400), ("1.5.0", 409), ("1.4.0", 409), ("1.7.0", 404)])
def test_update_refuses_bad_targets(mgr, git, to, status):
    with pytest.raises(Exception) as err:
        mgr.update(to)
    assert err.value.status == status
    assert not git.ran("git", "merge")


def test_update_refuses_while_blocked_and_reports_a_failed_fetch(mgr, git):
    mgr.state.run = "r1"
    with pytest.raises(Exception) as err:
        mgr.update()
    assert err.value.status == 409 and "export is running" in str(err.value)
    mgr.state.run = None
    git.fetch_fails = True
    with pytest.raises(Exception) as err:
        mgr.update()
    assert err.value.status == 502 and "network down" in str(err.value)
    assert (git.repo / "VERSION").read_text().strip() == "1.5.0" and not mgr.updating


# ---- restart ----

def test_restart_only_under_launchd_and_not_mid_export(mgr):
    mgr.state.launchd = False
    with pytest.raises(Exception) as err:
        mgr.restart()
    assert err.value.status == 409 and "launchd" in str(err.value)
    mgr.state.launchd = True
    mgr.state.run = "r1"
    with pytest.raises(Exception) as err:
        mgr.restart()
    assert err.value.status == 409 and "force" in str(err.value)
    assert mgr.restart(force=True) == {"restarting": True}
    import time
    for _ in range(50):
        if mgr.state.exits:
            break
        time.sleep(0.01)
    assert mgr.state.exits == [True]


# ---- through the API ----

@pytest.fixture
def api(make_config, export_root, git):
    config = make_config(update_python=sys.executable, restart_delay_seconds=0.0)
    app = create_app(config, fake_permissions(config))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        ctx = app.state.ctx
        ctx.auth.create_user("root", PASSWORD, "admin")
        ctx.settings.update({"export_root": str(export_root)})
        exits = []
        ctx.updates = UpdateManager(config, running_run_id=lambda: ctx.manager.running_run_id,
                                    repo_dir=git.repo, loaded_version="1.5.0", runner=git,
                                    exit_process=lambda: exits.append(True), is_under_launchd=lambda: True)
        keys = {"read": make_key(ctx, ["read"]), "admin": make_key(ctx, ["read", "admin"])}
        yield client, keys, exits
        ctx.manager.shutdown()


def as_(keys, which):
    return {"Authorization": f"Bearer {keys[which]}"}


def test_api_version_needs_read_and_answers(api):
    client, keys, _ = api
    assert client.get("/api/version").status_code == 401
    r = client.get("/api/version", headers=as_(keys, "read"))
    assert r.status_code == 200 and r.json()["latest"] == "1.6.0" and r.json()["update_available"]


def test_api_update_and_restart_need_admin(api, git):
    client, keys, exits = api
    assert client.post("/api/admin/update", json={}, headers=as_(keys, "read")).status_code == 403
    assert client.post("/api/admin/restart", json={}, headers=as_(keys, "read")).status_code == 403
    r = client.post("/api/admin/update", json={"to": "1.6.0"}, headers=as_(keys, "admin"))
    assert r.status_code == 200 and r.json()["ok"] and r.json()["to"] == "1.6.0"
    assert client.get("/api/version", headers=as_(keys, "read")).json()["restart_needed"]
    r = client.post("/api/admin/restart", json={}, headers=as_(keys, "admin"))
    assert r.status_code in (200, 202) and r.json() == {"restarting": True}


def test_api_refusals_carry_their_message(api, git):
    client, keys, _ = api
    r = client.post("/api/admin/update", json={"to": "1.7.0"}, headers=as_(keys, "admin"))
    assert r.status_code == 404 and "no release 1.7.0" in r.json()["detail"]
    git.dirty = " M x\n"
    r = client.post("/api/admin/update", json={}, headers=as_(keys, "admin"))
    assert r.status_code == 409 and "uncommitted" in r.json()["detail"]
