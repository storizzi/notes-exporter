"""Generated passwords kept in the login Keychain, through ``security``.

The password goes to ``security -i`` on its standard input, never on a command
line (where ``ps`` would show it), and is read back over a pipe to make sure
it was stored. It is never printed. ``NOTES_SERVICE_SECURITY_BIN`` names the
binary (tests point it at a fake).
"""

import secrets
import subprocess

from .config import Config

_UNSAFE = set('"\\\n\r')


class KeychainError(RuntimeError):
    pass


def generate_password(config: Config) -> str:
    n = max(config.generated_password_bytes, config.min_password_length)
    while True:
        pw = secrets.token_urlsafe(n)
        if not pw.startswith("-") and len(pw) >= config.min_password_length:
            return pw


def _quoted(value: str, what: str) -> str:
    if not value or _UNSAFE & set(value):
        raise KeychainError(f"the {what} can't contain quotes, backslashes or line breaks")
    return f'"{value}"'


def _scrub(text: str, password: str) -> str:
    return (text or "").replace(password, "****").strip()


def store_password(config: Config, account: str, service: str, password: str) -> None:
    """Add or update a generic password (account + service) in the default Keychain."""
    line = (f"add-generic-password -U -a {_quoted(account, 'user name')} -s {_quoted(service, 'Keychain service')}"
            f" -l {_quoted(f'notes-exporter ({account})', 'label')} -w {_quoted(password, 'password')}\n")
    try:
        r = subprocess.run([config.security_bin, "-i"], input=line, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KeychainError(f"couldn't run {config.security_bin}: {e.__class__.__name__}")
    err = _scrub(r.stderr, password)
    if r.returncode != 0 or err:
        raise KeychainError(f"security couldn't store the password: {err or f'exit {r.returncode}'}")
    try:
        back = subprocess.run([config.security_bin, "find-generic-password", "-a", account, "-s", service, "-w"],
                              capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KeychainError(f"couldn't read the password back: {e.__class__.__name__}")
    if back.returncode != 0 or back.stdout.rstrip("\n") != password:
        raise KeychainError("the Keychain didn't keep the password (reading it back gave something else)")
