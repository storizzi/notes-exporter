"""The LaunchAgent ``com.storizzi.notes-exporter`` that keeps ``serve`` running.

``launchctl`` is ``NOTES_SERVICE_LAUNCHCTL`` (default /bin/launchctl) and the
LaunchAgents folder is under $HOME, so tests run all of it against a fake
launchctl and a temporary HOME.

The old scheduled job ``com.<user>.notes_exporter`` (setup_launchd.py) runs
the exporter itself at night. Install refuses while it exists, because both
would export into the same folder; ``--replace-legacy`` unloads it and moves
its plist into the service's state directory (``legacy-launchagent/``), after
printing what it will do.
"""

import getpass
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

from .config import REPO_DIR, Config, default_home

LABEL = "com.storizzi.notes-exporter"


def launchctl_cmd() -> str:
    return os.environ.get("NOTES_SERVICE_LAUNCHCTL") or "/bin/launchctl"


def home_dir() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def agents_dir() -> Path:
    return home_dir() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return agents_dir() / f"{LABEL}.plist"


def legacy_label() -> str:
    return f"com.{getpass.getuser()}.notes_exporter"


def legacy_plist_path() -> Path:
    return agents_dir() / f"{legacy_label()}.plist"


def domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([launchctl_cmd(), *args], capture_output=True, text=True, timeout=30)


def is_loaded(label: str) -> bool:
    return _launchctl("print", f"{domain()}/{label}").returncode == 0


def build_plist(config: Config) -> dict:
    env = {"PYTHONPATH": str(REPO_DIR), "PATH": config.exporter_path}
    # Pass on the settings that differ from their defaults, so the agent runs as configured.
    for name, value in sorted(os.environ.items()):
        if name.startswith("NOTES_SERVICE_") and name not in ("NOTES_SERVICE_LAUNCHCTL",):
            env[name] = value
    if config.home != default_home():
        env["NOTES_SERVICE_HOME"] = str(config.home)
    logs = config.logs_dir
    return {
        "Label": LABEL,
        "ProgramArguments": [config.python, "-m", "notes_service", "serve"],
        "WorkingDirectory": str(REPO_DIR),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "service.out.log"),
        "StandardErrorPath": str(logs / "service.err.log"),
    }


def plan_install(config: Config, replace_legacy: bool) -> List[str]:
    steps = []
    legacy_present = legacy_plist_path().exists() or is_loaded(legacy_label())
    if legacy_present:
        if not replace_legacy:
            raise SystemExit(
                f"The old scheduled job {legacy_label()} exists ({legacy_plist_path()}). It runs the exporter "
                "itself, into the same folder. Run again with --replace-legacy to unload it and move its plist "
                f"into {config.home / 'legacy-launchagent'}, or remove it yourself (setup_launchd.py).")
        if is_loaded(legacy_label()):
            steps.append(f"unload the old job: launchctl bootout {domain()}/{legacy_label()}")
        if legacy_plist_path().exists():
            steps.append(f"move {legacy_plist_path()} to {config.home / 'legacy-launchagent'}/")
    if is_loaded(LABEL):
        steps.append(f"unload the running service: launchctl bootout {domain()}/{LABEL}")
    steps.append(f"write {plist_path()}")
    steps.append(f"load it: launchctl bootstrap {domain()} {plist_path()}")
    return steps


def install(config: Config, replace_legacy: bool = False, dry_run: bool = False,
            out: Callable[[str], None] = print) -> int:
    steps = plan_install(config, replace_legacy)
    out("This will:")
    for s in steps:
        out(f"  - {s}")
    if dry_run:
        out("(dry run: nothing changed)")
        out(plistlib.dumps(build_plist(config)).decode())
        return 0
    if legacy_plist_path().exists() or is_loaded(legacy_label()):
        if is_loaded(legacy_label()):
            r = _launchctl("bootout", f"{domain()}/{legacy_label()}")
            if r.returncode != 0:
                out(f"could not unload {legacy_label()}: {r.stderr.strip()}")
                return 1
        if legacy_plist_path().exists():
            backup = config.home / "legacy-launchagent"
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_plist_path()), str(backup / legacy_plist_path().name))
            out(f"moved the old job's plist to {backup}")
    config.ensure_home()
    if is_loaded(LABEL):
        _launchctl("bootout", f"{domain()}/{LABEL}")
    agents_dir().mkdir(parents=True, exist_ok=True)
    with open(plist_path(), "wb") as f:
        plistlib.dump(build_plist(config), f)
    r = _launchctl("bootstrap", domain(), str(plist_path()))
    if r.returncode != 0:
        out(f"launchctl bootstrap failed: {r.stderr.strip() or r.returncode}")
        return 1
    out(f"installed {LABEL}; it serves on http://{config.host}:{config.port}/")
    return 0


def uninstall(out: Callable[[str], None] = print) -> int:
    if is_loaded(LABEL):
        r = _launchctl("bootout", f"{domain()}/{LABEL}")
        if r.returncode != 0:
            out(f"could not unload {LABEL}: {r.stderr.strip()}")
            return 1
        out(f"unloaded {LABEL}")
    if plist_path().exists():
        plist_path().unlink()
        out(f"removed {plist_path()}")
    else:
        out("the service was not installed")
    return 0


def status(config: Config) -> dict:
    r = _launchctl("print", f"{domain()}/{LABEL}")
    pid = state = None
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("pid = "):
                pid = int(line.split("=", 1)[1].strip())
            elif line.startswith("state = "):
                state = line.split("=", 1)[1].strip()
    return {"label": LABEL, "plist": str(plist_path()), "installed": plist_path().exists(),
            "loaded": r.returncode == 0, "state": state, "pid": pid,
            "legacy_job": {"label": legacy_label(), "plist_present": legacy_plist_path().exists(),
                           "loaded": is_loaded(legacy_label())}}
