"""``notes-exporter mcp setup | check | uninstall``: connect an MCP client
(Claude Code, Claude Desktop, anything that runs a stdio server) to the service.

``setup`` makes an API key for the MCP server and writes it into its env file
(never printed, never into a client's config), then registers the server with
the clients asked for. Run again, it rotates the key. With ``--url`` for a
service on another Mac, the key comes from that service (its web page's MCP
tab, or ``notes-exporter apikey create`` there) through ``--key-stdin``.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from .config import LOOPBACK_HOSTS, Config, default_home
from .mcp_client import (DEFAULT_KEY_NAME, DEFAULT_SERVER_NAME, KEY_VAR, claude_code_command, client_entry,
                         default_env_file, read_env_key, server_args)

CLIENTS = ("claude-code", "claude-desktop", "print")
DEFAULT_URL = "http://127.0.0.1:8790"


def claude_bin() -> Optional[str]:
    return os.environ.get("NOTES_SERVICE_CLAUDE_BIN") or shutil.which("claude")


def desktop_config_path() -> Path:
    return Path(os.environ.get("NOTES_SERVICE_CLAUDE_DESKTOP_CONFIG")
                or Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOOPBACK_HOSTS


def scopes_for(args) -> List[str]:
    scopes = ["read"]
    if not args.no_run:
        scopes.append("run")
    if args.write:
        scopes.append("write")
    return scopes


def _args_for_client(args, config: Config, env_file: Path) -> List[str]:
    url = args.url if args.url and args.url.rstrip("/") != DEFAULT_URL else None
    if not url and config.local_url() != DEFAULT_URL:
        url = config.local_url()
    default = default_env_file(default_home())
    return server_args(url=url, env_file=None if env_file == default else str(env_file),
                       read_only=args.read_only)


def _owner(store, name: Optional[str]) -> dict:
    if name:
        user = store.find_user(name)
        if not user:
            raise SystemExit(f"no user {name!r}")
        return user
    admins = [u for u in store.list_users() if u["role"] == "admin"]
    if len(admins) != 1:
        raise SystemExit("name the key's owner with --owner USER" if admins else
                         "there is no admin yet: notes-exporter user add NAME --admin --generate-password --keychain")
    return admins[0]


def make_key(config: Config, name: str, scopes: List[str], owner_name: Optional[str], env_file: Path,
             expires_days: Optional[int] = None, replace: bool = True) -> dict:
    """Create a key, write it into env_file, revoke the owner's older keys of that name.
    Returns {record, revoked}. The key itself is never returned or printed."""
    from .auth import AuthError, AuthStore
    from .envfile import write_env_var
    store = AuthStore(config)
    owner = _owner(store, owner_name)
    expires = None
    if expires_days:
        expires = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat(timespec="seconds")
    try:
        record, key = store.create_key(name, scopes, owner["id"], expires)
    except AuthError as e:
        raise SystemExit(f"error: {e}")
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_env_var(str(env_file), KEY_VAR, key)
    except (OSError, ValueError) as e:
        store.delete_key(record["id"])
        raise SystemExit(f"error: couldn't write {env_file} ({e.__class__.__name__}: {e}); the key was not kept")
    revoked = []
    if replace:
        for k in store.list_keys():
            if k["owner_user_id"] == owner["id"] and k["name"] == record["name"] and k["id"] != record["id"]:
                store.delete_key(k["id"])
                revoked.append(k["prefix"])
    return {"record": record, "revoked": revoked, "owner": owner["username"]}


def register_claude_code(name: str, args: List[str], scope: str, dry_run: bool) -> bool:
    exe = claude_bin()
    cmd = claude_code_command(name, args, scope)
    if not exe:
        print("Claude Code: the claude command wasn't found. Register it yourself with:\n  " + shlex.join(cmd))
        return False
    cmd[0] = exe
    if dry_run:
        print("would run: " + shlex.join(cmd))
        return True
    subprocess.run([exe, "mcp", "remove", "--scope", scope, name], capture_output=True, text=True,
                   stdin=subprocess.DEVNULL, timeout=60)
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    if r.returncode != 0:
        print(f"Claude Code: claude mcp add failed: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
        return False
    print(f"Claude Code: added MCP server {name!r} ({scope} scope); new sessions have it (/mcp shows it)")
    return True


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_desktop(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as e:
        raise SystemExit(f"error: {path} isn't valid JSON ({e}); fix it or add the server by hand")
    if not isinstance(data, dict):
        raise SystemExit(f"error: {path} isn't a JSON object")
    return data


def register_claude_desktop(name: str, args: List[str], dry_run: bool) -> bool:
    path = desktop_config_path()
    data = _load_desktop(path)
    servers = data.setdefault("mcpServers", {})
    entry = client_entry(args)
    if dry_run:
        print(f"would set mcpServers.{name} in {path} to {json.dumps(entry)}")
        return True
    if servers.get(name) == entry:
        print(f"Claude Desktop: {name!r} already set up in {path}")
        return True
    if path.exists():
        backup = path.with_name(path.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
        print(f"Claude Desktop: saved the old config as {backup}")
    servers[name] = entry
    _write_json_atomic(path, data)
    print(f"Claude Desktop: added {name!r} to {path}; quit and reopen Claude Desktop to load it")
    return True


def print_config(name: str, args: List[str]) -> None:
    print("For any other MCP client (stdio), add:")
    print(json.dumps({"mcpServers": {name: client_entry(args)}}, indent=2))


def default_clients() -> List[str]:
    clients = ["claude-code"] if claude_bin() else []
    if desktop_config_path().parent.is_dir():
        clients.append("claude-desktop")
    return clients or ["print"]


def setup(args, config: Config) -> int:
    url = (args.url or config.local_url()).rstrip("/")
    local = is_local(url)
    env_file = Path(os.path.expanduser(args.env_file)) if args.env_file else default_env_file(config.home)
    scopes = scopes_for(args)
    clients = args.client or default_clients()
    client_args = _args_for_client(args, config, env_file)

    print(f"MCP server for notes-exporter at {url}")
    print(f"  key: {args.name!r} with scopes {','.join(scopes)}, kept in {env_file}")
    print(f"  clients: {', '.join(clients)}")
    if args.dry_run:
        print("(dry run: nothing changed)")

    # 1. the key
    if args.key_stdin:
        key = sys.stdin.readline().strip()
        if not key.startswith("ne_"):
            raise SystemExit("error: expected an API key (ne_…) on stdin")
        if not args.dry_run:
            from .envfile import write_env_var
            env_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_env_var(str(env_file), KEY_VAR, key)
            print(f"key {key[:10]}… written to {env_file}")
    elif args.keep_key and read_env_key(env_file):
        print(f"keeping the key already in {env_file}")
    elif not local:
        raise SystemExit("error: the service is on another Mac, so its key comes from there: create one on its web page "
                         "(MCP tab → Show the key once) and pass it with --key-stdin")
    elif not args.dry_run:
        made = make_key(config, args.name, scopes, args.owner, env_file, args.expires_days)
        rec = made["record"]
        print(f"created key {rec['name']} ({','.join(rec['scopes'])}) for {made['owner']}, "
              f"{rec['prefix']}… written to {env_file}")
        if made["revoked"]:
            print(f"revoked the older key(s) named {rec['name']}: " + ", ".join(p + "…" for p in made["revoked"]))

    # 2. the clients
    ok = True
    for c in clients:
        if c == "claude-code":
            ok &= register_claude_code(args.server_name, client_args, args.claude_scope, args.dry_run)
        elif c == "claude-desktop":
            ok &= register_claude_desktop(args.server_name, client_args, args.dry_run)
        else:
            print_config(args.server_name, client_args)

    # 3. does it work?
    if not args.dry_run:
        print()
        result = check(url, env_file)
        if result != 0:
            return result
    return 0 if ok else 1


def check(url: Optional[str], env_file, out=print) -> int:
    from .mcp_server import Api, ApiError, NotesMcp, Unreachable, resolve
    base, key, path, _ = resolve(url, str(env_file) if env_file else None, False)
    if not key:
        out(f"no API key: {KEY_VAR} isn't set and isn't in {path} (notes-exporter mcp setup)")
        return 1
    api = Api(base, key, timeout=15)
    try:
        health = api.json("GET", "/api/health")
        me = api.json("GET", "/api/auth/me")
    except Unreachable as e:
        out(str(e))
        return 2
    except ApiError as e:
        out(f"the service at {base} refused the key in {path}: {e.status} {e.detail}")
        return 1
    tools = [t["name"] for t in NotesMcp(api).tools()]
    out(f"service {base}: notes-exporter {health.get('version')}")
    out(f"key {me.get('key_prefix') or ''}… of {me.get('username')}: scopes {','.join(me.get('scopes', []))}")
    out(f"tools: {', '.join(tools)}")
    if "write" in me.get("scopes", []):
        try:
            w = api.json("GET", "/api/writes")
            if not w.get("allowed"):
                out("note: writing notes is off until an admin ticks Allow clients to write notes in Settings")
        except ApiError:
            pass
    return 0


def uninstall(args, config: Config) -> int:
    clients = args.client or list(CLIENTS[:2])
    for c in clients:
        if c == "claude-code":
            exe = claude_bin()
            if exe:
                r = subprocess.run([exe, "mcp", "remove", "--scope", args.claude_scope, args.server_name],
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
                print(f"Claude Code: {'removed' if r.returncode == 0 else 'not registered'} {args.server_name!r}")
        elif c == "claude-desktop":
            path = desktop_config_path()
            data = _load_desktop(path)
            if args.server_name in (data.get("mcpServers") or {}):
                del data["mcpServers"][args.server_name]
                _write_json_atomic(path, data)
                print(f"Claude Desktop: removed {args.server_name!r} from {path}")
    if args.keep_key:
        return 0
    from .auth import AuthStore
    store = AuthStore(config)
    gone = [k for k in store.list_keys() if k["name"] == args.name]
    for k in gone:
        store.delete_key(k["id"])
    print(f"revoked {len(gone)} key(s) named {args.name!r}" + (": " + ", ".join(k["prefix"] + "…" for k in gone) if gone else ""))
    return 0


def add_parser(sub) -> None:
    m = sub.add_parser("mcp", help="the MCP server for AI assistants (Claude Code, Claude Desktop, …)")
    ms = m.add_subparsers(dest="action", required=True)

    s = ms.add_parser("serve", help="run the MCP server on stdio (what an MCP client starts)")
    s.add_argument("--url", help="the service (default this Mac's, http://127.0.0.1:8790)")
    s.add_argument("--env-file", help="where the API key is (default <state dir>/mcp.env)")
    s.add_argument("--read-only", action="store_true", help="only the reading tools, whatever the key may do")

    st = ms.add_parser("setup", help="make the MCP key and register the server with Claude Code / Claude Desktop")
    st.add_argument("--client", action="append", choices=CLIENTS,
                    help="where to register it (repeat; default: Claude Code and Claude Desktop when present, else print)")
    st.add_argument("--write", action="store_true",
                    help="let the assistant change and create notes (the write scope; the admin must also allow writes)")
    st.add_argument("--no-run", action="store_true", help="don't let it start exports (no run scope)")
    st.add_argument("--read-only", action="store_true", help="register the server with --read-only")
    st.add_argument("--name", default=DEFAULT_KEY_NAME, help=f"the API key's name (default {DEFAULT_KEY_NAME})")
    st.add_argument("--server-name", default=DEFAULT_SERVER_NAME,
                    help=f"the MCP server's name in the client (default {DEFAULT_SERVER_NAME})")
    st.add_argument("--owner", help="the key's owner (default: the only admin)")
    st.add_argument("--expires-days", type=int)
    st.add_argument("--url", help="a service on another Mac (needs --key-stdin)")
    st.add_argument("--env-file", help="where to keep the key (default <state dir>/mcp.env)")
    st.add_argument("--key-stdin", action="store_true", help="read the key from stdin instead of making one")
    st.add_argument("--keep-key", action="store_true", help="keep the key already in the env file")
    st.add_argument("--claude-scope", choices=["user", "project", "local"], default="user",
                    help="Claude Code's config scope (default user: every project)")
    st.add_argument("--dry-run", action="store_true")

    c = ms.add_parser("check", help="check the MCP server's key against the service")
    c.add_argument("--url")
    c.add_argument("--env-file")

    u = ms.add_parser("uninstall", help="unregister the server and revoke its key")
    u.add_argument("--client", action="append", choices=CLIENTS[:2])
    u.add_argument("--name", default=DEFAULT_KEY_NAME)
    u.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    u.add_argument("--claude-scope", choices=["user", "project", "local"], default="user")
    u.add_argument("--keep-key", action="store_true", help="unregister only; leave the key")


def run(args, config: Config) -> int:
    if args.action == "serve":
        from .mcp_server import main
        return main(url=args.url, env_file=args.env_file, read_only=args.read_only)
    if args.action == "setup":
        return setup(args, config)
    if args.action == "check":
        return check(args.url, args.env_file)
    return uninstall(args, config)
