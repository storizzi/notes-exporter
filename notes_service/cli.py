"""``notes-exporter`` command line: serve, users, API keys, the Notes permission, the LaunchAgent."""

import argparse
import getpass
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import __version__
from .config import Config

DEFAULT_ENV_VAR = "NOTES_EXPORTER_API_KEY"


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


def _new_password(args, config: Config, prompt="Password: ") -> str:
    if getattr(args, "generate_password", False):
        if not args.keychain:
            raise SystemExit("--generate-password needs --keychain: a generated password is never printed")
        from .keychain import generate_password
        return generate_password(config)
    return _password(args, prompt)


def _keychain(args, config: Config, username: str, password: str) -> bool:
    """Store the password in the login Keychain when asked; False (and a message) if that failed."""
    if not getattr(args, "keychain", False):
        return True
    from .keychain import KeychainError, store_password
    service = args.keychain_service or config.keychain_service
    try:
        store_password(config, username, service, password)
    except KeychainError as e:
        print(f"error: {e}", file=sys.stderr)
        return False
    print(f'password for {username} stored in your login Keychain as "{service}" (open the Passwords app to see it)')
    return True


def cmd_user(args, config: Config) -> int:
    from .auth import AuthError, AuthStore
    store = AuthStore(config)
    try:
        if args.action == "add":
            role = "admin" if args.admin else args.role
            password = _new_password(args, config)
            store.check_new_user(args.name, password, role)   # refuse before touching the Keychain
            if not _keychain(args, config, args.name, password):
                return 1
            user = store.create_user(args.name, password, role)
            print(f"added {user['username']} ({user['role']})")
        elif args.action == "list":
            for u in store.list_users():
                print(f"{u['username']:<24} {u['role']:<7} {u['id']}  created {u['created_at']}")
        elif args.action == "passwd":
            user = store.find_user(args.name) or _missing("user", args.name)
            password = _new_password(args, config, "New password: ")
            store._check_password(password)
            if not _keychain(args, config, user["username"], password):
                return 1
            store.set_password(user["id"], password)
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
            env_var = DEFAULT_ENV_VAR if args.env_var is None else args.env_var
            if args.env_var is not None and not args.env_file:
                raise SystemExit("--env-var goes with --env-file")
            if args.env_file:
                from .envfile import NAME_RE
                if not NAME_RE.match(env_var):
                    raise SystemExit(f"{env_var!r} isn't an environment variable name ([A-Z_][A-Z0-9_]*)")
            record, key = store.create_key(args.name, args.scopes, owner["id"], expires)
            scopes = ",".join(record["scopes"])
            if args.env_file:
                from .envfile import write_env_var
                try:
                    written = write_env_var(args.env_file, env_var, key)
                except (OSError, ValueError) as e:
                    store.delete_key(record["id"])
                    print(f"error: couldn't write {args.env_file} ({e.__class__.__name__}: {e}); "
                          "the key was not kept", file=sys.stderr)
                    return 1
                print(f"created {record['name']} ({scopes}), key {record['prefix']}… written to {written} as {env_var}")
            else:
                print(f"created {record['name']} ({scopes}) owned by {owner['username']}")
                print("The key is shown once; store it now:")
                print(key)
            if args.replace:
                old = [k for k in store.list_keys() if k["owner_user_id"] == owner["id"]
                       and k["name"] == record["name"] and k["id"] != record["id"]]
                for k in old:
                    store.delete_key(k["id"])
                if old:
                    print(f"revoked {len(old)} older key(s) named {record['name']}: "
                          + ", ".join(k["prefix"] + "…" for k in old))
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


def _admin_for_cli(store, name: Optional[str]) -> dict:
    if name:
        user = store.find_user(name) or _missing("user", name)
        if user["role"] != "admin":
            raise SystemExit(f"{user['username']} isn't an admin")
        return user
    admins = [u for u in store.list_users() if u["role"] == "admin"]
    if len(admins) != 1:
        raise SystemExit("say which admin with --as USER" if admins else
                         "there is no admin yet: notes-exporter user add NAME --admin")
    return store.get_user(admins[0]["id"])


HERE_NOTE = ("This asks for the program running this command (your terminal, usually), not for the "
             "service: the service runs as its own process and needs its own permission "
             "(notes-exporter permission request, with the service running).")


def _print_permission(result: dict) -> None:
    fda = result.get("full_disk_access")
    print(f"automation: {result.get('automation')}")
    print(f"full disk access: {'unknown' if fda is None else ('yes' if fda else 'no (only needed for tags)')}")


def cmd_permission(args, config: Config) -> int:
    from . import permissions
    if args.here:
        print(HERE_NOTE)
        if args.action == "request":
            print("macOS is asking on this Mac — click Allow")
            word = permissions.request_automation(config)
        else:
            word = permissions.automation_state(config)
        _print_permission({"automation": word, "full_disk_access": permissions.full_disk_access()})
        return 0 if word == "allowed" else 3

    import httpx
    from .auth import AuthStore
    store = AuthStore(config)
    user = _admin_for_cli(store, getattr(args, "as_user", None))
    session = store.open_session(user, hours=config.cli_session_minutes / 60)
    base = config.local_url()
    headers = {"Authorization": f"Bearer {session['token']}"}
    try:
        with httpx.Client(base_url=base, headers=headers,
                          timeout=config.permission_request_timeout_seconds + 30) as client:
            if args.action == "request":
                client.get("/api/health", timeout=10).raise_for_status()
                print("macOS is asking on this Mac — click Allow")
                r = client.post("/api/admin/permission/request")
            else:
                r = client.get("/api/admin/permission", params={"refresh": "true" if args.refresh else "false"})
    except httpx.ConnectError:
        print(f"error: no service at {base}: start the service first — the permission belongs to the process "
              "that asks (notes-exporter serve, or notes-exporter service install). "
              "--here asks for this terminal instead.", file=sys.stderr)
        return 2
    except httpx.HTTPError as e:
        print(f"error: {e.__class__.__name__} talking to {base}", file=sys.stderr)
        return 2
    finally:
        store.revoke_session(session["session_id"])
    if r.status_code != 200:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:200]
        print(f"error: the service answered {r.status_code}: {detail}", file=sys.stderr)
        return 1
    result = r.json()
    _print_permission(result)
    return 0 if result.get("automation") == "allowed" else 3


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
    p.add_argument("--version", action="version", version=f"notes-exporter {__version__}")
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
    us.add_parser("list")
    pw = us.add_parser("passwd")
    pw.add_argument("name")
    for sp in (a, pw):
        sp.add_argument("--password-stdin", action="store_true")
        sp.add_argument("--generate-password", action="store_true",
                        help="make a strong password (never printed; needs --keychain)")
        sp.add_argument("--keychain", action="store_true", help="store the password in your login Keychain")
        sp.add_argument("--keychain-service", help="the Keychain item's service name "
                        "(default NOTES_SERVICE_KEYCHAIN_SERVICE, notes-exporter)")
    rm = us.add_parser("remove")
    rm.add_argument("name")

    k = sub.add_parser("apikey", help="manage API keys")
    ks = k.add_subparsers(dest="action", required=True)
    c = ks.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--scopes", default="read")
    c.add_argument("--owner")
    c.add_argument("--expires-days", type=int)
    c.add_argument("--env-file", help="write the key into this env file instead of printing it (mode 0600)")
    c.add_argument("--env-var", help=f"the variable to set in --env-file (default {DEFAULT_ENV_VAR})")
    c.add_argument("--replace", action="store_true",
                   help="then revoke the owner's other keys with the same name")
    ks.add_parser("list")
    r = ks.add_parser("revoke")
    r.add_argument("ref", help="the key's id or prefix")

    pm = sub.add_parser("permission", help="macOS permission to automate Notes (asked by the running service)")
    ps = pm.add_subparsers(dest="action", required=True)
    for name, text in (("status", "what the service may do now"),
                       ("request", "make macOS ask (on this Mac) for the service to automate Notes")):
        sp = ps.add_parser(name, help=text)
        sp.add_argument("--as", dest="as_user", help="the admin to act as (default: the only admin)")
        sp.add_argument("--here", action="store_true",
                        help="check / ask for this terminal instead of the service")
    ps.choices["status"].add_argument("--refresh", action="store_true", help="check again now")

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
    handler = {"serve": cmd_serve, "user": cmd_user, "apikey": cmd_apikey, "permission": cmd_permission,
               "service": cmd_service}[args.command]
    return handler(args, config)
