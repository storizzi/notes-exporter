# Releases <!-- omit from toc -->

- [Unreleased - 1.5.1 - Settings for clients](#unreleased---151---settings-for-clients)
- [11 November 2026 - Release 1.5.0 - Service API \& EPUB](#11-november-2026---release-150---service-api--epub)
- [11 November 2026 - Release 1.4.0 - Nested Folders, Manifest \& Reliable Incremental Export](#11-november-2026---release-140---nested-folders-manifest--reliable-incremental-export)
- [18 March 2026 - Release 1.3.0 - Bidirectional Sync, Search \& Venv Support](#18-march-2026---release-130---bidirectional-sync-search--venv-support)
- [17 March 2026 - Release 1.2.0 - Bug Fix, UTF-8 Support \& File Date Setting](#17-march-2026---release-120---bug-fix-utf-8-support--file-date-setting)
- [8 January 2026 - Release 1.1.0 - Deleted Record Handling](#8-january-2026---release-110---deleted-record-handling)
- [10 June 2025 - Release 1.0.0 - Incremental Export \& Deletion Tracking - BREAKING CHANGES!](#10-june-2025---release-100---incremental-export--deletion-tracking---breaking-changes)
- [6 June 2025 - Release 0.3 - Automated Scheduling \& Output Improvements](#6-june-2025---release-03---automated-scheduling--output-improvements)
- [10 June 2024 - Release 0.2 - Filename format / other file types](#10-june-2024---release-02---filename-format--other-file-types)
- [8 December 2023 - Release 0.1 - Initial Release](#8-december-2023---release-01---initial-release)

## Unreleased - 1.5.1 - Settings for clients

* **New API key scope `settings`**: `GET` / `PUT /api/settings` read and change the export settings (formats, folders, deleted notes, tags, images, EPUB books, schedule) — everything except where the export is written (`export_root`), which stays with an admin. An admin key includes it. Create one with `notes-exporter apikey create --scopes read,run,settings …` (or tick **settings** on the API keys page); FunHoard uses it to show the service's settings on its collection page. See [Settings for a client](SERVICE-API.md#settings-for-a-client).
* **Garbled characters in older exports fixed**: exports made before 1.5.0 wrote some raw files in Mac Roman and appended each re-export to the old file instead of replacing it, so a note that hadn't changed since kept a raw file holding both. The HTML step then read the whole file as Mac Roman: the note appeared two or more times and every UTF-8 character in it was garbled (`’` became `‚Äô`). Now any note whose raw file isn't valid UTF-8 is exported again on the next run, whatever its date (`tracker_io.py load`), so its raw, html, md, pdf… are rewritten once; and a mixed file is read part by part (`decode_note_bytes`), never wholesale as Mac Roman.

## 11 November 2026 - Release 1.5.0 - Service API & EPUB

notes-exporter can now run as a long-running service that other programs (FunHoard, a backup job, a script) use over HTTP, and exports EPUB.

### Upgrading from 1.4.x <!-- omit from toc -->

Nothing changes for the command line or the nightly job. `requirements.txt` gains the service's dependencies (FastAPI, uvicorn, bcrypt, PyJWT, httpx), so the next run of `exportnotes.zsh` installs them into `.venv`. To use the service, follow [Running as a service](README.md#running-as-a-service); if you scheduled exports with `setup_launchd.py`, let the service take over with `notes-exporter service install --replace-legacy` and set a schedule in its settings.

### Service <!-- omit from toc -->

* **`notes-exporter serve`** (`notes_service/`, FastAPI + uvicorn) on 127.0.0.1:8790: `GET /api/health`, `/status` (running and last run, next scheduled run, Notes automation and Full Disk Access checked without prompting, formats), `/manifest` (verbatim, ETag / 304), `/notes` (changed since a sequence, by account or folder, tombstones), `/notes/{id}`, `/files/{path}` (realpath containment, Range, ETag from the manifest's sha256), `/runs` (start, list, events, log, cancel), `/admin/settings`, `/admin/users`, `/admin/api-keys`. See [SERVICE-API.md](SERVICE-API.md).
* **Auth**: users with bcrypt passwords and roles admin / reader, JWT sessions with logout, API keys (`ne_…`, stored as SHA-256, scopes read / run / admin, optional expiry, shown once), a login rate limit, credentials in query strings refused, the last admin protected, first-time setup only from the Mac itself.
* **Runs**: one at a time; `exportnotes.zsh --json-log --non-interactive` in a clean environment, never with `--sync`; progress and counts from the events; cancel stops the whole process group (SIGTERM, then SIGKILL after a grace period); records in sqlite. A run can ask for extra formats (`formats`, a union with the settings) and for folder books.
* **Schedule**: every N minutes or daily at HH:MM; a time missed while the Mac slept runs once; skipped while a run is in progress.
* **Web page** at `/`: first-run setup, sign-in, status, Run now, live run log, settings, users, API keys (new key shown once with a Copy button, revoke).
* **`notes-exporter`** command: `serve`, `user add|list|passwd|remove`, `apikey create|list|revoke`, `permission status|request`, `service install|uninstall|status` for the `com.storizzi.notes-exporter` LaunchAgent (refuses while the old `com.<user>.notes_exporter` job exists, unless `--replace-legacy`).
* **Setup without copying secrets**: `user add|passwd --generate-password --keychain` makes a strong password and stores it in the login Keychain (through `security -i` on stdin, read back to check; never printed, never on a command line); `apikey create --env-file PATH [--env-var NAME] [--replace]` writes the key into another program's env file (other lines kept byte for byte, mode 0600, atomic), shows only its prefix, and with `--replace` revokes the older keys of that name.
* **Asking for the Notes permission**: `notes_permission.py --ask` lets macOS show its dialog (opening Notes in the background first if needed); the service asks for itself with `POST /api/admin/permission/request` (one at a time, waits up to `NOTES_SERVICE_PERMISSION_REQUEST_TIMEOUT_SECONDS`), from the web page's **Ask macOS for access to Notes** or `notes-exporter permission request`, which signs in with a short session of its own and revokes it afterwards. `GET /api/admin/permission` reports it.
* Every tunable (port, session hours, rate limit, grace period, scheduler tick, …) is a `NOTES_SERVICE_*` variable.

### EPUB <!-- omit from toc -->

* **`--convert-epub`**: one EPUB 3 per note in `epub/`, made from the HTML output: well-formed XHTML, every image it shows packaged (shared images once), nav.xhtml and toc.ncx, the note id as a URN, its dates, account and folder in the metadata. Standard-library zipfile only (no GPL / AGPL dependency). Incremental, deterministic (an unchanged note keeps its sha256), and renamed, moved and pruned like the other formats. `outputs.epub` in the manifest.
* **`--epub-books folder`**: one EPUB per Notes folder in `epub-books/`, each note a chapter, ordered by `--epub-book-order modified|created|title`; `--epub-book-subfolders nested` makes subfolders parts of their top folder's book. A book is rebuilt only when it changes; a folder with no notes left loses its book. The manifest gains `books` and `deleted_books`.

### Manifest <!-- omit from toc -->

* Additions within version 1: `books`, `deleted_books`, `run.counts.books`, `deleted[].deleted_in_run`, and `epub` in `formats` / `outputs`.

### Tests <!-- omit from toc -->

* Service tests (TestClient with a fake exporter, a fake launchctl, a fake permission helper and a fake `security`), an end-to-end suite on a real server port (also driving the real `exportnotes.zsh` with the fake osascript), EPUB structure and book tests, and `ikt.project.js` so `ikt test notes-exporter` runs the tiers `unit`, `service`, `e2e` and `epubcheck` (optional), plus the opt-in `live` tier (`NOTES_EXPORTER_LIVE=1`: one real export through the running service, checked file by file against the manifest, counts only).

## 11 November 2026 - Release 1.4.0 - Nested Folders, Manifest & Reliable Incremental Export

This release makes the export dependable for large libraries and for other programs: incremental runs only touch notes that changed, one bad note no longer stops a run, deletions are only recorded when they are certain, nested folders are kept, and every run leaves a machine-readable `manifest.json`.

### Upgrading from 1.3.x <!-- omit from toc -->

Nothing is required. The default layout (`&account-&folder`, `&title-&id`) is unchanged, and 1.3 tracking files are read as they are; the first 1.4 run adds ISO dates and folder information to each record. Use `python3` (macOS has no `python`); `exportnotes.zsh` now creates `.venv` and installs the dependencies itself when no suitable Python is found. To move to nested folders, run `reorganize_by_folder.py --dry-run`, then without it, and export with `--folder-hierarchy`.

### Export reliability <!-- omit from toc -->

* **Incremental runs re-exported unchanged notes** (#30): modification dates are compared as ISO timestamps instead of localised strings, and recorded with a time zone.
* **Note titles with a back-tick, quote or `$` were silently dropped** (#33): tracking data is no longer passed through a shell; the AppleScript writes it to a file that `tracker_io.py` merges.
* **Same-named folders under different parents dropped each other's notes** (#37): a note is recorded as deleted only after a run that listed its own folder to the end. Interrupted, failed and filtered runs never record deletions.
* **Locked notes and failing notes** are skipped and reported; the export carries on. Only a refused permission or Notes quitting stops it.
* **Notes changing during an export**: folders are checked by id and each folder's notes are read consistently, so another note's title or flags can't end up on a file.
* **writeToFile appended instead of replacing** shorter content, and closed the wrong file (#24, #25).
* **Paths with spaces** in the tool's own folder broke the script (#38).
* **`python` not found** on current macOS (#15, #17, #32).
* **`--venv-dir` didn't install dependencies** (#29).
* Dates from `set_file_dates.py` work with more locale formats (#24).

### Nested folders <!-- omit from toc -->

* `&folderpath` (alias `&path`) in `--subdir-format`, and `--folder-hierarchy` for `&account/&folderpath` (#36).
* `--filter-folders` and the new `--exclude-folders` accept folder paths (`Work/Projects`).
* `reorganize_by_folder.py` moves an existing flat export into the nested layout, offline from the tracking data.
* Every later step (images, conversions, dates, sync, query, reconcile, Qdrant) follows the nested paths.

### For other programs <!-- omit from toc -->

* **`manifest.json`** (format `notes-exporter.manifest`, version 1), written atomically after every run, failed ones included: notes with stable ids, nested folder paths, ISO dates, tags, locked / shared / pinned / checklist, every output file with SHA-256 and size, attachments, `previous_outputs` after renames and moves, `changed_this_run`; deleted notes as tombstones; skipped notes with the reason. See [INTEGRATION.md](./INTEGRATION.md).
* **`--json-log [FILE]`** on `exportnotes.zsh`: JSON Lines events (`start`, `plan`, `progress`, `stage`, `note_error`, `manifest`, `result`).
* **Exit codes**: 0 ok, 1 could not start, 2 partial, 3 Notes automation refused, 4 another export running, 5 failed.
* **`--non-interactive`** checks the automation permission without asking and exits with 3 rather than wait at a prompt.
* A lock in the export root stops two exports sharing it.
* `--version`, `--python PATH`.

### Files and formats <!-- omit from toc -->

* **`--prune-deleted`** removes the files of notes deleted in Apple Notes, keeping locally edited Markdown (#26). A moved note's old copy is always removed.
* **`--image-format`**, `--image-format-from`, `--image-quality` convert extracted images (sips; WebP through Pillow or cwebp) (#28).
* **`--tags`** reads `#tags`, pinned and checklist flags from a copy of the Notes database (needs Full Disk Access) (#16); `--tags-in-content` writes a Tags line into each note. Without `--tags` the manifest lists hashtags found in the text.
* Markdown image links work for attachment names with spaces or parentheses (#34, #35).
* `--html-wrap` escapes the title and adds the tags as keywords.
* A rename removes only that note's attachments (names with `[` `]` matched others').
* `sync_to_notes.py`: options with spaces are passed whole (#31), and Markdown edited before its first sync is detected as changed (#31).

### Dependencies <!-- omit from toc -->

beautifulsoup4 4.15.0, markdownify 1.2.3, pypandoc 1.17, pytest 9.2.0; tested on Python 3.15. Pillow is optional, for WebP.

*Thanks to [@rnoblecodes](https://github.com/rnoblecodes) for the detailed reports and fixes behind #33, #34–#37 (PR #35 and the folder post-processor), [@sai3563](https://github.com/sai3563) (PR #24), [@weijianfan](https://github.com/weijianfan) (PR #25), [@laurachencn](https://github.com/laurachencn) (PR #32), [@gdecugis](https://github.com/gdecugis) (PR #38), [@jtenniswood](https://github.com/jtenniswood) for the ideas in PR #27, and [@chrisvanpatten](https://github.com/chrisvanpatten), [@dotherightthing](https://github.com/dotherightthing), [@tcrgit](https://github.com/tcrgit), [@pppaapp](https://github.com/pppaapp) and [@MrSimmo](https://github.com/MrSimmo) for their reports.*

## 18 March 2026 - Release 1.3.0 - Bidirectional Sync, Search & Venv Support

This release adds bidirectional sync (edit markdown locally, push back to Apple Notes), AI-powered semantic search via Qdrant, a full-text search/query tool, reconciliation, several export enhancements, JSON Lines output on all commands, comprehensive test coverage, and switches from conda to Python venv.

### Upgrading from 1.2.x <!-- omit from toc -->

Sync requires the `fullNoteId` field in your tracking JSON, which is only populated by the updated export. After upgrading, run a full re-export to populate the new field:

```bash
exportnotes.zsh --update-all --convert-markdown
```

Existing exports will continue to work for all non-sync features without a re-export. The `--conda-env` flag now maps to `--venv-dir` and prints a deprecation warning.

### Bidirectional Sync <!-- omit from toc -->

* **Sync local edits back to Apple Notes**: Edit exported markdown files locally, then push changes back with `--sync` or `--sync-only`
* **Change detection**: SHA-256 hash comparison for local files, modification date comparison for remote notes
* **Conflict handling**: When both sides change, creates a `.conflict.md` sidecar file showing both versions (configurable with `--conflict`)
* **New note creation**: Create new Apple Notes from local markdown files with `--create-new`
* **Dry run mode**: Preview what would be synced with `--sync-dry-run`
* **Full Note ID tracking**: Export now stores the complete Apple Notes ID (`fullNoteId`) in tracking JSON, enabling sync-back by finding notes via `first note whose id is fullID`
* **Settings file**: New `.notes-exporter-settings.json` for persistent sync configuration (conflict strategy, auto-regeneration, sync source)

### Virtual Environment Support <!-- omit from toc -->

* **New `--venv-dir` (`-v`) option**: Creates and activates a Python virtual environment (replaces conda as preferred approach)
* **`--remove-venv` option**: Cleans up the virtual environment after export
* **`--conda-env` deprecated**: Still works but prints a warning; use `--venv-dir` instead

### New CLI Options <!-- omit from toc -->

**Sync:**
* `-S, --sync` — Run sync-back after export
* `--sync-only` — Run sync-back without exporting first
* `--sync-dry-run` — Preview sync operations
* `--create-new` — Create new notes from unmatched local files
* `--conflict STRATEGY` — Override conflict handling (`abort`|`local`|`remote`)

**Search:**
* `-Q, --query PATTERN` — Search exported notes (passes remaining args to `query_notes.py`)

**Export & Qdrant:**
* `-O, --no-overwrite` — Skip files that already exist
* `--modified-after DATE` — Only export notes modified after this date
* `--images-beside-docs` — Place images next to HTML files
* `--html-wrap` — Wrap HTML with proper page structure
* `--dedup-images` — Deduplicate identical images
* `--update-qdrant` — Sync notes to Qdrant after export

**Environment:**
* `-v, --venv-dir DIR` — Python virtual environment directory
* `--remove-venv` — Remove venv after export
* `--conda-env` — Deprecated, maps to `--venv-dir`

### New Environment Variables <!-- omit from toc -->

* `NOTES_EXPORT_SYNC`, `NOTES_EXPORT_SYNC_ONLY`, `NOTES_EXPORT_SYNC_DRY_RUN`
* `NOTES_EXPORT_CREATE_NEW`, `NOTES_EXPORT_CONFLICT_STRATEGY`
* `NOTES_EXPORT_VENV_DIR`, `NOTES_EXPORT_REMOVE_VENV`
* `NOTES_EXPORT_NO_OVERWRITE`, `NOTES_EXPORT_MODIFIED_AFTER`
* `NOTES_EXPORT_IMAGES_BESIDE_DOCS`, `NOTES_EXPORT_HTML_WRAP`, `NOTES_EXPORT_DEDUP_IMAGES`
* `NOTES_EXPORT_UPDATE_QDRANT`, `NOTES_EXPORT_QDRANT_URL`, `NOTES_EXPORT_QDRANT_API_KEY`, `NOTES_EXPORT_QDRANT_COLLECTION`
* `NOTES_EXPORT_EMBEDDING_PROVIDER`, `NOTES_EXPORT_OLLAMA_URL`, `NOTES_EXPORT_OLLAMA_MODEL`, `NOTES_EXPORT_EMBEDDING_MODEL`

### New Files <!-- omit from toc -->

* `sync_to_notes.py` — Main sync engine with change detection, conflict handling, and new note creation
* `sync_notes.scpt` — AppleScript for writing/creating notes and checking modification dates
* `sync_notes_bridge.py` — Python-to-AppleScript bridge via temp JSON files
* `sync_settings.py` — Settings file loading and CLI override precedence
* `query_notes.py` — Full-text search with regex, date, and image filters
* `qdrant_integration.py` — Qdrant vector DB management: sync, search, status, reset
* `reconcile.py` — Cross-system reconciliation: Apple Notes vs JSON vs disk vs Qdrant
* `output_format.py` — Shared JSON Lines output formatting for all commands
* `GUIDE-BASIC.md` — Basic guide: backup and search
* `GUIDE-ADVANCED.md` — Advanced guide: sync, AI search, JSON output
* `REFERENCE.md` — Complete technical reference
* `tests/conftest.py` — Shared test fixtures, markers, and scope control
* `tests/test_integration.py` — Integration tests (29 subprocess-based tests)

### JSON Schema Extensions <!-- omit from toc -->

New fields per note (added by sync engine, preserved by existing export):
* `fullNoteId` — Complete Apple Notes identifier for sync-back
* `lastSyncedToNotes` — Timestamp of last sync to Apple Notes
* `localFileHashAtLastSync` — SHA-256 hash for local change detection
* `appleNotesModifiedAtLastSync` — Remote modification date at last sync
* `syncCount` — Number of times synced back
* `syncSource` — Which format drives sync (`markdown` by default)

### Qdrant Vector Database Integration <!-- omit from toc -->

* **Semantic/AI search**: Find notes by meaning, not just keywords — `--ai-search "cooking ideas"` finds recipe notes
* **Incremental indexing**: `--update-qdrant` only re-embeds notes that changed since the last index, tracked via `lastIndexedToQdrant` in the JSON. First run indexes everything; subsequent runs process only the delta.
* **Automatic deletion**: Notes deleted in Apple Notes (marked with `deletedDate`) are automatically removed from the Qdrant index on each sync
* **Force re-index**: `python qdrant_integration.py sync --force` re-embeds all notes (e.g. after changing embedding model)
* **Ollama embeddings**: Uses local Ollama server with `mxbai-embed-large` by default (1024 dims) — all data stays on your machine
* **Qdrant Cloud support**: Set `NOTES_EXPORT_QDRANT_URL` and `NOTES_EXPORT_QDRANT_API_KEY` for cloud-hosted Qdrant
* **sentence-transformers alternative**: Set `NOTES_EXPORT_EMBEDDING_PROVIDER=sentence-transformers` to use local Python embeddings without Ollama
* **Prerequisite checker**: `python qdrant_integration.py check` verifies Docker, Qdrant, and Ollama are running and models are available
* **No new pip dependencies**: Uses Qdrant REST API via Python stdlib — no `qdrant-client` package needed

### Note Search / Query <!-- omit from toc -->

* **New `query_notes.py` script**: Full-text search across exported notes with regex, date, and image filters
* **Text search**: Literal text or regex (`-E`), case-insensitive (`-i`), context lines (`-c N`), files-only listing (`-l`)
* **Date filtering**: `--modified-within 3d`, `--created-within 2w`, `--modified-after 2026-01-15`, `--created-before 2025-06-01` — supports timespans (`5h`, `3d`, `2w`, `2m`, `1y`) and ISO dates
* **Image filtering**: `--has-images` / `--no-images` to find notes with or without attachments
* **Format/folder filtering**: `--format md,html,text` and `-F Notes` to narrow search scope
* **CLI integration**: `./exportnotes.zsh --query "search term"` passes through to the query tool

### Reconciliation <!-- omit from toc -->

* **New `reconcile.py` script**: Compares note counts across Apple Notes, tracking JSON, disk files, and Qdrant to find mismatches
* **Specific exception listing** (`--details`): Pinpoints orphan files, missing exports, deleted notes still on disk, and notes missing from Qdrant — by filename
* **Per-notebook breakdown** (`--notebooks`): Shows counts per notebook across all systems
* **Speed controls**: `--skip-apple` and `--skip-qdrant` skip live queries for instant results using only JSON + disk
* **Fix suggestions** (`--fix`): Recommends commands to resolve discrepancies

### JSON Lines Output <!-- omit from toc -->

* **`--json-log` flag on all commands**: Machine-readable JSON Lines output (one JSON object per line) for piping, logging, and integrations
* **Two modes**: `--json-log` sends JSON to stdout (human output to stderr); `--json-log FILE` sends JSON to file (human output to stdout)
* **Consistent key names**: All commands use the same field names (`file`, `score`, `note_id`, `notebook`, `filename`, `created`, `modified`, etc.)
* **Supported commands**: `query_notes.py`, `qdrant_integration.py`, `reconcile.py`, `sync_to_notes.py`

### Export Enhancements <!-- omit from toc -->

* **No-overwrite mode** (`--no-overwrite`, `-O`): Skip writing files that already exist, preventing accidental overwrites of locally edited files
* **Date range filter** (`--modified-after DATE`): Only export notes modified after a given date (supports ISO `2026-01-15` and locale formats)
* **Images beside documents** (`--images-beside-docs`): Place extracted images alongside HTML files instead of in an `attachments/` subdirectory
* **Proper HTML wrapping** (`--html-wrap`): Wrap exported HTML with `<!DOCTYPE html>`, `<head>`, `<title>`, and `<body>` tags for standards-compliant output
* **Image deduplication** (`--dedup-images`): Identical images (by SHA-256 content hash) are saved once and referenced from multiple notes, reducing disk usage

### Documentation <!-- omit from toc -->

* **Restructured into 3 guides**: README is now a concise overview linking to:
  * `GUIDE-BASIC.md` — backup, search, scheduling for new users
  * `GUIDE-ADVANCED.md` — sync, Qdrant AI search, JSON output for power users
  * `REFERENCE.md` — complete CLI options, env vars, JSON schemas, console output format, test details
* **Console output examples**: Technical reference includes exact examples of human-readable output for every command
* **No PII**: All documentation uses generic example data only

### Testing <!-- omit from toc -->

* **258 tests** across 13 test files (up from 80 in v1.2.0)
* **Integration tests** (`test_integration.py`): 29 subprocess-based end-to-end tests running commands against isolated temp data
* **Test markers**: `unit`, `integration`, `search`, `sync`, `qdrant`, `reconcile`, `export`, `settings`, `json_output` — run any category with `pytest -m <marker>`
* **Test isolation**: All tests use temp directories via `conftest.py` fixtures; never touches live data
* **Scope control**: `NOTES_TEST_LIMIT` env var or `--all-items` flag
* **Shared fixtures**: `test_export_dir` and `sample_notes` create realistic test data automatically

### Additional Environment Variables <!-- omit from toc -->

* `NOTES_EXPORT_CHUNK_SIZE` (default: 800) — characters per chunk for Qdrant embedding
* `NOTES_EXPORT_CHUNK_OVERLAP` (default: 200) — overlap between chunks

## 17 March 2026 - Release 1.2.0 - Bug Fix, UTF-8 Support & File Date Setting

This release incorporates community contributions: a critical bug fix for `--update-all` mode, proper UTF-8 file encoding, and the ability to set filesystem timestamps to match Apple Notes dates.

### Performance: Batch Metadata Fetching (~3x faster incremental checks) <!-- omit from toc -->

* **Batch Apple Events**: Instead of fetching note IDs and modification dates one-by-one (2 Apple Events per note), the script now fetches all IDs and dates in just 2 Apple Events per folder. This eliminates the main bottleneck in incremental runs where most notes are unchanged.

| Scenario (841 notes) | Before | After | Speedup |
|---|---|---|---|
| Incremental (all skipped) | 91s (9 notes/s) | 29s (29 notes/s) | **3.1x** |

### Bug Fix & Code Improvements <!-- omit from toc -->

*Thanks to [@sulkaharo](https://github.com/sulkaharo) for code improvements (PR #18).*

* **Fixed `--update-all` mode**: A redundant `shouldProcessNote` call in the main loop meant that `--update-all` would still skip unchanged notes instead of re-exporting them. The duplicate check has been removed so `--update-all` now correctly forces re-export of all notes.
* **Fixed `--note-limit` with deletion tracking**: When a note limit caused the loop to exit early, notes that weren't iterated could be incorrectly marked as deleted. The batch fetch now populates all note IDs upfront, preventing false deletions.
* **Fixed note limit count**: Note limit now uses `>=` instead of `>` for correct enforcement (previously allowed one extra note beyond the limit).
* **Deferred metadata loading**: Note title, creation date, and content are only fetched when the note will actually be processed, reducing unnecessary API calls during full exports.
* **Early random selection**: When using `--note-pick-probability`, random selection now happens before any metadata retrieval.
* **Optimized JSON loading**: Added shell-based file existence check before invoking Python, avoiding unnecessary Python startup for missing files.
* **Reduced logging**: Progress logging reduced from every 50 to every 100 notes; verbose debug logging trimmed throughout.

### UTF-8 File Encoding <!-- omit from toc -->

*Thanks to [@lmmsoft](https://github.com/lmmsoft) for the UTF-8 encoding fix (PR #22).*

* **UTF-8 file writing**: Exported files are now written with explicit UTF-8 encoding (`as class utf8`), ensuring proper handling of non-ASCII characters including Chinese, Japanese, Korean, and other international text

### File Date Setting <!-- omit from toc -->

*Thanks to [@dfl](https://github.com/dfl) for the filesystem timestamp feature (PR #19).*

* **New `--set-file-dates` (`-D`) flag**: Sets filesystem creation and modification dates on exported files to match the original Apple Notes dates
  * Default: `false` (opt-in to avoid unexpected behavior changes)
  * Environment variable: `NOTES_EXPORT_SET_FILE_DATES`
  * Uses `touch -t` for modification dates and `SetFile` (Xcode Command Line Tools) for creation dates
  * Useful for tools like UpNote that read timestamps from the filesystem
  * Supports all export formats: HTML, text, raw, Markdown, PDF, and Word

### Usage Examples <!-- omit from toc -->

Set filesystem dates to match Apple Notes (boolean flag form):
```bash
exportnotes.zsh --set-file-dates
```

Or using explicit value form:
```bash
exportnotes.zsh --set-file-dates true
```

Set via environment variable:
```bash
export NOTES_EXPORT_SET_FILE_DATES=true
exportnotes.zsh
```

## 8 January 2026 - Release 1.1.0 - Deleted Record Handling

### New Features <!-- omit from toc -->

* **Memory efficiency**: Deleted records are now excluded from memory by default, significantly reducing memory usage for large note collections with many deleted notes
* **Configurable deleted record handling**: New `--include-deleted` (`-I`) flag allows you to include or exclude deleted records from memory
  * Default: `false` (excludes deleted records for better performance)
  * Set to `true` if you need to track deleted notes
  * Environment variable: `NOTES_EXPORT_INCLUDE_DELETED`
* **Enhanced statistics**: Distinguishes between "skipped unchanged" and "skipped older" notes for better insight into export behavior
* **Improved logging**: More detailed progress tracking and better error messages throughout the export process

### Behavior Changes <!-- omit from toc -->

* **Note limit behavior**: The note limit check now uses `≥` instead of `>`, meaning if `noteLimit=10`, it will stop after processing exactly 10 notes (previously 11)
* **Progress logging frequency**: Reduced from every 50 notes to every 100 notes to reduce log verbosity for large exports

### Usage Examples <!-- omit from toc -->

Include deleted records for tracking purposes (boolean flag form):
```bash
exportnotes.zsh --include-deleted
```

Or use the short form:
```bash
exportnotes.zsh -I
```

Or using explicit value form (useful for automation):
```bash
exportnotes.zsh --include-deleted true
```

Force a full update of all notes (boolean flag form):
```bash
exportnotes.zsh --update-all
```

Or using explicit value form:
```bash
exportnotes.zsh --update-all true
```

Convert notes to Markdown (boolean flag form):
```bash
exportnotes.zsh --convert-markdown
```

Or using explicit value form:
```bash
exportnotes.zsh --convert-markdown true
```

Convert notes to PDF (boolean flag form):
```bash
exportnotes.zsh --convert-pdf
```

Or using explicit value form:
```bash
exportnotes.zsh --convert-pdf true
```

Convert notes to Word (boolean flag form):
```bash
exportnotes.zsh --convert-word
```

Or using explicit value form:
```bash
exportnotes.zsh --convert-word true
```

Remove conda environment after export (boolean flag form):
```bash
exportnotes.zsh --conda-env exportnotes --remove-conda-env
```

Or using explicit value form:
```bash
exportnotes.zsh --conda-env exportnotes --remove-conda-env true
```

Set via environment variable:
```bash
export NOTES_EXPORT_INCLUDE_DELETED=true
exportnotes.zsh
```

**Note**: All boolean parameters now support two forms for consistency and easier automation:
- **Boolean flag**: Presence of the flag sets it to `true` (e.g., `--include-deleted`, `--convert-markdown`)
- **Explicit value**: Accepts `true` or `false` (e.g., `--include-deleted false`, `--convert-markdown true`)

This applies to: `--update-all`, `--include-deleted`, `--convert-markdown`, `--convert-pdf`, `--convert-word`, and `--remove-conda-env`.

This makes automation easier while maintaining backward compatibility with existing usage.

### Technical Details <!-- omit from toc -->

* Modified `loadNotebookData()` function to accept `includeDeleted` parameter
* Python code in AppleScript now conditionally skips deleted records based on the flag
* Added detailed logging to show whether deleted records are included or excluded
* Backward compatible - existing behavior preserved when flag is not set

## 10 June 2025 - Release 1.0.0 - Incremental Export & Deletion Tracking - BREAKING CHANGES!

In this release, we introduce update mode, making exports up to 5x faster and overall processing including conversions up to 12x faster for everyday use.

This involves breaking changes, so it is recommended that you regenerate your data directories, to improve performance and a few weird design decisions made early on. In particular, the html directory has been broken up into the raw directory for raw extracted html files with embedded images, and the html directory (with html extensions instead of htm) for html with the images broken out into a subdirectory.  Filenames now include the document ID to avoid overwrites of files with the same title, and a new data directory keeps track of what has been read and written allowing for a new default option of only reading documents from Apple Notes, and updating documents already exported where they have changed - including renames. Quite the overhaul, and hopefully you'll notice the difference when exporting regularly.

* **Build versioning introduced**: I'm doing n.n.n style versioning with major versions for big structural changes (like this one - 1.0.0), minor versions (e.g. 1.1.0) for things involving breaking changes, and build numbers for small feature improvements and bug fixes (e.g. 1.1.1).
* **Incremental Export System**: Complete rewrite of conversion scripts to use JSON-based tracking for dramatically improved performance
  * New shared utility module (`notes_export_utils.py`) - only processes notes that have changed since last export
  * Tracks export status per format: `lastExportedToMarkdown`, `lastExportedToPdf`, `lastExportedToWord`, `lastExportedToImages`
  * Subsequent exports are much, much faster as only changed/new notes are processed (by default)
* **Deletion Tracking**: Automatically detects when notes are removed from Apple Notes and marks them with `deletedDate` timestamp
* **Filename Collision Prevention**: Changed default filename format from `&title` to `&title-&id` to ensure unique filenames and avoiding accidental overwrites
* **All-Formats Export**: Added `--all-formats`/`--all`/`-a` flag to read data (raw / text) and export to all formats (HTML, Markdown, PDF, Word, images) in one command
* **Renaming**: When a file is renamed in an update, all converted files are deleted, and all associated images are deleted, and regenerated with new filenames so you don't end up with orphan old copies of documents and images hanging about
* **JSON Tracking Data**: New tracking system using JSON files in `data/` directory to store note metadata and export history - will be expanding on this in future versions
* **Enhanced Character Handling**: Further improved filename sanitization while preserving Unicode characters and international text
* **Performance Optimization**: All Python conversion scripts rewritten for incremental processing - first export same speed, subsequent exports dramatically faster by checking the last modification date
* **File Naming Consistency**: Standardized script filenames to use underscores instead of dashes (e.g., `convert_to_markdown.py`, `extract_images.py`)
* **Update dependencies**: Updated requirements.txt as the library versions were a bit outdated

### Speed comparison - Update mode vs Recreate everything mode <!-- omit from toc -->

| Metric                     | Fresh Export | Update Mode | Speedup (Fresh ÷ Update) |
| -------------------------- | -----------: | ----------: | -----------------------: |
| **AppleScript processing** |        687 s |       129 s |                    5.33× |
| **Other operations**       |        882 s |         1 s |                     882× |
| **Combined total**         |      1 569 s |       130 s |                   12.07× |

* **AppleScript processing** in a fresh run takes about 5.3 times as long as in update-only mode.
* **Conversion/other operations** take some 882 times longer when re-exporting everything.
* **Overall**, a full fresh export is roughly **12 times** slower than simply checking for updates with no changes.

This uses a sample size of 769 notes, many including a lot of images embedded, exporting to HTML, Docx, Markdown and PDF (as well as the default raw html and text formats).

## 6 June 2025 - Release 0.3 - Automated Scheduling & Output Improvements

### New Features <!-- omit from toc -->
* **Automated Scheduling System**: Added comprehensive LaunchD scheduling support for macOS
  * New Python script (`setup_launchd.py`) for creating, managing, and debugging scheduled exports
  * Automatic wrapper script generation that properly sources shell environment and conda
  * Support for both daily scheduling (`--hour`, `--minute`) and interval-based scheduling (`--interval`)
  * Complete job lifecycle management: `--load`, `--unload`, `--test`, `--status`, `--remove`, `--debug`
  * Automatic permission handling and environment variable setup
  * Comprehensive logging with separate stdout/stderr streams
  * Smart job reloading that automatically unloads existing jobs before loading new ones

### Improvements <!-- omit from toc -->
* **Better Output Handling**: Modified AppleScript to properly route informational messages to stdout and errors to stderr
* **Combined Commands**: Support for chaining multiple actions in a single command (e.g., `--hour 22 --minute 15 --load --test`)
* **Environment File Support**: Added `.env` file support for custom environment variables in scheduled jobs
* **Enhanced Debugging**: Added comprehensive debugging tools to troubleshoot scheduling and permission issues
* **Documentation**: Added detailed scheduling section to README.md with setup instructions and troubleshooting

### Bug Fixes <!-- omit from toc -->
* Fixed AppleScript filename validation to handle edge case where removing trailing dash could result in empty filename
* Improved error handling for file write operations in AppleScript
* Fixed permission issues that could cause "Input/output error" when loading jobs
* Enhanced environment variable detection and sourcing for scheduled execution

### Technical Details <!-- omit from toc -->
* LaunchD integration provides more reliable scheduling than cron for GUI applications
* Automatic detection of conda installations and proper environment activation
* Support for multiple scheduling patterns and easy reconfiguration
* Comprehensive permission setup guide for macOS security requirements

## 10 June 2024 - Release 0.2 - Filename format / other file types

* `--filename-format` Format of main part of filename before the filetype for word/pdf/html - default is &title but can contain &title for a santitized version of the title (note this can change), and / or &id for the internal id apple uses for the note to generate a filename with a specific format. Thanks to @cromulus for the suggestion and sample code - I decided rather than to have an ID option to have a more general file format option so if more file format requirements appear, we don't need to have lots of new command line options / environment variables!
* Similar for `--subdir-format` - the notes folder subdirectory is now optional and can be formatted
* Added requirements.txt to pip install easily
* Option to create / teardown conda environment before / after running
* Use python instead of python3 in case using conda
* Update README.md to include better install instructions, including miniconda
* Fix issue where problematic parameters could cause an infinite while loop in shell script

## 8 December 2023 - Release 0.1 - Initial Release

Initial release with features like:

* Load data from all Apple Notes linked accounts and folders as HTML and Text - great for a basic backup
* Extract embedded attachments from HTML and put into subfolder as .htm files
* Convert to PDF files with embedded images
* Convert to Word (.DOCX) files with embedded images
* Convert to Markdown format with files in a subfolder (e.g. for use in another note-taking tool like Obsidian)
* Command line parameters and environment variables to help customize how to use the tool