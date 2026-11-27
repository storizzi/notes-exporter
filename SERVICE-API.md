# Service API <!-- omit from toc -->

notes-exporter can run as a long-running **service**: it runs and schedules its
own exports and serves the results over an authenticated HTTP API, so a media
server (FunHoard), a backup job or a script can use your notes without running
the exporter itself. This page is the API contract (version 1) and the guide to
running it.

Within `api_version` 1 fields are only ever **added**; clients ignore fields
they don't know. The manifest the API serves is [INTEGRATION.md](INTEGRATION.md)'s
manifest version 1.

- [Quick start](#quick-start)
- [Running it](#running-it)
  - [The LaunchAgent](#the-launchagent)
  - [macOS permissions](#macos-permissions)
  - [Configuration (environment)](#configuration-environment)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [Health, setup and sign-in](#health-setup-and-sign-in)
  - [Status](#status)
  - [Manifest, notes and files](#manifest-notes-and-files)
  - [Runs](#runs)
  - [Admin: settings, users, API keys](#admin-settings-users-api-keys)
  - [Refusal reasons](#refusal-reasons)
- [Writing notes](#writing-notes)
  - [Backups before a change](#backups-before-a-change)
  - [Deleting a note](#deleting-a-note)
  - [The mass-change limit](#the-mass-change-limit)
  - [The approval list](#the-approval-list)
  - [Write refusals](#write-refusals)
- [Sign-in links for the web page](#sign-in-links-for-the-web-page)
- [Updates](#updates)
- [Formats and EPUB books](#formats-and-epub-books)
- [Change detection for clients](#change-detection-for-clients)
- [Security notes](#security-notes)
- [Safety](#safety)

## Quick start

```bash
cd notes-exporter
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. The first admin, with a generated password kept in your login Keychain
./notes-exporter user add simon --admin --generate-password --keychain

# 2. Start the service (http://127.0.0.1:8790/)
./notes-exporter serve

# 3. In another terminal, at the Mac: let the service automate Notes (click Allow)
./notes-exporter permission request

# 4. A key for FunHoard, written straight into its env file (never printed)
./notes-exporter apikey create --name FunHoard --scopes read,run,settings \
    --env-file ~/dev/storizzi/repos/apps/desktop/media-server/backend/.env --env-var NOTES_EXPORTER_API_KEY

# 5. Keep it running after you log in (stop the `serve` from step 2 first)
./notes-exporter service install --replace-legacy
./notes-exporter permission request     # again: now it is the LaunchAgent's process that asks
```

The password is in the Passwords app (or Keychain Access) under
`notes-exporter`; sign in to the web page with it, and check **Settings**
(export folder, formats, schedule). Step 3 belongs to whichever process runs the
exporter: a `serve` started in Terminal asks as Terminal, the LaunchAgent asks as
itself, so ask again after installing it ([permissions](#macos-permissions)).
The web page has the same button: **Ask macOS for access to Notes**.

With no user yet you can also create the first admin on the web page, but only
from the Mac itself (a loopback connection).

## Running it

```
notes-exporter serve [--host HOST] [--port PORT] [--allow-remote]
notes-exporter user add NAME [--admin | --role admin|reader] [--password-stdin]
                              [--generate-password --keychain [--keychain-service NAME]]
notes-exporter user passwd NAME [--password-stdin | --generate-password --keychain [--keychain-service NAME]]
notes-exporter user list | remove NAME
notes-exporter apikey create --name NAME [--scopes read,run,admin] [--owner USER] [--expires-days N]
                             [--env-file PATH [--env-var NAME]] [--replace]
notes-exporter apikey list | revoke ID|PREFIX
notes-exporter permission status [--refresh] | request   [--as ADMIN] [--here]
notes-exporter service install [--replace-legacy] [--dry-run] | uninstall | status [--json]
```

**Generated passwords.** `--generate-password` makes a random password (from
`secrets`, never starting with `-`) and needs `--keychain`, because it is never
printed. `--keychain` stores the password (generated or typed) in your login
Keychain as a generic password, service `notes-exporter`
(`--keychain-service`, `NOTES_SERVICE_KEYCHAIN_SERVICE`), account the user name,
label `notes-exporter (NAME)`: it is handed to `security -i` on its standard
input (never on a command line, where `ps` would show it) and read back to make
sure it is there. If the Keychain refuses, the user isn't created (or the
password isn't changed). Find it in the Passwords app.

**Keys into an env file.** `--env-file PATH` writes the new key into PATH as
`NOTES_EXPORTER_API_KEY=ne_…` (`--env-var` for another name, `[A-Z_][A-Z0-9_]*`)
instead of printing it: an existing `NAME=` or `export NAME=` line is replaced
in place (later duplicates dropped), else the line is appended; every other line
is kept byte for byte; the file is rewritten through a temporary file in the
same directory and left at mode 0600 (created 0600 if missing). The output shows
only the key's prefix. If the file can't be written the key is revoked again.
`--replace` then revokes the owner's other keys with the same name, so running
the same command again rotates the key.

**The Notes permission.** `permission request` asks the **running service** to
ask macOS (`POST /api/admin/permission/request`), because the grant belongs to
the process that asks; `permission status` shows what the service may do
(`--refresh` checks again now). Both sign in as an admin with a session made
from `auth.sqlite` for `NOTES_SERVICE_CLI_SESSION_MINUTES` (default 10) and
revoked when the command ends; `--as` names the admin when there is more than
one. With no service running they say "start the service first". `--here`
checks or asks for the program running the command instead (your terminal),
which is what a manual `exportnotes.zsh` run needs, not the service. Exit codes:
0 allowed, 3 not allowed, 2 no service, 1 an error.

`notes-exporter` (in the repository root) runs `python -m notes_service` with
`NOTES_SERVICE_PYTHON`, else `.venv/bin/python`, else `python3`.

The service listens on **127.0.0.1:8790** by default. Listening on anything
other than loopback needs `--allow-remote` (or `NOTES_SERVICE_ALLOW_REMOTE=true`)
and prints a warning: the service speaks plain HTTP, so put a reverse proxy with
HTTPS in front of it (Caddy, nginx) if other machines must reach it.

State lives in `~/Library/Application Support/notes-exporter/`
(`NOTES_SERVICE_HOME`), never in the export folder:

| File | What |
|---|---|
| `service.json` | the export settings (below) |
| `auth.sqlite` | users, sessions, API keys (hashes only) and the session-signing secret; mode 0600 |
| `runs/runs.sqlite`, `runs/<id>.ndjson`, `runs/<id>.log` | run records, each run's `--json-log` events and its human output |
| `logs/` | the LaunchAgent's stdout / stderr |

The export folder stays `~/Downloads/AppleNotesExport` unless you change it, so
an existing export keeps working (and keeps its flat layout: "Nested folders" is
off by default; see `reorganize_by_folder.py` before turning it on).

### The LaunchAgent

`notes-exporter service install` writes
`~/Library/LaunchAgents/com.storizzi.notes-exporter.plist` (RunAtLoad,
KeepAlive) running `python -m notes_service serve` from this checkout, and loads
it with `launchctl bootstrap gui/<uid>`. Any `NOTES_SERVICE_*` variables set when
you install are written into the plist. `--dry-run` prints the plan and the plist
without changing anything; `status` says whether it is installed and running;
`uninstall` unloads and removes it.

The older scheduled job made by `setup_launchd.py`
(`com.<user>.notes_exporter`, which runs the exporter itself every night) would
export into the same folder, so **install refuses while it exists**. Either
remove it yourself, or pass `--replace-legacy`: the installer prints what it will
do, unloads the old job and moves its plist to
`~/Library/Application Support/notes-exporter/legacy-launchagent/` (put it back
in `~/Library/LaunchAgents/` to restore it). Then set a schedule in the
service's settings (for example daily at `00:13`).

### macOS permissions

* **Automation (required).** macOS asks once whether the process running the
  export may control Notes; the grant belongs to that process (Terminal for a
  `serve` started in Terminal, the service's own Python under the LaunchAgent).
  Under the LaunchAgent there may be nobody at the Mac to click Allow; the
  service always runs the exporter with `--non-interactive`, so an unanswered
  prompt fails the run with exit code 3 instead of hanging. `GET /api/status`
  reports `permission.automation` using `notes_permission.py`, which asks macOS
  **without prompting**: `allowed`, `prompt` (macOS would ask), `denied`,
  `not-running` (Notes is not open, macOS can't tell) or `unknown(…)`.

  To grant it, sit at the Mac with the service running and either press **Ask
  macOS for access to Notes** on the web page's Status tab (shown to admins
  while automation is `prompt`, `not-running` or unknown) or run
  `notes-exporter permission request`. The service runs
  `notes_permission.py --ask` (AEDeterminePermissionToAutomateTarget with
  askUserIfNeeded=true; Notes is first opened in the background with
  `open -g -j -b com.apple.Notes` if it isn't running), macOS shows its dialog,
  and you click **Allow**. The request waits up to
  `NOTES_SERVICE_PERMISSION_REQUEST_TIMEOUT_SECONDS` (180) for the answer, then
  checks again. Do it again after `service install`, since the LaunchAgent is a
  different process from a `serve` in Terminal.

  A refused permission can't be asked for again: re-enable it in *System
  Settings > Privacy & Security > Automation* (the Python or Terminal entry,
  **Notes** ticked).
* **Writing to the export folder.** A folder the service's Python may not write
  to — on another drive, in Documents / Desktop / Downloads, or anywhere macOS's
  privacy settings (TCC) guard — fails with *Operation not permitted* even when
  its permission bits allow it. `GET /api/status` probes it by creating and
  removing a hidden empty file (`.notes-exporter-probe-…`) in the folder, or in
  the nearest folder above it before the first export made it, and reports
  `export_root_access`: `ok`, `denied` (macOS refuses it: allow the Python named
  in `export_root_problem` — the real path of the service's interpreter — in
  *System Settings → Privacy & Security → Full Disk Access*, or *Files and
  Folders* (Removable Volumes / Network Volumes) for a drive, then restart the
  service), `not_writable` (the folder's permissions, or a read-only drive),
  `missing` (its drive isn't connected) or `unknown`. A run into a folder that is
  `denied`, `not_writable` or `missing` fails at once saying so.
* **Full Disk Access (only for tags).** `--tags` reads Notes' database, which
  needs Full Disk Access for the same Python. `permission.full_disk_access` is
  `true` / `false` (checked by opening the TCC database read-only, which never
  prompts) or `null` when unknown.

### Configuration (environment)

Process settings are environment variables (the export settings are in
`service.json`, edited on the web page or with `PUT /api/admin/settings`). What
program runs and with which environment can only be set here, never over HTTP.

| Variable | Default | |
|---|---|---|
| `NOTES_SERVICE_HOME` | `~/Library/Application Support/notes-exporter` | state directory |
| `NOTES_SERVICE_HOST`, `NOTES_SERVICE_PORT` | `127.0.0.1`, `8790` | where to listen |
| `NOTES_SERVICE_ALLOW_REMOTE` | `false` | allow a non-loopback host |
| `NOTES_SERVICE_SESSION_HOURS` | `24` | session (JWT) lifetime |
| `NOTES_SERVICE_LOGIN_MAX_ATTEMPTS`, `NOTES_SERVICE_LOGIN_WINDOW_SECONDS` | `10`, `300` | failed sign-ins per client address before 429 |
| `NOTES_SERVICE_MIN_PASSWORD_LENGTH` | `8` | |
| `NOTES_SERVICE_BCRYPT_ROUNDS` | `12` | bcrypt cost |
| `NOTES_SERVICE_CANCEL_GRACE_SECONDS` | `10` | SIGTERM → SIGKILL on cancel |
| `NOTES_SERVICE_SCHEDULER` | `true` | run the schedule at all |
| `NOTES_SERVICE_SCHEDULER_TICK_SECONDS` | `30` | how often the schedule is checked |
| `NOTES_SERVICE_MIN_INTERVAL_MINUTES` | `5` | smallest allowed `interval_minutes` |
| `NOTES_SERVICE_PERMISSION_CHECK` | `true` | report `permission` (false: `unchecked`) |
| `NOTES_SERVICE_PERMISSION_CACHE_SECONDS`, `NOTES_SERVICE_PERMISSION_TIMEOUT_SECONDS` | `300`, `10` | |
| `NOTES_SERVICE_PERMISSION_HELPER` | `<repo>/notes_permission.py` | the permission helper (tests use a fake) |
| `NOTES_SERVICE_PERMISSION_REQUEST_TIMEOUT_SECONDS` | `180` | how long a permission request waits for someone to click Allow |
| `NOTES_SERVICE_PERMISSION_LAUNCH_WAIT_SECONDS` | `20` | how long a request waits for Notes to start |
| `NOTES_SERVICE_SECURITY_BIN` | `/usr/bin/security` | the Keychain tool (tests use a fake) |
| `NOTES_SERVICE_OPEN_BIN` | `/usr/bin/open` | what Settings → Show in Finder runs (tests use a fake) |
| `NOTES_SERVICE_KEYCHAIN` | (the login keychain) | the keychain a generated password goes into; by default `security login-keychain`'s answer, never the default keychain, which can be the System keychain (only root writes there — `security` then fails with -61) |
| `NOTES_SERVICE_KEYCHAIN_SERVICE` | `notes-exporter` | the Keychain item's service name |
| `NOTES_SERVICE_GENERATED_PASSWORD_BYTES` | `24` | random bytes in a generated password (32 characters) |
| `NOTES_SERVICE_CLI_SESSION_MINUTES` | `10` | the `permission` command's own short session |
| `NOTES_SERVICE_EXPORTER` | `<repo>/exportnotes.zsh` | the exporter to run |
| `NOTES_SERVICE_PYTHON` | the service's own Python | passed to the exporter as `--python` |
| `NOTES_SERVICE_EXPORTER_PATH` | `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | `PATH` of the exporter's clean environment |
| `NOTES_SERVICE_PASS_ENV` | — | comma-separated variables copied into the exporter's environment (never the sync ones) |
| `NOTES_SERVICE_FILE_CHUNK_BYTES` | `262144` | file streaming chunk |
| `NOTES_SERVICE_RUNS_KEEP` | `200` | finished runs kept (older records and logs removed) |
| `NOTES_SERVICE_PROGRESS_WRITE_SECONDS` | `1` | how often a run's progress is saved |
| `NOTES_SERVICE_KEY_TOUCH_SECONDS` | `60` | how often an API key's `last_used_at` is updated |
| `NOTES_SERVICE_DOCS` | `false` | serve the OpenAPI docs at `/docs` |
| `NOTES_SERVICE_LAUNCHCTL` | `/bin/launchctl` | (tests) |
| `NOTES_SERVICE_ALLOW_UPDATE` | `true` | let an admin client update the service ([Updates](#updates)) |
| `NOTES_SERVICE_UPDATE_CHECK_HOURS` | `24` | how long the newest release is remembered |
| `NOTES_SERVICE_UPDATE_CHECK_MIN_SECONDS` | `60` | the shortest gap between checks a client can ask for (`?refresh=true`) |
| `NOTES_SERVICE_UPDATE_TIMEOUT_SECONDS` | `300` | fetch, `pip install` and the self-check, each |
| `NOTES_SERVICE_UPDATE_GIT_TIMEOUT_SECONDS` | `30` | the other git commands |
| `NOTES_SERVICE_UPDATE_PYTHON` | `<repo>/.venv/bin/python` | the Python that installs requirements and runs the self-check |
| `NOTES_SERVICE_RESTART_DELAY_SECONDS` | `1` | how long after answering a restart the service exits |

## Authentication

**Never put a credential in a URL.** Requests with `?token=`, `?apikey=`,
`?api_key=`, `?access_token=`, `?key=`, `?password=`, `?jwt=` or `?auth=` are
refused with **400**, whatever the endpoint.

Send `Authorization: Bearer <session token or API key>`, or `X-API-Key: ne_…`.
Missing or invalid credentials: **401** (`WWW-Authenticate: Bearer`); a valid
one without the scope an endpoint needs: **403**.

* **Users** have a username, a bcrypt password and a role: `admin` (scopes
  read, run, settings, write, approve, admin) or `reader` (read, run). The last admin can't be removed or
  demoted (409). Resetting a password signs that user out everywhere; removing a
  user removes their API keys.
* **Sessions**: `POST /api/auth/login` returns a JWT (HS256, signed with a
  secret generated into `auth.sqlite`) that names a session row; logout ends it.
  Failed sign-ins are limited per client address (429).
* **API keys**: `ne_` + 32 random bytes (urlsafe base64). Only the SHA-256 is
  stored, with the first 10 characters as `prefix`, a name, scopes, owner,
  `created_at`, `last_used_at` and an optional `expires_at`. The key is shown
  **once**, when created. A key's scopes are limited to what its owner's role
  allows at the time of each request.

| Scope | Grants |
|---|---|
| `read` | status, manifest, notes, files, runs and their events |
| `run` | start and cancel runs |
| `settings` | read and change the export settings (`/api/settings`), except where the export is written and whether clients may write |
| `write` | change and create notes in Apple Notes ([Writing notes](#writing-notes)) — only while the admin has turned on `allow_writes`; not implied by `admin` |
| `approve` | 1.7.0: see, approve and reject writes held on [the approval list](#the-approval-list), and make [sign-in links](#sign-in-links-for-the-web-page); implied by `admin` |
| `admin` | settings (and moving the export), users, API keys; includes `settings` and `approve` |

## Endpoints

JSON unless noted, all under `/api`. Errors are `{"detail": "…"}` (validation
errors: 422 with FastAPI's list form); some also carry a machine-readable
`reason` ([Refusal reasons](#refusal-reasons)).

| Method | Path | Scope | |
|---|---|---|---|
| GET | `/health` | — | service, version, api_version, manifest_version, platform |
| GET / POST | `/setup` | — | first admin, loopback only, while there are no users |
| POST | `/auth/login`, `/auth/logout` | —, any | session token |
| GET | `/auth/me` | any | who you are, your scopes |
| POST | `/auth/password` | user session | change your own password |
| GET | `/status` | read | running run, last run, next run, permissions, formats |
| GET | `/manifest` | read | manifest.json verbatim, ETag / 304 |
| GET | `/notes`, `/notes/{id}` | read | note entries from the manifest |
| GET | `/writes` | read | whether writing is on, and whether you may |
| PUT | `/notes/{id}` | write | change a note from Markdown (a backup first; may be held: 202) |
| POST | `/notes` | write | a new note from Markdown (may be held: 202) |
| DELETE | `/notes/{id}?base=` | write | 1.7.0: move a note to Notes' Recently Deleted (may be held: 202) |
| GET | `/approvals`, `/approvals/{id}` | approve (write: your own) | 1.7.0: writes held for approval; one with before / after / diff |
| POST | `/approvals/{id}/approve`, `/approvals/{id}/reject`, `/approvals/bulk` | approve | 1.7.0: make or drop held writes |
| POST | `/auth/login-link` | admin or approve | 1.7.0: a one-off link that opens the web page signed in |
| POST | `/auth/login-link/exchange` | — | 1.7.0: the link's page swaps its token for a session |
| GET, HEAD | `/files/{path}` | read | a file of the export, Range / ETag |
| POST | `/runs` | run | start a run (202), 409 if one is running |
| GET | `/runs`, `/runs/{id}` | read | run records |
| GET | `/runs/{id}/events` | read | the run's JSON Lines events (`?after=`) |
| GET | `/runs/{id}/log` | read | the run's human output (text) |
| POST | `/runs/{id}/cancel` | run | stop it |
| GET | `/version` | read | running / installed / newest version, whether it can update ([Updates](#updates)) |
| POST | `/admin/update` | admin | update to a release, checked and undone on failure |
| POST | `/admin/restart` | admin | exit so launchd starts it again (202) |
| GET, PUT | `/admin/settings` | admin | export settings |
| GET, POST | `/admin/users` | admin | |
| PATCH, DELETE | `/admin/users/{id}` | admin | role / password; remove |
| GET, POST | `/admin/api-keys` | admin | POST returns the key once |
| DELETE | `/admin/api-keys/{id}` | admin | revoke |
| GET | `/` (not under /api) | — | the web UI |

### Health, setup and sign-in

`GET /api/health` → `{"service": "notes-exporter", "version": "1.5.0",
"api_version": 1, "manifest_version": 1, "platform": "darwin", "macos_version": "…"}`.

`GET /api/setup` → `{"needed": true|false, "allowed_here": true|false}`.
`POST /api/setup {username, password}` creates the first admin and returns
`{user, token, expires_at}` — only on a loopback connection without proxy
headers (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`), and only while no user
exists (409 afterwards, 403 from elsewhere).

`POST /api/auth/login {username, password}` → `{token, expires_at, user:{id,
username, role, …}}`. 401 wrong credentials, 429 too many failures.
`POST /api/auth/logout` ends the session. `GET /api/auth/me` →
`{kind: user|key, user_id, username, role, scopes, key_id?, key_prefix?}`.

### Status

```jsonc
GET /api/status
{
  "running_run_id": null,
  "last_run": { /* a run (below), the last finished one */ },
  "next_run_at": "2026-11-12T00:13:00+00:00",   // null when not scheduled
  "schedule": {"enabled": true, "interval_minutes": null, "daily_at": "00:13"},
  "export_root": "/Users/…/AppleNotesExport",
  "export_root_ok": true,                        // exists and a file can be created in it
  "export_root_problem": null,                   // or why not, in words: its drive isn't connected, macOS refuses it…
  "export_root_access": "ok",                    // 1.6.1: ok | denied | not_writable | missing | unknown
  "export_root_reason": null,                    // 1.6.1: drive_not_mounted | not_a_folder | not_writable | access_denied | probe_failed
  "manifest_present": true,
  "permission": {"automation": "allowed", "full_disk_access": false, "checked_at": "…",
                 "requesting": false},           // 1.6.1: a permission request is waiting for macOS
  // 1.6.1: the last runs without reading the history. Each prefix has _id, _status,
  // _finished_at and _message (all null when there is no such run).
  "last_run_id": "5c0f…", "last_run_status": "ok", "last_run_finished_at": "…", "last_run_message": null,
  "last_failed_run_id": "9a1e…",                 // the newest run that ended failed (not cancelled)
  "last_failed_run_status": "failed", "last_failed_run_finished_at": "…",
  "last_failed_run_message": "cannot create the lock in …",
  "last_success_run_id": "5c0f…",                // the newest ok or partial run
  "last_success_run_status": "ok", "last_success_run_finished_at": "…", "last_success_run_message": null,
  "formats": ["html", "md"],                     // the settings' formats
  "epub_books": "none",
  "version": "1.5.0",
  "writes": {                                    // 1.7.0 adds all but allowed
    "allowed": true,
    "backup": {"folder": "FunHoard Backups", "required": true, "exported": false},
    "limits": {"changes_last_hour": 3, "changes_last_day": 12, "max_per_hour": 50, "max_per_day": 200,
               "limited_until": null},            // when writing opens again while at a limit
    "holds": {"batch_over": 3, "batch_seconds": 60, "count_over": 5, "window_hours": 24,
              "changes_in_window": 4, "change_percent": 50, "min_lines": 2, "max_age_days": 0,
              "held": 2}                         // writes waiting on the approval list
  }
}
```

`GET /api/health` (no sign-in) and `GET /api/version` also answer `features` (1.7.0):
`["write", "write_backup", "delete", "write_limit", "approvals", "login_link"]`, so a client
can tell what this service does before relying on it.

### Manifest, notes and files

`GET /api/manifest` returns `manifest.json` byte for byte with
`ETag: "<sha256 of the file>"`; send `If-None-Match` to get **304** when it has
not changed. 404 `{detail}` before the first export.

`GET /api/notes?changed_since_sequence=N&account=A&folder=F&include_deleted=true`
→ `{sequence, notes:[…], deleted:[…]}`: manifest note entries (unchanged), only
those with `changed_in_run > N`, in account `A` (name or id) and folder `F`
(`Food` matches `Food` and everything under it; `Food/Baking` a path).
`deleted` is empty unless `include_deleted=true`; with `changed_since_sequence`
only tombstones whose `deleted_in_run > N` (or unknown) are listed.

`GET /api/notes/{id}` — the id URL-encoded (`x-coredata%3A%2F%2F…`): one note
entry, or its tombstone with `"deleted": true`; 404 otherwise.

`GET /api/files/{path}` — any file under the export root by its
manifest-relative path (`html/iCloud-Notes/My%20Note.html`). The path is
resolved with realpath and must stay inside the root's realpath: `..`, absolute
paths and symlinks that point outside are **403**; a missing file or a directory
is 404. Responses carry the right `Content-Type` (`text/markdown`,
`application/epub+zip`, …), `Accept-Ranges: bytes`, `Last-Modified` and an
`ETag` — `"sha256:<hex>"` when the manifest knows the file's hash and its size
still matches, else `"<size hex>-<mtime ns hex>"`. `If-None-Match` → 304;
`Range: bytes=a-b`, `bytes=a-`, `bytes=-n` → 206 with `Content-Range`; outside
the file → 416; several ranges → the whole file; `If-Range` with another ETag →
the whole file. Files are served with `Content-Security-Policy: sandbox` so an
exported note's HTML can't run scripts in the service's origin.

### Runs

A run:

```jsonc
{
  "id": "5c0f…",                      // the service's run id
  "status": "queued|running|ok|partial|failed|cancelled",
  "trigger": "schedule|api|ui|cli",
  "mode": "incremental|full",
  "folders": [], "accounts": [],
  "formats": ["raw", "text", "html", "epub"],   // what the run produces
  "epub_books": "none|folder",
  "requested_by": "key:ne_AbCdEf…" ,  // or user:<name>, schedule
  "created_at": "…", "started_at": "…", "finished_at": "…",
  "exit_code": 0,                      // the exporter's (INTEGRATION.md); -9 when killed
  "counts": {"notes": 412, "changed": 3, "deleted": 1, "deleted_this_run": 0, "skipped": 2},
  "progress": {"stage": "export", "done": 120, "total": 412, "unit": "notes"},
  "message": null,                     // why it failed, in words
  "exporter_run_id": "…",              // the manifest's run.id
  "manifest_sequence": 57,             // the manifest's run.sequence after this run
  "permission": "allowed"              // the run's own automation check
}
```

`POST /api/runs {mode?, folders?, accounts?, formats?, epub_books?, epub_book_order?, epub_book_subfolders?, trigger?}` →
**202** `{run}`. `mode` `incremental` (default) or `full` (re-export every note);
`folders` / `accounts` limit the run (names or folder paths; no commas, line
breaks or a leading `-`, else 400); `formats` and `epub_books` see
[below](#formats-and-epub-books); `epub_book_order` / `epub_book_subfolders` set
the folder books' layout for this run only (else the settings'; a book is rebuilt
when its order changes, so send the same values every run); `trigger` `api` (default), `ui` or `cli`.
**409** `{detail, running_run_id}` while a run is in progress — one run at a
time.

The exporter runs as `exportnotes.zsh --json-log runs/<id>.ndjson
--non-interactive` (plus `--sync false --sync-only false --update-qdrant false`)
with a clean environment: `HOME`, `USER`, `LOGNAME`, `TMPDIR`, `LANG`, a fixed
`PATH` and the variables named in `NOTES_SERVICE_PASS_ENV`; nothing from shell
rc files. Exit codes map to status: 0 ok, 2 partial, anything else failed
(with `message`: 3 permission, 4 another export holds the lock, 5 export
failed, 1 could not start).

`GET /api/runs?limit=20&offset=0` → `{runs, total}`, newest first.
`GET /api/runs/{id}/events?after=N` → `application/x-ndjson`: the event lines
after the first N (only complete lines), with `X-Next-After` (pass it as the
next `after`) and `X-Run-Status`. `GET /api/runs/{id}/log` → text.
`POST /api/runs/{id}/cancel` → `{run}`: SIGTERM to the exporter's process group,
SIGKILL after `NOTES_SERVICE_CANCEL_GRACE_SECONDS`; the run ends `cancelled`.
Cancelling a finished run changes nothing. When the service stops, a run in
progress is cancelled; a run left `running` by a crash is marked `failed` at the
next start.

The schedule (`settings.schedule`): `interval_minutes` counts from the last
run's start (any trigger), or from the service's start when there is none;
`daily_at "HH:MM"` (local time) runs at the first such time after the last run's
start — a time missed while the Mac slept runs once when the service notices.
A slot that comes while a run is in progress is skipped.

### Settings for a client

`GET /api/settings` (scope `settings`) → `{settings, read_only}`: the same
settings as [below](#admin-settings-users-api-keys), and `read_only`, the
fields this scope can't change (`["export_root"]`). `PUT /api/settings` merges
the fields you send, as the admin endpoint does, and answers the same shape; 422
for an invalid value or an unknown field. Sending `export_root` back unchanged
is fine; a different one is **403** `reason: "not_admin"` unless the key also has `admin` — a client
that tunes the export never decides where on the Mac it is written. This is how
FunHoard shows and changes the service's settings on its collection page.
Since 1.6.1 both answers also carry `export_root_ok`, `export_root_problem`,
`export_root_access` and `export_root_reason` (as in [Status](#status)) beside
`settings`, not inside it.

### Admin: settings, users, API keys

`GET /api/admin/settings` → the settings, plus (1.6.1) `export_root_ok`,
`export_root_problem`, `export_root_access` and `export_root_reason` as in
[Status](#status); `PUT` merges the fields you send and answers the same
(422 `{detail, reason, field}` for invalid ones; unknown fields are refused).
Those four fields may be sent back with the rest: they are ignored, never
saved. A **new** `export_root` must be writable now — its drive connected and
the folder (or, before the first export, the nearest folder above it) one the
service can create a file in — else 422 with `reason` `drive_not_mounted`,
`not_a_folder`, `not_writable` or `access_denied`. An unchanged one is never
refused, so other settings can be saved while its drive is away.

| Field | Default | |
|---|---|---|
| `export_root` | `~/Downloads/AppleNotesExport` | absolute; may not contain or be inside the state directory |
| `formats` | `["html"]` | any of `html, md, pdf, docx, epub, text, raw` ([below](#formats-and-epub-books)) |
| `folder_hierarchy` | `false` | nested folders (`--folder-hierarchy`) |
| `exclude_folders` | `["Recently Deleted"]` | see INTEGRATION.md for why |
| `prune_deleted` | `true` | remove files of notes deleted in Notes |
| `tags`, `tags_in_content` | `false` | `--tags` (Full Disk Access), `--tags-in-content` |
| `html_wrap` | `true` | full HTML pages with titles |
| `image_format`, `image_format_from`, `image_quality` | none | `--image-format jpeg|png|heic|tiff|webp` … |
| `epub_books` | `none` | `folder`: one EPUB per Notes folder |
| `epub_book_order` | `modified` | `modified`, `created` (newest first) or `title` |
| `epub_book_subfolders` | `separate` | or `nested` |
| `schedule` | `{"enabled": false}` | `{enabled, interval_minutes | daily_at "HH:MM"}` |

Users: `GET /api/admin/users` → `{users:[{id, username, role, created_at,
password_changed_at}]}`; `POST {username, password, role}` → 201 (409 if the
name is taken); `PATCH /api/admin/users/{id} {role?, password?}`;
`DELETE /api/admin/users/{id}`. 409 for the last admin.

Permission: `GET /api/admin/permission[?refresh=true]` → `{automation,
full_disk_access, checked_at, requesting}` (never prompts).
`POST /api/admin/permission/request` makes macOS show its "wants to control
Notes" dialog on the Mac and waits for the answer (up to
`NOTES_SERVICE_PERMISSION_REQUEST_TIMEOUT_SECONDS`), then checks again and
answers `{automation, full_disk_access, checked_at}`; 409 `reason: "busy"` while another request
is waiting. Only call it when someone is at the Mac.

Without waiting (1.6.1): `POST /api/admin/permission/request?wait=false` (or
the body `{"wait": false}`) starts the request and answers **202** at once with
the permission as `GET /api/admin/permission` gives it — `requesting: true`.
Poll `GET /api/admin/permission` (or `/api/status`'s `permission.requesting`)
until `requesting` is false; `automation` is then macOS's answer.
`GET /api/admin/permission` also has `last_request`: `{started_at,
finished_at, asked}` of the latest request (`finished_at` / `asked` null while
it waits), or null before the first. Waiting stays the default, so older
clients behave as before.

### Refusal reasons

Since 1.6.1 these refusals carry a machine-readable `reason` next to `detail`
(the message, unchanged), so a client needn't parse the words:

| Status | `reason` | Also | When |
|---|---|---|---|
| 403 | `not_admin` | `scope: "admin"` | an `/api/admin/…` endpoint without the admin scope |
| 403 | `not_admin` | `field`, `fields` | `PUT /api/settings` changing `export_root` (or `allow_writes`) without admin |
| 403 | `scope` | `scope` | any other endpoint without its scope |
| 409 | `busy` | | `POST /api/admin/permission/request` while another request waits |
| 422 | `not_absolute` | `field: "export_root"` | `export_root` isn't an absolute path |
| 422 | `inside_state_dir` | `field: "export_root"` | it contains, or is inside, the service's state directory |
| 422 | `drive_not_mounted` | `field: "export_root"` | a new one is on a drive (`/Volumes/<drive>`) that isn't connected |
| 422 | `not_a_folder` | `field: "export_root"` | a new one (or the folder above it) is a file |
| 422 | `not_writable` | `field: "export_root"` | a new one's permissions, or a read-only drive, don't allow writing |
| 422 | `access_denied` | `field: "export_root"` | macOS's privacy settings refuse the service there (Full Disk Access / Files and Folders) |
| 422 | `unknown_settings` | `field: null` | a field that isn't a setting |
| 422 | `invalid` | `field` (or null) | any other invalid value |

The 422s are from `PUT /api/admin/settings` and `PUT /api/settings`; `field`
names the setting when there is one. `/api/status`'s `export_root_reason` uses
the same `export_root` reasons, plus `probe_failed` (the check itself failed;
never refused for).

Export folder: `POST /api/admin/export-folder/open` shows the saved export
folder in the Finder (Settings → Show in Finder) — always on the Mac running the
service, so the answer `{opened, on_this_mac}` says when the caller is
elsewhere; 404 while the folder doesn't exist yet.

API keys: `GET /api/admin/api-keys` → `{api_keys:[{id, name, prefix, scopes,
owner_user_id, created_at, last_used_at, expires_at}]}`; `POST {name, scopes,
owner_user_id?, expires_at?}` → 201 `{api_key, key}` — **`key` is only ever in
this response**; `DELETE /api/admin/api-keys/{id}` revokes it.

## Writing notes

The service can change Apple Notes, behind several fences:

* **Off by default.** The admin turns on `allow_writes` (Settings → "Allow clients to
  write notes"); a `settings` key can't (it is in `read_only`). Every write needs the
  `write` scope, which `admin` doesn't imply. Off: **403** `reason: "off"`.
* **Never during an export, one write at a time:** **409** `reason: "running"` (with
  `running_run_id`) or `"busy"`.
* **Conflicts.** An update sends `base_modified`, the note's `modified` when the client
  read it. A newer export → **409** `reason: "export"` (`modified`). Then the service
  asks Notes for the note's modification date just before writing; a change made in
  Notes after the last export → **409** `reason: "notes"` (`notes_modified`). `force: true`
  skips both — the client's version replaces whatever Notes has.
* **What a rewrite loses.** Writing replaces the note's whole body: pictures go back in
  (embedded), but attachments that aren't pictures and a checklist's ticks don't. Such a
  note is **409** `reason: "losses"` with `losses` in words, until the client sends
  `accept_losses: true` after showing them. Locked and deleted notes are never written (409).
* A new note goes only into a folder the export already holds notes in (404 otherwise).
* 1.7.0: **a backup copy before every change** ([below](#backups-before-a-change)),
  **deleting** to Recently Deleted, a hard **mass-change limit** (429) and **the approval
  list**, which holds writes that look like a mass change or a big rewrite until someone
  approves them. All of their settings are the admin's: a `settings` key can read them
  (they are in `read_only`) but not change them.

`GET /api/writes` → `{allowed, busy, running_run_id, can_write, can_approve, backup, limits,
holds}` (the last three as in [`/api/status`](#status)'s `writes`).

`PUT /api/notes/{id}` `{markdown, base_modified, title?, force?, accept_losses?, backup?, export?, formats?}` →
`{note_id, modified, backup_note_id, run}`. `POST /api/notes` `{account, folder_path, markdown, title?, export?, formats?}`
→ **201** `{note_id, modified, run}`. A changed `title` renames the note. The Markdown becomes HTML with pandoc; a picture it links is embedded
when its file lies inside the export folder (anything outside, `..` or a symlink out, is
left as a link). With `export` (default true) the service then exports that note's folder
(adding `formats`), and `run` is that run, so the manifest soon has the new version.
Other errors: 503 `reason: "permission"` (allow the service under Privacy & Security →
Automation), 404 `not_found`, 504 `timeout`, 501 off macOS.

**A held write** (any of the three) answers **202** instead:
`{held: true, approval_id, reason, detail, kind, note_id, modified: null, backup_note_id: null, run: null}` —
nothing has changed in Notes yet. A client that only checks for a 2xx must look at `held`
(and `features` has `approvals` to tell it may happen).

Each write is appended to `writes.ndjson` in the state directory — when, who, which note,
the outcome, the backup's id, whether it was held / approved and by whom — never the note's
text. The work is `notes_write_helper.py` (pandoc, then
`osascript notes_write.applescript`) in a subprocess with the exporter's clean environment
(`NOTES_SERVICE_WRITER_HELPER`, `NOTES_SERVICE_WRITE_TIMEOUT_SECONDS`, default 180).

### Backups before a change

Since 1.7.0 an update first **copies the note as it is now** into a backup folder in Notes,
in the note's own account: `write_backup_folder` (default `FunHoard Backups`) at the top, and
beneath it the note's folder path (`FunHoard Backups/Food/Baking`), the folders made when
missing. The copy is titled with ` (before <local time>)` added — `Scones (before 2026-11-27 14:05)`
— and its id is answered as `backup_note_id`. **If the backup fails the note isn't changed**:
**502** `reason: "backup_failed"` (or the Notes refusal itself: `permission`, `timeout`, `locked`).

The request's `backup` is `"folder"` (the default for an update) or `"none"`; `"none"` is
refused (**403** `reason: "backup_required"`) while the admin's `write_backup_required` is on
(the default). The backup folders are left out of exports (so out of clients such as
FunHoard) unless `write_backup_export` is on; the service remembers every backup folder it has
made in `write_state.json`, because the exporter only skips whole folder paths.

How the copy is made: `notes_write.applescript backup` reads the note's `name` and `body` (the
HTML Notes gives a script, pictures embedded) and makes a new note with that body in the
backup folder. So the copy has the text, formatting and pictures; **not** attachments that
aren't pictures, checklist ticks, the original creation date, tags' links or a lock. Restore by
hand in Notes (copy the text back, or move the copy). A locked note is never copied.

| Setting | Default | |
|---|---|---|
| `write_backup_folder` | `FunHoard Backups` | one folder name, no `/` or commas |
| `write_backup_required` | `true` | clients may not send `backup: "none"` on an update |
| `write_backup_export` | `false` | export the backup folders like any others |

### Deleting a note

`DELETE /api/notes/{id}?base=<modified>[&backup=folder|none][&force=true][&export=false]`
(scope `write`) → `{note_id, deleted: true, recently_deleted: true, backup_note_id, run}`.

It is Notes' own delete: the note goes to the account's **Recently Deleted** folder, where Notes
keeps it about 30 days (iCloud and On My Mac; notes of other accounts follow that account's
rules). `base` (or `base_modified`) is required unless `force`; the conflict checks are the
update's (**409** `export` / `notes`), and locked or already deleted notes are refused (409).
`backup` defaults to `none` here (Recently Deleted is the copy); `folder` makes the same backup
first. The folder is then exported, so the manifest lists the note under `deleted`.

### The mass-change limit

A hard cap on the changes clients make — updates, new notes and deletes; not the service's own
backups, and not writes an approver approves:

| Setting | Default | |
|---|---|---|
| `write_max_changes_per_hour` | 50 | 0 = no limit |
| `write_max_changes_per_day` | 200 | 0 = no limit |

Beyond it: **429** `{detail, reason: "write_limit", retry_after, window: "hour"|"day", max, count}`
with a `Retry-After` header. The counts are kept in `write_state.json` in the state directory,
so a restart doesn't reset them; `/api/status` shows them (`writes.limits`).

### The approval list

A firewall in front of Notes for every client (FunHoard, the MCP server, scripts): a write
that trips one of these rules is **held** (202, above) instead of made. 0 turns a rule off.

| Setting | Default | Holds a write when |
|---|---|---|
| `write_hold_batch_over` / `write_hold_batch_seconds` | 3 / 60 | one client has already asked for more than 3 writes in the last 60 s (made or held) |
| `write_hold_count_over` / `write_hold_window_hours` | 5 / 24 | more than 5 changes were made in the last 24 h (by anyone) |
| `write_hold_change_percent` / `write_hold_min_lines` | 50 / 2 | more than 50 % of the note's words change, for a note longer than 2 lines; a delete counts as 100 % |
| `write_hold_max_age_days` | 0 | held writes older than this are dropped (0 = kept until decided) |

The change is measured on words (difflib) between the note's text in the export now (its
Markdown, else plain text, else the HTML's words) and the requested Markdown; when the export
has no text for the note the size rule can't apply and only the other two do. A new note is
held only by the first two.

Held writes are kept in `approvals/<id>.json` in the state directory (0600; it holds the
note's text before and after, as the export folder does), so they survive a restart. At most
1000 wait; beyond that a write is **429** `reason: "approvals_full"`.

* `GET /api/approvals` → `{approvals: [{id, kind (update|create|delete), status (pending|stale),
  note_id, account, folder_path, title, base, reason (batch|count|big_change), rule {reason,
  detail, …}, change_percent, created_at, stale_reason, client {name, label, kind, key_id?},
  before_lines, after_lines}], counts {total, pending, stale, update, create, delete}, can_approve}`.
  Scope `approve`: every held write. A `write` key (or user) without it: only its own.
* `GET /api/approvals/{id}` → the same plus `before`, `after`, `diff` (unified) and `request`
  (the write's options).
* `POST /api/approvals/{id}/approve` (scope `approve`) makes the write **the normal way**: the
  backup first, and the conflict checks against the `base` it was asked on (never forced) — so
  a note changed meanwhile isn't overwritten: **409** `reason: "export"|"notes"|…, stale: true`,
  and the item stays listed with `status: "stale"`. The hold rules and the mass-change limit
  don't apply to an approved write. Answers what the write answers, plus `approval_id`,
  `approved: true`, `kind`; the folder is exported as the write asked.
* `POST /api/approvals/{id}/reject` drops it (the client keeps its own copy) → `{approval_id, rejected: true}`.
* `POST /api/approvals/bulk {action: "approve"|"reject", ids: [...] | all: true}` → `{results:
  [{approval_id, ok, …}], approved, rejected, failed, run}`. `all` approves every **pending**
  item (rejects every item); approved writes are exported in **one** run afterwards.

The service's web page has an **Approvals** tab (for the `approve` scope) with each held
write's before / after and difference, and Approve / Reject, Approve selected, Approve all.
Approving one at a time starts that folder's export, and writes wait while an export runs, so
for several use Approve selected.

### Write refusals

| Status | `reason` | When |
|---|---|---|
| 202 | (`held: true`, `reason` batch / count / big_change) | held for approval — not an error, nothing changed |
| 400 | `bad_request` | a delete without `base`, a bad `backup`, a new note without text or folder |
| 403 | `off` | writing is off (`allow_writes`) |
| 403 | `backup_required` | `backup: "none"` while `write_backup_required` |
| 404 | `not_found` | no such note (or folder) in the export |
| 409 | `running`, `busy` | an export or another write is running |
| 409 | `export`, `notes` | the note changed since `base` |
| 409 | `losses`, `locked`, `deleted` | see above |
| 429 | `write_limit` | the mass-change limit (`retry_after`) |
| 429 | `approvals_full` | 1000 writes are already waiting |
| 502 | `backup_failed` | the backup couldn't be made, so the note wasn't changed |
| 503 / 504 / 501 | `permission` / `timeout` / `platform` | Notes refused automation / didn't answer / not macOS |

## Sign-in links for the web page

So a client (FunHoard's "Approve in notes-exporter" button, say) can open the service's own
web page already signed in:

`POST /api/auth/login-link {next?}` with a key (or session) holding `admin` or `approve` →
`{url, expires_at, next, ttl_seconds}`. `url` is `http(s)://<the address the client used>/login-link#<token>`:
a random single-use token in the URL's **fragment**, which browsers never send to a server, so it
reaches no access log or proxy; the service keeps only its digest (`auth.sqlite`, table
`login_links`). It works once, for `login_link_ttl_seconds` (setting, default 60, 10–600).
`next` is a path on the service (default `/`; `/approvals` opens the Approvals tab); anything
else — another site, `//host`, a relative path — is **400**.

Opening it loads `/login-link`, whose script (`web/link.js`) removes the token from the address
bar, sends it to `POST /api/auth/login-link/exchange {token}` and keeps the session that comes
back the way a password sign-in does (in that tab's `sessionStorage`), then goes to `next`. The
session is the key owner's, **limited to the key's scopes** (a signed claim in the token, so
an `approve` key's link can approve but not change settings). A used, unknown or expired token
is **401** `reason: "link_invalid"`, and failed exchanges count towards the sign-in limit per
address (429). Neither the token nor the link is logged.

## Updates

The service runs from a git checkout, so a client — FunHoard's Versions & Updates page, or
the web page's status card — can see whether it is current and, with an admin key, update and
restart it. A release is a `vX.Y.Z` tag on the checkout's `origin`.

`GET /api/version` (scope read; `?refresh=true` asks the remote now, at most every
`NOTES_SERVICE_UPDATE_CHECK_MIN_SECONDS`; otherwise the answer is remembered for
`NOTES_SERVICE_UPDATE_CHECK_HOURS`):

```json
{"version": "1.5.1", "installed": "1.6.0", "restart_needed": true,
 "latest": "1.6.0", "latest_checked_at": "2026-11-14T16:20:00+00:00",
 "update_available": false, "can_update": false, "why_not": "This is the newest release.",
 "updating": false, "can_restart": true}
```

`version` is what is running, `installed` the `VERSION` on disk — they differ after an
update until the service restarts (`restart_needed`). `check_error` appears when the remote
couldn't be asked. `can_update` is false, with `why_not` saying why, when updates are off
(`NOTES_SERVICE_ALLOW_UPDATE=false`), one is being made, an export is running, the service
isn't a git checkout, tracked files have uncommitted changes, the branch holds commits the
remote doesn't (or tracks none), the newest release isn't known or already installed, or it
isn't a fast-forward of what is checked out. `can_restart` is true when launchd started the
service, so it comes back after exiting.

`POST /api/admin/update` `{"to": "1.6.0"}` (scope admin; `to` defaults to the newest):
fetches the tags, fast-forwards to `v1.6.0` (`git merge --ff-only`, never a merge or a
rebase), runs `pip install -r requirements.txt` when that file changed, then checks the new
code in a fresh process — it imports and reports the version it should. Any failure puts the
checkout back (`git reset --hard` to the previous commit, and the old requirements) and answers
200 `{"ok": false, "rolled_back": true, "reason": "…", "from", "to"}`; success is
`{"ok": true, "from": "1.5.1", "to": "1.6.0", "restart_needed": true, "requirements_changed": false}`.
Refused before anything changes: 400 for a `to` that isn't `X.Y.Z`, 404 for a release that
doesn't exist, 409 for the `why_not` reasons above or a version that isn't newer, 502 when the
fetch fails. One update at a time. Each is logged in `updates.ndjson` in the state directory
(who, from, to, result).

`POST /api/admin/restart` `{"force": false}` (scope admin) answers 202 `{"restarting": true}`
and exits `NOTES_SERVICE_RESTART_DELAY_SECONDS` later; the LaunchAgent's `KeepAlive` starts it
again with the installed code. 409 when the service wasn't started by launchd (it wouldn't come
back), while an update is being made, or while an export runs unless `force` (which stops it).

## Formats and EPUB books

The service's `formats` setting is what every run produces. A client can ask a
run for more: `POST /api/runs {"formats": ["epub"]}` produces the **union** of
the settings' formats and the requested ones (`html, md, pdf, docx, epub,
text`; anything else is 422). `raw` and `text` are always written (raw is the
source of everything else), and `md`, `pdf`, `docx` and `epub` are made from the
HTML, so they bring `html` with them. HTML always has its images extracted and
linked. Each run records the formats it produced; `GET /api/status` keeps
reporting the settings' formats.

`epub` is one EPUB 3 per note (`epub/…/<note>.epub`, `outputs.epub` in the
manifest). `epub_books: "folder"` (in the settings or on a run, again a union)
also makes one EPUB per Notes folder, each note a chapter, listed in the
manifest's `books` (see [INTEGRATION.md](INTEGRATION.md#books)).

## Change detection for clients

Poll `GET /api/manifest` with `If-None-Match`. On a change, compare
`run.sequence` with the last one you saw and fetch the files whose
`outputs[*].sha256` or attachment `sha256` differ (or ask
`GET /api/notes?changed_since_sequence=N&include_deleted=true`). A note's
identity is its `id`; `previous_outputs` says its files moved; `deleted`
entries are tombstones. Books: compare each book's `sha256`; `deleted_books`
are tombstones.

## Security notes

* Loopback only by default; plain HTTP. Use a reverse proxy with HTTPS for
  remote access, and keep `--allow-remote` off otherwise.
* No CORS: browsers on other origins can't call the API.
* The web UI keeps its session token in `sessionStorage` (one tab) and sends it
  as a header; it is served with a strict Content-Security-Policy and
  `X-Frame-Options: DENY`.
* Bearer tokens and keys are never accepted from the URL, so they don't end up
  in logs, browser history or `Referer` headers.
* API keys and passwords are stored as hashes only. The exporter's program,
  Python and environment can't be changed over HTTP.

## Safety

Exports never write to Apple Notes: the service never passes `--sync` or
`--sync-only`, and blocks the sync variables from the exporter's environment. The only
writes are [Writing notes](#writing-notes), off until the admin allows them; their tests
(backups, deletes, the limits and the approval list among them) use `tests/service/fake_writer.py`
and fake `osascript` / `pandoc`, never Notes; `notes_write.applescript` is only compiled
(`osacompile`, which reads Notes' scripting dictionary and sends it nothing).
Its tests never touch real Notes or the real export folder: the exporter is
`tests/service/fake_exporter.py`, or the real `exportnotes.zsh` with
`tests/fake_osascript.py` first on its `PATH`, every test in its own temporary
`HOME`, and the LaunchAgent tests use a fake `launchctl`. The permission tests
use a fake `notes_permission.py` (`tests/service/fake_permission.py`) and the
Keychain tests a fake `security` (`tests/service/fake_security.py`), so no test
shows a macOS dialog or touches your Keychain. The update tests
(`tests/service/test_service_updates.py`) run git, pip and the self-check through a fake
runner over a pretend checkout, and restart through a fake exit — never the real checkout,
the network or launchd.

### The live check (opt in)

`ikt test notes-exporter live` (or `scripts/live_check.py`) does one real export
through the **running** service, so it reads your real Notes; it is skipped
unless `NOTES_EXPORTER_LIVE=1`, is never part of the required tiers, and prints
counts only (never a title, folder or path):

```bash
NOTES_EXPORTER_LIVE=1 \
NOTES_EXPORTER_LIVE_ENV_FILE=~/dev/storizzi/repos/apps/desktop/media-server/backend/.env \
  ikt test notes-exporter live
```

It checks `/api/health`; if Notes automation isn't allowed, asks for it (macOS
shows its dialog on the Mac: click Allow) — which needs a key with the admin
scope (`apikey create --scopes read,run,admin …`); otherwise press the web
page's button first. Then it starts a run (trigger `cli`), follows it, requires
`ok` or `partial`, checks the manifest's format and version, downloads every
output and book to compare its SHA-256 and size, and checks every attachment
exists with its size.

| Variable | Default | |
|---|---|---|
| `NOTES_EXPORTER_LIVE` | — | must be `1` |
| `NOTES_EXPORTER_LIVE_URL` | `http://127.0.0.1:8790` | the service |
| `NOTES_EXPORTER_API_KEY` | — | the key, else… |
| `NOTES_EXPORTER_LIVE_ENV_FILE` | — | …an env file to read only `NOTES_EXPORTER_API_KEY` from |
| `NOTES_EXPORTER_LIVE_MODE` | `incremental` | or `full` |
| `NOTES_EXPORTER_LIVE_TIMEOUT_SECONDS`, `NOTES_EXPORTER_LIVE_POLL_SECONDS` | `3600`, `2` | |

Its logic is tested against a service with the fake exporter and fake
permission helper (`tests/e2e/test_permission_and_live_e2e.py`).
