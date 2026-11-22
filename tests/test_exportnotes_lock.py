"""exportnotes.zsh's lock: a lock that can't be created says why, and only a lock that really
exists is "another export". Apple Notes is never touched (tests/fake_osascript.py), and a fake
``mkdir`` first on PATH stands in for macOS refusing the lock folder (TCC's EPERM)."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "exportnotes.zsh"

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("zsh"),
                                reason="exportnotes.zsh needs macOS and zsh")

FAKE_MKDIR = """#!/bin/sh
# Refuses the lock folder as macOS privacy settings do; any other mkdir is the real one.
for a in "$@"; do
    case "$a" in
        *.notes-exporter.lock) echo "mkdir: $a: Operation not permitted" >&2; exit 1 ;;
    esac
done
exec /bin/mkdir "$@"
"""


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "osascript"
    fake.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{REPO / 'tests' / 'fake_osascript.py'}' \"$@\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"notes": [{
        "account": "iCloud", "folder": ["Food"], "folder_id": "Food", "id": 1, "title": "Scones",
        "modified": "2026-03-05T07:08:09", "html": "<div><h1>Scones</h1></div>", "text": "Scones"}],
        "fail": None}))
    e = {k: v for k, v in os.environ.items() if not k.startswith("NOTES_EXPORT_")}
    e.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_NOTES_LIBRARY=str(library),
             NOTES_EXPORT_SKIP_PERMISSION_CHECK="true", HOME=str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    root = tmp_path / "export"
    root.mkdir()
    return {"env": e, "bin": bin_dir, "root": root}


def run(env):
    cmd = ["zsh", str(SCRIPT), "--python", sys.executable, "--root-dir", str(env["root"]),
           "--filename-format", "&title", "--json-log"]
    return subprocess.run(cmd, env=env["env"], capture_output=True, text=True, timeout=120)


def result_event(r):
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()][-1]


def test_lock_refused_by_macos_says_so(env):
    fake = env["bin"] / "mkdir"
    fake.write_text(FAKE_MKDIR)
    fake.chmod(0o755)
    r = run(env)
    assert r.returncode == 1, r.stderr
    msg = result_event(r)["message"]
    assert "cannot create the lock in" in msg and "Operation not permitted" in msg
    assert "Full Disk Access" in msg and "another export" not in msg
    assert not (env["root"] / "raw").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_lock_in_an_unwritable_folder_says_so(env):
    env["root"].chmod(0o555)
    try:
        r = run(env)
    finally:
        env["root"].chmod(0o755)
    assert r.returncode == 1
    msg = result_event(r)["message"]
    assert "cannot create the lock in" in msg and "Permission denied" in msg and "permissions" in msg
    assert "another export" not in msg


def test_an_existing_lock_without_a_pid_is_still_another_export(env):
    (env["root"] / ".notes-exporter.lock").mkdir()
    r = run(env)
    assert r.returncode == 4
    assert "another export (pid unknown)" in result_event(r)["message"]
    assert (env["root"] / ".notes-exporter.lock").is_dir()  # not ours to remove
