"""``notes-exporter`` command line: serve, users, API keys, the LaunchAgent."""

import argparse
import getpass
import json
import sys
from datetime import datetime, timedelta, timezone

from .config import Config


def _password(args, prompt="Password: ") -> str:
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass(prompt)
    if getpass.getpass("Again: ") != first:
        raise SystemExit("the passwords differ")
    return first


def cmd_serve(args, config: Config) -> int:
    import uvicorn
    from .app import create_app

    if not config.is_loopback_bind():
        if not config.allow_remote:
            print(f"refusing to listen on {config.host}: only loopback by default. Add --allow-remote "
                  "(or NOTES_SERVICE_ALLOW_REMOTE=true) and put HTTPS in front of it.", file=sys.stderr)
            return 2
        print(f"WARNING: listening on {config.host}:{config.port} beyond this Mac, over plain HTTP. "
              "Put a reverse proxy with HTTPS in front of it.", file=sys.stderr)
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level=args.log_level,
                proxy_headers=False, server_header=False)
    return 0


def cmd_user(args, config: Config) -> int:
    from .auth import AuthError, AuthStore
    store = AuthStore(config)
    try:
        if args.action == "add":
            role = "admin" if args.admin else args.role
            user = store.create_user(args.name, _password(args), role)
            print(f"added {user['username']} ({user['role']})")
        elif args.action == "list":
            for u in store.list_users():
                print(f"{u['username']:<24} {u['role']:<7} {u['id']}  created {u['created_at']}")
        elif args.action == "passwd":
            user = store.find_user(args.name) or _missing("user", args.name)
            store.set_password(user["id"], _password(args, "New password: "))
            print(f"password changed for {user['username']} (their sessions are signed out)")
        elif args.action == "remove":
            user = store.find_user(args.name) or _missing("user", args.name)
            store.delete_user(user["id"])
            print(f"removed {user['username']} and their API keys")
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _missing(what, ref):
    raise SystemExit(f"no {what} {ref!r}")


def cmd_apikey(args, config: Config) -> int:
    from .auth import AuthError, AuthStore
    store = AuthStore(config)
    try:
        if args.action == "create":
            if args.owner:
                owner = store.find_user(args.owner) or _missing("user", args.owner)
            else:
                admins = [u for u in store.list_users() if u["role"] == "admin"]
                if len(admins) != 1:
                    raise SystemExit("name the key's owner with --owner USER")
                owner = admins[0]
            expires = None
            if args.expires_days:
                expires = (datetime.now(timezone.utc) + timedelta(days=args.expires_days)).isoformat(timespec="seconds")
            record, key = store.create_key(args.name, args.scopes, owner["id"], expires)
            print(f"created {record['name']} ({','.join(record['scopes'])}) owned by {owner['username']}")
            print("The key is shown once; store it now:")
            print(key)
        elif args.action == "list":
            users = {u["id"]: u["username"] for u in store.list_users()}
            for k in store.list_keys():
                print(f"{k['prefix']}…  {k['name']:<20} {','.join(k['scopes']):<15} "
                      f"owner {users.get(k['owner_user_id'], '?'):<12} last used {k['last_used_at'] or 'never'}"
                      f"  id {k['id']}")
        elif args.action == "revoke":
            key = store.find_key(args.ref) or _missing("API key", args.ref)
            store.delete_key(key["id"])
            print(f"revoked {key['name']} ({key['prefix']}…)")
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_service(args, config: Config) -> int:
    from . import launchagent
    if args.action == "install":
        return launchagent.install(config, replace_legacy=args.replace_legacy, dry_run=args.dry_run)
    if args.action == "uninstall":
        return launchagent.uninstall()
    st = launchagent.status(config)
    if args.json:
        print(json.dumps(st, indent=2))
    else:
        print(f"{st['label']}: {'installed' if st['installed'] else 'not installed'}, "
              f"{'loaded' if st['loaded'] else 'not loaded'}"
              + (f", {st['state']}" if st['state'] else "") + (f", pid {st['pid']}" if st['pid'] else ""))
        lg = st["legacy_job"]
        if lg["plist_present"] or lg["loaded"]:
            print(f"old job {lg['label']}: {'loaded' if lg['loaded'] else 'not loaded'}"
                  f"{', plist present' if lg['plist_present'] else ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notes-exporter", description="notes-exporter service (see SERVICE-API.md)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the HTTP service")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--allow-remote", action="store_true", default=None,
                   help="allow listening beyond loopback (put HTTPS in front of it)")
    s.add_argument("--log-level", default="info")

    u = sub.add_parser("user", help="manage users")
    us = u.add_subparsers(dest="action", required=True)
    a = us.add_parser("add")
    a.add_argument("name")
    a.add_argument("--admin", action="store_true")
    a.add_argument("--role", choices=["admin", "reader"], default="reader")
    a.add_argument("--password-stdin", action="store_true")
    us.add_parser("list")
    pw = us.add_parser("passwd")
    pw.add_argument("name")
    pw.add_argument("--password-stdin", action="store_true")
    rm = us.add_parser("remove")
    rm.add_argument("name")

    k = sub.add_parser("apikey", help="manage API keys")
    ks = k.add_subparsers(dest="action", required=True)
    c = ks.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--scopes", default="read")
    c.add_argument("--owner")
    c.add_argument("--expires-days", type=int)
    ks.add_parser("list")
    r = ks.add_parser("revoke")
    r.add_argument("ref", help="the key's id or prefix")

    sv = sub.add_parser("service", help="the LaunchAgent that keeps the service running")
    ss = sv.add_subparsers(dest="action", required=True)
    i = ss.add_parser("install")
    i.add_argument("--replace-legacy", action="store_true",
                   help="unload the old com.<user>.notes_exporter job and move its plist aside")
    i.add_argument("--dry-run", action="store_true")
    ss.add_parser("uninstall")
    st = ss.add_parser("status")
    st.add_argument("--json", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.command == "serve":
        overrides = {"host": args.host, "port": args.port, "allow_remote": args.allow_remote}
    config = Config.from_env(**overrides)
    handler = {"serve": cmd_serve, "user": cmd_user, "apikey": cmd_apikey, "service": cmd_service}[args.command]
    return handler(args, config)
