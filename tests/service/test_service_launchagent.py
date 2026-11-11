"""The LaunchAgent installer, against a fake launchctl and a temporary HOME.

Nothing here touches the real launchd or ~/Library/LaunchAgents.
"""

import json
import os
import plistlib
import stat
import sys

import pytest

from notes_service import launchagent
from notes_service.config import Config


@pytest.fixture
def fake_launchctl(tmp_path, monkeypatch, isolated_env):
    log = tmp_path / "launchctl.log"
    loaded = tmp_path / "loaded"
    loaded.mkdir()
    script = tmp_path / "launchctl"
    script.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
log, loaded = Path({str(log)!r}), Path({str(loaded)!r})
args = sys.argv[1:]
with log.open("a") as f:
    f.write(json.dumps(args) + "\\n")
cmd = args[0]
if cmd == "print":
    label = args[1].split("/")[-1]
    if (loaded / label).exists():
        print("state = running"); print("pid = 4242"); sys.exit(0)
    sys.exit(113)
if cmd == "bootstrap":
    import plistlib
    label = plistlib.loads(Path(args[2]).read_bytes())["Label"]
    (loaded / label).touch(); sys.exit(0)
if cmd == "bootout":
    label = args[1].split("/")[-1]
    p = loaded / label
    if p.exists():
        p.unlink(); sys.exit(0)
    sys.exit(3)
sys.exit(1)
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NOTES_SERVICE_LAUNCHCTL", str(script))
    assert launchagent.launchctl_cmd() == str(script)
    assert str(launchagent.agents_dir()).startswith(str(isolated_env))

    class Fake:
        def calls(self):
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def load(self, label):
            (loaded / label).touch()

        def is_loaded(self, label):
            return (loaded / label).exists()
    return Fake()


@pytest.fixture
def config(tmp_path):
    return Config(home=tmp_path / "state", python=sys.executable)


def test_install_writes_plist_and_bootstraps(fake_launchctl, config):
    out = []
    assert launchagent.install(config, out=out.append) == 0
    plist = plistlib.loads(launchagent.plist_path().read_bytes())
    assert plist["Label"] == "com.storizzi.notes-exporter"
    assert plist["ProgramArguments"][1:] == ["-m", "notes_service", "serve"]
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert plist["EnvironmentVariables"]["NOTES_SERVICE_HOME"] == str(config.home)
    assert "NOTES_SERVICE_LAUNCHCTL" not in plist["EnvironmentVariables"]
    assert ["bootstrap", f"gui/{os.getuid()}", str(launchagent.plist_path())] in fake_launchctl.calls()
    st = launchagent.status(config)
    assert st["installed"] and st["loaded"] and st["pid"] == 4242 and st["state"] == "running"
    # reinstall: unloads the running one first
    assert launchagent.install(config, out=out.append) == 0
    assert any(c[0] == "bootout" for c in fake_launchctl.calls())


def test_dry_run_changes_nothing(fake_launchctl, config):
    out = []
    assert launchagent.install(config, dry_run=True, out=out.append) == 0
    assert not launchagent.plist_path().exists()
    assert not any(c[0] in ("bootstrap", "bootout") for c in fake_launchctl.calls())
    assert any("dry run" in line for line in out)


def test_refuses_with_legacy_job(fake_launchctl, config):
    legacy = launchagent.legacy_plist_path()
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(plistlib.dumps({"Label": launchagent.legacy_label()}))
    with pytest.raises(SystemExit) as e:
        launchagent.install(config, out=lambda s: None)
    assert "--replace-legacy" in str(e.value)
    assert legacy.exists() and not launchagent.plist_path().exists()
    assert not any(c[0] in ("bootstrap", "bootout") for c in fake_launchctl.calls())


def test_refuses_when_legacy_only_loaded(fake_launchctl, config):
    fake_launchctl.load(launchagent.legacy_label())
    with pytest.raises(SystemExit):
        launchagent.install(config, out=lambda s: None)


def test_replace_legacy(fake_launchctl, config):
    legacy = launchagent.legacy_plist_path()
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(plistlib.dumps({"Label": launchagent.legacy_label()}))
    fake_launchctl.load(launchagent.legacy_label())
    out = []
    assert launchagent.install(config, replace_legacy=True, out=out.append) == 0
    text = "\n".join(out)
    assert "unload the old job" in text and "move" in text   # said before doing it
    assert out.index("This will:") < next(i for i, l in enumerate(out) if l.startswith("moved"))
    assert not legacy.exists()
    assert (config.home / "legacy-launchagent" / legacy.name).exists()
    assert not fake_launchctl.is_loaded(launchagent.legacy_label())
    assert fake_launchctl.is_loaded(launchagent.LABEL)
    st = launchagent.status(config)
    assert st["legacy_job"] == {"label": launchagent.legacy_label(), "plist_present": False, "loaded": False}


def test_uninstall(fake_launchctl, config):
    out = []
    launchagent.install(config, out=out.append)
    assert launchagent.uninstall(out=out.append) == 0
    assert not launchagent.plist_path().exists() and not fake_launchctl.is_loaded(launchagent.LABEL)
    assert launchagent.uninstall(out=out.append) == 0
    assert "not installed" in out[-1]


def test_cli_service_status_json(fake_launchctl, config, capsys, monkeypatch):
    from notes_service.cli import main
    monkeypatch.setenv("NOTES_SERVICE_HOME", str(config.home))
    assert main(["service", "status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["installed"] is False and st["loaded"] is False
