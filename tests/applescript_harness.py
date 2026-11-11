"""Run individual handlers of export_notes.scpt without touching Apple Notes.

The script is compiled once with ``osacompile`` (which only reads the Notes
scripting dictionary), loaded with ``load script`` and a single handler is
called. Handlers that never address ``application "Notes"`` send no Apple
Events, so no macOS automation permission is needed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "export_notes.scpt"

requires_osascript = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("osascript") is None,
    reason="AppleScript tests need macOS",
)


def compile_script(dest_dir: Path) -> Path:
    out = dest_dir / "export_notes_compiled.scpt"
    subprocess.run(["osacompile", "-o", str(out), str(SCRIPT)],
                   check=True, capture_output=True, text=True)
    return out


def call_handler(compiled: Path, expression: str, *args: str) -> str:
    """Evaluate ``expression`` with the loaded script bound to ``s``.

    ``args`` are available as ``item N of argv`` so test strings never pass
    through AppleScript source quoting.
    """
    lines = [
        "on run argv",
        f'set s to load script (POSIX file "{compiled}")',
        f"return {expression}",
        "end run",
    ]
    cmd = ["osascript"]
    for line in lines:
        cmd += ["-e", line]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.rstrip("\n")
