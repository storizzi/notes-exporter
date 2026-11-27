"""What an MCP client needs to start ``notes-exporter mcp serve``, shared by
``notes-exporter mcp setup`` and the web page's MCP tab (``/api/admin/mcp``).

Standard library only: the MCP server runs with any ``python3``.

The API key never goes into a client's configuration. It lives in an env file
(``<state dir>/mcp.env``, mode 0600) that the server reads at start, so the
client's config holds only a command line.
"""

import json
import os
import shlex
from pathlib import Path
from typing import List, Optional

REPO_DIR = Path(__file__).resolve().parent.parent
COMMAND = REPO_DIR / "notes-exporter"
KEY_VAR = "NOTES_EXPORTER_API_KEY"
URL_VAR = "NOTES_EXPORTER_URL"
ENV_FILE_VAR = "NOTES_EXPORTER_MCP_ENV_FILE"
DEFAULT_SERVER_NAME = "notes-exporter"
DEFAULT_KEY_NAME = "MCP"
ENV_FILE_NAME = "mcp.env"


def default_env_file(home: Path) -> Path:
    return Path(home) / ENV_FILE_NAME


def server_args(url: Optional[str] = None, env_file: Optional[str] = None, read_only: bool = False) -> List[str]:
    """The arguments after ``notes-exporter``: only what differs from the defaults."""
    args = ["mcp", "serve"]
    if url:
        args += ["--url", url]
    if env_file:
        args += ["--env-file", str(env_file)]
    if read_only:
        args.append("--read-only")
    return args


def client_entry(args: List[str]) -> dict:
    return {"command": str(COMMAND), "args": list(args)}


def claude_code_command(name: str, args: List[str], scope: str = "user") -> List[str]:
    return ["claude", "mcp", "add", "--scope", scope, name, "--", str(COMMAND), *args]


def snippets(name: str, args: List[str]) -> dict:
    """Copy-and-paste text for the common clients."""
    entry = client_entry(args)
    return {
        "server_name": name,
        "command": entry["command"],
        "args": entry["args"],
        "claude_code": shlex.join(claude_code_command(name, args)),
        "json": json.dumps({"mcpServers": {name: entry}}, indent=2),
        "setup_command": shlex.join([str(REPO_DIR / "setup_mcp.zsh")]),
    }


def read_env_key(path, var: str = KEY_VAR) -> Optional[str]:
    """The value of ``var`` in an env file (``NAME=value`` or ``export NAME=value``), else None."""
    try:
        text = Path(os.path.expanduser(str(path))).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if sep and name.strip() == var:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None
