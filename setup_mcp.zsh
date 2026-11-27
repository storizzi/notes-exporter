#!/bin/zsh
# setup_mcp.zsh - connect AI assistants (Claude Code, Claude Desktop, any MCP client)
# to your exported Apple Notes through the notes-exporter service.
#
#   ./setup_mcp.zsh                 # read + start exports; registers with Claude Code / Desktop
#   ./setup_mcp.zsh --write         # also let the assistant change and create notes
#   ./setup_mcp.zsh --client print  # just print the config for another MCP client
#   ./setup_mcp.zsh --help          # every option (notes-exporter mcp setup --help)
#
# It checks the dependencies and that the service is running and has an admin, then runs
# `notes-exporter mcp setup`, which makes an API key named MCP, writes it into
# ~/Library/Application Support/notes-exporter/mcp.env (mode 0600, never printed) and
# registers the server. Running it again rotates the key. See MCP.md.
set -u
SCRIPT_DIR="${0:A:h}"
CLI="$SCRIPT_DIR/notes-exporter"

for a in "$@"; do
    case "$a" in -h|--help) exec "$CLI" mcp setup --help ;; esac
done

PY="${NOTES_SERVICE_PYTHON:-}"
if [[ -z "$PY" ]]; then
    if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
        echo "Making $SCRIPT_DIR/.venv and installing requirements.txt…"
        python3 -m venv "$SCRIPT_DIR/.venv" || exit 1
        "$SCRIPT_DIR/.venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt" || exit 1
    fi
    PY="$SCRIPT_DIR/.venv/bin/python"
fi
if ! "$PY" -c "import fastapi, bcrypt, jwt" 2>/dev/null; then
    echo "Installing the service's requirements…"
    "$PY" -m pip install -q -r "$SCRIPT_DIR/requirements.txt" || exit 1
fi
export NOTES_SERVICE_PYTHON="$PY"

remote=0
for a in "$@"; do [[ "$a" == --url || "$a" == --url=* ]] && remote=1; done

if (( ! remote )); then
    if [[ -z "$("$CLI" user list 2>/dev/null)" ]]; then
        echo "There is no notes-exporter user yet. Make the admin first:"
        echo "  $CLI user add $USER --admin --generate-password --keychain"
        exit 1
    fi
    port="${NOTES_SERVICE_PORT:-8790}"
    if ! /usr/bin/curl -fsS -m 3 "http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then
        echo "The service isn't running on port $port. Start it, then run this again:"
        echo "  $CLI service install      # keeps it running (or: $CLI serve)"
        exit 2
    fi
fi

exec "$CLI" mcp setup "$@"
