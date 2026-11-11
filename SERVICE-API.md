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
./notes-exporter apikey create --name FunHoard --scopes read,run \
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

## Authentication

**Never put a credential in a URL.** Requests with `?token=`, `?apikey=`,
`?api_key=`, `?access_token=`, `?key=`, `?password=`, `?jwt=` or `?auth=` are
refused with **400**, whatever the endpoint.

Send `Authorization: Bearer <session token or API key>`, or `X-API-Key: ne_…`.
Missing or invalid credentials: **401** (`WWW-Authenticate: Bearer`); a valid
one without the scope an endpoint needs: **403**.

* **Users** have a username, a bcrypt password and a role: `admin` (scopes
  read, run, admin) or `reader` (read, run). The last admin can't be removed or
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
| `admin` | settings, users, API keys |

## Endpoints

JSON unless noted, all under `/api`. Errors are `{"detail": "…"}` (validation
errors: 422 with FastAPI's list form).

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
| GET, HEAD | `/files/{path}` | read | a file of the export, Range / ETag |
| POST | `/runs` | run | start a run (202), 409 if one is running |
| GET | `/runs`, `/runs/{id}` | read | run records |
| GET | `/runs/{id}/events` | read | the run's JSON Lines events (`?after=`) |
| GET | `/runs/{id}/log` | read | the run's human output (text) |
| POST | `/runs/{id}/cancel` | run | stop it |
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
  "export_root_ok": true,                        // exists and writable
  "manifest_present": true,
  "permission": {"automation": "allowed", "full_disk_access": false, "checked_at": "…"},
  "formats": ["html", "md"],                     // the settings' formats
  "epub_books": "none",
  "version": "1.5.0"
}
```

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

### Admin: settings, users, API keys

`GET /api/admin/settings` → the settings; `PUT` merges the fields you send
(422 with a message for invalid ones; unknown fields are refused):

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
answers `{automation, full_disk_access, checked_at}`; 409 while another request
is waiting. Only call it when someone is at the Mac.

API keys: `GET /api/admin/api-keys` → `{api_keys:[{id, name, prefix, scopes,
owner_user_id, created_at, last_used_at, expires_at}]}`; `POST {name, scopes,
owner_user_id?, expires_at?}` → 201 `{api_key, key}` — **`key` is only ever in
this response**; `DELETE /api/admin/api-keys/{id}` revokes it.

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

The service never writes to Apple Notes: it never passes `--sync` or
`--sync-only`, and blocks the sync variables from the exporter's environment.
Its tests never touch real Notes or the real export folder: the exporter is
`tests/service/fake_exporter.py`, or the real `exportnotes.zsh` with
`tests/fake_osascript.py` first on its `PATH`, every test in its own temporary
`HOME`, and the LaunchAgent tests use a fake `launchctl`. The permission tests
use a fake `notes_permission.py` (`tests/service/fake_permission.py`) and the
Keychain tests a fake `security` (`tests/service/fake_security.py`), so no test
shows a macOS dialog or touches your Keychain.

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
