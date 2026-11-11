"""Users, sessions and API keys (auth.sqlite).

* Passwords: bcrypt.
* Sessions: JWT HS256 signed with a secret generated into auth.sqlite; each
  token names a session row (``sid``), so logging out ends it.
* API keys: ``ne_`` + 32 random bytes (urlsafe). Only the SHA-256 is stored,
  with the first 10 characters as ``prefix`` so a key can be recognised.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Set

import bcrypt
import jwt

from .config import Config
from .db import Database

ROLES = ("admin", "reader")
SCOPES = ("read", "run", "admin")
ROLE_SCOPES = {"admin": {"read", "run", "admin"}, "reader": {"read", "run"}}
KEY_PREFIX = "ne_"
PREFIX_LENGTH = 10
_USERNAME = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
BCRYPT_MAX_BYTES = 72

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    password_changed_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    expires_at TEXT
);
"""


class AuthError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_scopes(value) -> List[str]:
    items = value.split(",") if isinstance(value, str) else list(value or [])
    scopes = [s.strip() for s in items if s and s.strip()]
    bad = [s for s in scopes if s not in SCOPES]
    if bad:
        raise AuthError(f"unknown scopes {bad}; use {list(SCOPES)}")
    if not scopes:
        raise AuthError("an API key needs at least one scope")
    return [s for s in SCOPES if s in scopes]


@dataclass
class Principal:
    kind: str                      # "user" or "key"
    user_id: str
    username: str
    role: str
    scopes: Set[str] = field(default_factory=set)
    session_id: Optional[str] = None
    key_id: Optional[str] = None
    key_prefix: Optional[str] = None

    @property
    def label(self) -> str:
        return f"key:{self.key_prefix}" if self.kind == "key" else f"user:{self.username}"

    def public(self) -> dict:
        d = {"kind": self.kind, "user_id": self.user_id, "username": self.username,
             "role": self.role, "scopes": [s for s in SCOPES if s in self.scopes]}
        if self.kind == "key":
            d.update(key_id=self.key_id, key_prefix=self.key_prefix)
        return d


class LoginLimiter:
    """Failed logins per client address in a sliding window."""

    def __init__(self, max_attempts: int, window_seconds: float, clock=time.monotonic):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.clock = clock
        self._fails: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: Deque[float]) -> None:
        cutoff = self.clock() - self.window
        while q and q[0] < cutoff:
            q.popleft()

    def blocked(self, ip: str) -> bool:
        with self._lock:
            q = self._fails[ip]
            self._trim(q)
            return len(q) >= self.max_attempts

    def failed(self, ip: str) -> None:
        with self._lock:
            self._fails[ip].append(self.clock())

    def succeeded(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


class AuthStore:
    def __init__(self, config: Config):
        self.config = config
        config.ensure_home()
        self.db = Database(config.auth_db, SCHEMA)
        self._secret = self._load_secret()
        # A real bcrypt hash to compare against for unknown users (constant-ish timing).
        self._dummy_hash = bcrypt.hashpw(b"not-a-password", bcrypt.gensalt(self.config.bcrypt_rounds)).decode()

    def _load_secret(self) -> str:
        row = self.db.one("SELECT value FROM meta WHERE key='jwt_secret'")
        if row:
            return row["value"]
        secret = secrets.token_urlsafe(48)
        self.db.run("INSERT OR IGNORE INTO meta(key, value) VALUES('jwt_secret', ?)", (secret,))
        return self.db.one("SELECT value FROM meta WHERE key='jwt_secret'")["value"]

    # ---- users ----
    def _check_password(self, password: str) -> bytes:
        if not isinstance(password, str) or len(password) < self.config.min_password_length:
            raise AuthError(f"passwords need at least {self.config.min_password_length} characters")
        raw = password.encode("utf-8")
        if len(raw) > BCRYPT_MAX_BYTES:
            raise AuthError(f"passwords may be at most {BCRYPT_MAX_BYTES} bytes")
        return raw

    @staticmethod
    def public_user(row: dict) -> dict:
        return {k: row[k] for k in ("id", "username", "role", "created_at", "password_changed_at")}

    def user_count(self) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM users")["n"]

    def admin_count(self) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM users WHERE role='admin'")["n"]

    def create_user(self, username: str, password: str, role: str = "reader") -> dict:
        if not _USERNAME.match(username or ""):
            raise AuthError("usernames are 1-64 letters, digits, '.', '_', '-' or '@'")
        if role not in ROLES:
            raise AuthError(f"role must be one of {list(ROLES)}")
        raw = self._check_password(password)
        if self.get_user_by_name(username):
            raise AuthError(f"user {username!r} already exists")
        row = {"id": uuid.uuid4().hex, "username": username,
               "password_hash": bcrypt.hashpw(raw, bcrypt.gensalt(self.config.bcrypt_rounds)).decode(),
               "role": role, "created_at": now_iso(), "password_changed_at": None}
        self.db.run("INSERT INTO users(id, username, password_hash, role, created_at) VALUES(?,?,?,?,?)",
                    (row["id"], username, row["password_hash"], role, row["created_at"]))
        return self.public_user(row)

    def create_first_admin(self, username: str, password: str) -> dict:
        """Only while there are no users at all (the setup page)."""
        with self.db._lock:  # check and insert as one step within this process
            if self.user_count():
                raise AuthError("setup is already done")
            return self.create_user(username, password, "admin")

    def list_users(self) -> List[dict]:
        return [self.public_user(r) for r in self.db.all("SELECT * FROM users ORDER BY username")]

    def get_user(self, user_id: str) -> Optional[dict]:
        return self.db.one("SELECT * FROM users WHERE id=?", (user_id,))

    def get_user_by_name(self, username: str) -> Optional[dict]:
        return self.db.one("SELECT * FROM users WHERE username=?", (username,))

    def find_user(self, ref: str) -> Optional[dict]:
        return self.get_user(ref) or self.get_user_by_name(ref)

    def set_password(self, user_id: str, password: str) -> None:
        raw = self._check_password(password)
        if not self.db.run("UPDATE users SET password_hash=?, password_changed_at=? WHERE id=?",
                           (bcrypt.hashpw(raw, bcrypt.gensalt(self.config.bcrypt_rounds)).decode(), now_iso(), user_id)):
            raise AuthError("no such user")
        self.revoke_user_sessions(user_id)

    def set_role(self, user_id: str, role: str) -> None:
        if role not in ROLES:
            raise AuthError(f"role must be one of {list(ROLES)}")
        user = self.get_user(user_id)
        if not user:
            raise AuthError("no such user")
        if user["role"] == "admin" and role != "admin" and self.admin_count() <= 1:
            raise AuthError("the last admin can't be demoted")
        self.db.run("UPDATE users SET role=? WHERE id=?", (role, user_id))

    def delete_user(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if not user:
            raise AuthError("no such user")
        if user["role"] == "admin" and self.admin_count() <= 1:
            raise AuthError("the last admin can't be removed")
        self.db.run("DELETE FROM users WHERE id=?", (user_id,))

    def verify_password(self, username: str, password: str) -> Optional[dict]:
        user = self.get_user_by_name(username or "")
        raw = (password or "").encode("utf-8")[:BCRYPT_MAX_BYTES]
        target = (user["password_hash"] if user else self._dummy_hash).encode()
        ok = bcrypt.checkpw(raw, target)
        return user if user and ok else None

    # ---- sessions ----
    def create_session(self, user: dict) -> dict:
        sid = uuid.uuid4().hex
        now = time.time()
        exp = now + self.config.session_hours * 3600
        self.db.run("INSERT INTO sessions(id, user_id, created_at, expires_at) VALUES(?,?,?,?)",
                    (sid, user["id"], now, exp))
        self.db.run("DELETE FROM sessions WHERE expires_at < ?", (now,))
        token = jwt.encode({"sub": user["id"], "sid": sid, "iat": int(now), "exp": int(exp)},
                           self._secret, algorithm="HS256")
        return {"token": token,
                "expires_at": datetime.fromtimestamp(int(exp), timezone.utc).isoformat()}

    def revoke_session(self, sid: str) -> None:
        self.db.run("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))

    def revoke_user_sessions(self, user_id: str) -> None:
        self.db.run("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))

    def principal_from_token(self, token: str) -> Optional[Principal]:
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"],
                                options={"require": ["sub", "sid", "exp"]})
        except jwt.PyJWTError:
            return None
        row = self.db.one("SELECT * FROM sessions WHERE id=? AND user_id=?", (claims["sid"], claims["sub"]))
        if not row or row["revoked"] or row["expires_at"] < time.time():
            return None
        user = self.get_user(claims["sub"])
        if not user:
            return None
        return Principal("user", user["id"], user["username"], user["role"],
                         set(ROLE_SCOPES[user["role"]]), session_id=claims["sid"])

    # ---- API keys ----
    @staticmethod
    def public_key(row: dict) -> dict:
        d = {k: row[k] for k in ("id", "name", "prefix", "created_at", "last_used_at", "expires_at",
                                 "owner_user_id")}
        d["scopes"] = row["scopes"].split(",")
        return d

    def create_key(self, name: str, scopes, owner_user_id: str, expires_at: Optional[str] = None):
        name = (name or "").strip()
        if not name or len(name) > 100:
            raise AuthError("an API key needs a name (at most 100 characters)")
        scope_list = parse_scopes(scopes)
        owner = self.get_user(owner_user_id)
        if not owner:
            raise AuthError("no such owner")
        if not set(scope_list) <= ROLE_SCOPES[owner["role"]]:
            raise AuthError(f"a {owner['role']} can't own a key with scopes {scope_list}")
        if expires_at:
            exp = _parse_iso(expires_at)
            if exp is None or exp <= datetime.now(timezone.utc):
                raise AuthError("expires_at must be a future ISO 8601 date")
            expires_at = exp.isoformat(timespec="seconds")
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        row = {"id": uuid.uuid4().hex, "name": name, "prefix": key[:PREFIX_LENGTH],
               "key_hash": hash_key(key), "scopes": ",".join(scope_list),
               "owner_user_id": owner_user_id, "created_at": now_iso(),
               "last_used_at": None, "expires_at": expires_at}
        self.db.run("INSERT INTO api_keys(id, name, prefix, key_hash, scopes, owner_user_id, created_at, expires_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (row["id"], name, row["prefix"], row["key_hash"], row["scopes"], owner_user_id,
                     row["created_at"], expires_at))
        return self.public_key(row), key

    def list_keys(self) -> List[dict]:
        return [self.public_key(r) for r in self.db.all("SELECT * FROM api_keys ORDER BY created_at")]

    def find_key(self, ref: str) -> Optional[dict]:
        return (self.db.one("SELECT * FROM api_keys WHERE id=?", (ref,))
                or self.db.one("SELECT * FROM api_keys WHERE prefix=?", (ref,)))

    def delete_key(self, key_id: str) -> bool:
        return bool(self.db.run("DELETE FROM api_keys WHERE id=?", (key_id,)))

    def principal_from_key(self, key: str) -> Optional[Principal]:
        if not key.startswith(KEY_PREFIX):
            return None
        row = self.db.one("SELECT * FROM api_keys WHERE key_hash=?", (hash_key(key),))
        if not row or not hmac.compare_digest(row["key_hash"], hash_key(key)):
            return None
        exp = _parse_iso(row["expires_at"])
        if exp and exp <= datetime.now(timezone.utc):
            return None
        owner = self.get_user(row["owner_user_id"])
        if not owner:
            return None
        last = _parse_iso(row["last_used_at"])
        if last is None or (datetime.now(timezone.utc) - last).total_seconds() >= self.config.key_touch_seconds:
            self.db.run("UPDATE api_keys SET last_used_at=? WHERE id=?", (now_iso(), row["id"]))
        scopes = set(row["scopes"].split(",")) & ROLE_SCOPES[owner["role"]]
        return Principal("key", owner["id"], owner["username"], owner["role"], scopes,
                         key_id=row["id"], key_prefix=row["prefix"])

    def authenticate(self, credential: str) -> Optional[Principal]:
        if not credential:
            return None
        if credential.startswith(KEY_PREFIX):
            return self.principal_from_key(credential)
        return self.principal_from_token(credential)
