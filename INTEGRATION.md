# Integration Guide <!-- omit from toc -->

How another program (a media server, a search index, a backup job) can drive
notes-exporter and read its results without parsing human output. Everything
on this page is a **stable contract**, versioned separately from the tool:

| Contract | Version | Where |
|---|---|---|
| Manifest | `"format": "notes-exporter.manifest"`, `"version": 1` | `<root>/manifest.json` |
| Event stream | `--json-log`, `manifest_version: 1` in the `start` event | stdout or a file |
| Exit codes | 0–5, below | process exit status |

To use an export over HTTP instead of running the exporter yourself, see
[SERVICE-API.md](SERVICE-API.md): `notes-exporter serve` runs and schedules
exports and serves this manifest and the files.

Within version 1, fields are only ever **added**. A reader must ignore fields
it does not know. A change that removes or changes the meaning of a field
bumps `version`. `exportnotes.zsh --json-log --version` prints the tool
version and the manifest version it writes.

- [Recommended invocation](#recommended-invocation)
- [Exit codes](#exit-codes)
- [The event stream (`--json-log`)](#the-event-stream---json-log)
- [The manifest (`manifest.json`)](#the-manifest-manifestjson)
  - [`run`](#run)
  - [`accounts`](#accounts)
  - [`notes`](#notes)
  - [`deleted`](#deleted)
  - [`skipped`](#skipped)
  - [`books`](#books)
- [Renames, moves and deletes](#renames-moves-and-deletes)
- [Locking](#locking)
- [macOS permissions](#macos-permissions)
- [Environment variables](#environment-variables)
- [What the exporter cannot see](#what-the-exporter-cannot-see)

## Recommended invocation

```bash
/path/to/notes-exporter/exportnotes.zsh \
    --root-dir /path/to/export \
    --python /path/to/venv/bin/python \
    --folder-hierarchy \
    --convert-markdown true --html-wrap true \
    --exclude-folders "Recently Deleted" \
    --json-log --non-interactive
```

- `--folder-hierarchy` puts each note under `<account>/<folder>/<subfolder>/`
  (the same as `--subdir-format '&account/&folderpath'`). Without it folders
  are flattened to `<account>-<folder>`; `folder_path` in the manifest is
  nested either way.
- `--python` (or `NOTES_EXPORT_PYTHON`) names the interpreter; it must have
  `requirements.txt` installed. Without it the script uses `--venv-dir`, a
  `python3` that already has the dependencies, or creates
  `<tool>/.venv` itself.
- `--exclude-folders "Recently Deleted"` matters: to AppleScript, Notes'
  *Recently Deleted* is an ordinary folder, so without it a deleted note
  looks like a note **moved** into a folder called "Recently Deleted" (and
  is reported in `deleted` only when Notes purges it, 30 days later). With
  it, a deleted note is in `deleted` after the next run. Use the folder's
  name in the Mac's language.
- `--non-interactive` fails with exit code 3 instead of waiting at a macOS
  permission prompt nobody will answer.
- Add `--prune-deleted true` to have the exporter remove files of notes
  deleted in Notes (their record stays, with `removed_outputs`).
- Add `--convert-epub true` for one EPUB 3 per note, and `--epub-books folder`
  for one EPUB per Notes folder (see [`books`](#books)).
- Add `--tags true` for real Notes `#tags`, pinned and checklist flags (needs
  Full Disk Access, see [below](#what-the-exporter-cannot-see)).
- Never pass `--sync` / `--sync-only` unless you mean to write into Apple
  Notes.

Run it with a clean environment: every option has a `NOTES_EXPORT_*`
variable, and variables you inherit from a shell rc file change the run.

## Exit codes

| Code | Meaning | Manifest |
|---|---|---|
| 0 | Success | written, `status: "ok"` |
| 1 | Could not start: bad option, no usable Python, missing dependencies, not macOS | not written |
| 2 | Partial: the run finished but some notes or steps failed | written, `status: "partial"`, failures in `skipped` |
| 3 | Notes automation refused (-1743), or with `--non-interactive` macOS would ask | written if the export had started, `status: "failed"` |
| 4 | Another export holds the lock on this root directory | not touched |
| 5 | The export failed (an AppleScript error stopped it) | written, `status: "failed"` |

Locked (password-protected) notes alone do not make a run partial: they are
listed in `skipped` with reason `locked` and the run is `ok`.

## The event stream (`--json-log`)

`--json-log` writes JSON Lines events to **stdout**, and moves all human
output to stderr, so stdout is pure JSON. `--json-log FILE` appends the
events to FILE instead and leaves human output on stdout.

Each line is one object with `type` and `time` (ISO 8601 with offset):

| `type` | Fields | When |
|---|---|---|
| `start` | `version`, `run_id`, `root_dir`, `mode`, `formats`, `manifest_version` | first |
| `permission` | `state`: `allowed`, `prompt`, `denied`, `not-running`, `unknown(…)` | before reading Notes |
| `plan` | `stage: "export"`, `folders` | the folders to read are known |
| `progress` | `stage`, `done`, `total`, `unit` (`folders` or `notes`); export adds `account`, `folder`, `notes_in_folder`, `notes_exported`; conversions add `failed` | throttled to about 4 a second per stage; the first and last always |
| `stage` | `stage`, `status`: `started`, `finished`, `failed`; `exit_code` on failure | around each pipeline step |
| `note_error` | `stage`, `note_id`, `message` or `filename` | a note could not be exported or converted |
| `message` | `level` (`warning`, `error`), `message`, `stage` | anything else worth showing |
| `manifest` | `path`, `notes`, `changed`, `deleted`, `deleted_this_run`, `skipped` | the manifest was written |
| `result` | `status` (`ok`, `partial`, `failed`), `exit_code`, `run_id`, `manifest`, `elapsed_seconds`, `message` on failure | last |
| `version` | `version`, `manifest_version` | only for `--json-log --version` |

Stages, in order: `export`, `tracking`, `tidy`, `tags`, `images`, `markdown`,
`pdf`, `word`, `epub`, `books`, `dates`, `prune`, `sync`, `qdrant` (only the
ones the options turn on). `books` progress counts `books`, not notes. New event types and fields may appear; ignore what you don't know.

## The manifest (`manifest.json`)

Written to `<root>/manifest.json` at the end of every run that got as far as
reading Notes, **including failed and partial ones**. It is written to a
temporary file and renamed, so a reader never sees half a manifest. It
describes the whole export, not just this run: use `changed_this_run` and
`deleted_this_run` for what this run did.

```jsonc
{
  "format": "notes-exporter.manifest",
  "version": 1,
  "run": { ... },
  "accounts": [{"id": "x-coredata://4D3C…/ICAccount/p1", "name": "iCloud"}],
  "notes": [ ... ],
  "deleted": [ ... ],
  "skipped": [ ... ],
  "books": [ ... ],
  "deleted_books": [ ... ]
}
```

All paths are **relative to the root directory**, with `/` separators.
All dates are ISO 8601 with a UTC offset, or `null` when unknown.

### `run`

| Field | Type | Notes |
|---|---|---|
| `id` | string | a UUID per run; also in the events |
| `sequence` | int | 1 for the first manifest in this root, then +1 per run |
| `started_at`, `finished_at` | ISO date | |
| `mode` | `incremental`, `full` (`--update-all`), `sync-only` | |
| `status` | `ok`, `partial`, `failed` | matches the exit code |
| `exit_code` | int | |
| `tool_version` | string | e.g. `1.4.0` |
| `root_dir` | string | absolute |
| `formats` | list | of `raw`, `text`, `html`, `md`, `pdf`, `docx`, `epub` |
| `filename_format`, `subdir_format`, `use_subdirs` | | the layout used |
| `filters` | object | `accounts`, `folders`, `exclude_folders`, `modified_after` (strings, empty when unused) |
| `notes_examined`, `notes_exported`, `notes_unchanged`, `errors`, `step_failures` | int | this run |
| `counts` | object | `notes`, `changed`, `deleted`, `deleted_this_run`, `skipped`, `books` |

A run with `filters` set only looked at part of the library: notes outside
the filter keep their previous entries and are not reported deleted.

### `accounts`

`id` is the Notes account id (`x-coredata://<store>/ICAccount/p<n>`), `name`
the account name.

### `notes`

One entry per note currently in the export, sorted by `id`.

| Field | Type | Notes |
|---|---|---|
| `id` | string | the Notes id, `x-coredata://<store>/ICNote/p<n>`. **The identity**: stable across renames and moves within an account. A note moved to another account gets a new id. Records from exports made before 1.3.0 that never re-exported have `legacy:<tracker>/<n>` |
| `short_id` | string | the `p<n>` number, as used in `&id` filenames |
| `account_id`, `account` | string | |
| `folder_id` | string | the Notes folder id |
| `folder_path` | list of strings | the folder and its parents, top first, e.g. `["Recipes", "Baking"]` |
| `title` | string | the note's name |
| `created`, `modified` | ISO date | from Notes |
| `tags` | list of strings | without `#`, see `tags_source` |
| `tags_source` | `database`, `text` or `null` | `database`: read from Notes' own store with `--tags`. `text`: hashtags found in the plain text, a best guess (Notes keeps real tags out of the text AppleScript sees, so this is often empty) |
| `locked`, `shared` | bool | from Notes |
| `pinned`, `checklist` | bool or `null` | only known with `--tags`; `null` otherwise |
| `filename` | string | the file name without extension |
| `tracker` | string | the tracking file in `data/` this note is recorded in |
| `outputs` | object | format → `{path, sha256, bytes}` for each file that exists |
| `previous_outputs` | object | format → old path, when this run renamed or moved the note (see below); `{}` otherwise |
| `attachments` | list | `{id, name, kind, media_type, path, sha256, bytes}`; `kind` is `image`, `pdf`, `audio`, `video` or `file`. Found from the links in the HTML output, else by file name. `id` is `<short_id>:<name>` |
| `changed_this_run` | bool | anything above changed since the previous manifest (content hashes, paths, title, folder, dates, tags, flags) |
| `changed_in_run` | int | the `run.sequence` that last changed it |
| `fingerprint` | string | a short hash of the fields compared for `changed_this_run` |
| `last_exported` | string | when the exporter last wrote it |

### `deleted`

Notes that were in Notes and no longer are. Entries stay (tombstones), so a
reader that missed a run still sees the deletion.

| Field | Type | Notes |
|---|---|---|
| `id`, `short_id`, `account_id`, `folder_path`, `title` | | as for notes |
| `deleted_at` | ISO date | when the exporter noticed |
| `removed_outputs` | list of paths | files the exporter removed (`--prune-deleted`) |
| `remaining_outputs` | list of paths | the note's files still on disk |
| `deleted_this_run` | bool | new in this run, or its files were removed in this run |
| `deleted_in_run` | int or `null` | the `run.sequence` that recorded the deletion (or last removed its files); `null` for tombstones written before 1.5.0 |

A note is only recorded as deleted after a run that **listed every note of
its folder** to the end. A failed or interrupted run never records
deletions, and a folder left out by a filter is not looked at.

### `skipped`

Notes this run could not export: `{id, short_id, reason, message, title}`
with `reason` `locked` (password-protected) or `error` (with Notes' error
message). A skipped note that was exported before keeps its entry in
`notes` with its old files.

### `books`

With `--epub-books folder`, one EPUB 3 per Notes folder, in
`epub-books/<account>/<folder path>.epub` (each folder name a path segment;
`/`, `\` and `:` become `-`). Each note of the folder is a chapter (its HTML
output as XHTML, with the images it shows packaged once per book), and the
table of contents lists the note titles. Chapters are ordered by
`--epub-book-order`: `modified` (default) or `created`, newest first, or `title`.
With `--epub-book-subfolders separate` (default) every folder with notes is its
own book; with `nested` a top-level folder's book holds its subfolders as parts
(a nested table of contents) and subfolders get no book of their own.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `<account_id>/<folder_id>`; when a nested book's top folder holds no notes itself its id is `path:<name>` in place of the folder id |
| `account_id`, `folder_id` | string | |
| `folder_path` | list of strings | the folder the book is for |
| `title` | string | the folder's name |
| `path`, `sha256`, `bytes` | | the file |
| `notes` | list of ids | the notes in the book, in book order |
| `nested_folders` | list of folder ids | the subfolders included (`nested` only) |
| `skipped_notes` | int | notes of the folder left out: locked, or without an HTML output |
| `changed_this_run`, `changed_in_run` | bool, int | the file or its membership changed in this run |
| `fingerprint` | string | what the book was built from |

A book is rebuilt only when one of its notes, their order, their images, or the
options changed; otherwise the file is left as it is (EPUBs are written
deterministically, so a rebuild of the same notes gives the same bytes). A
folder with no notes left (all deleted or moved away, the folder deleted) has no
book: its file is removed and a tombstone goes into `deleted_books`
(`{id, folder_path, path, deleted_at}`). Runs without `--epub-books folder`
leave existing books alone. State lives in `data/.epub_books.json`.

Per-note EPUBs (`--convert-epub`) appear as `outputs.epub` like any other
format. Each is EPUB 3 with `mimetype` first and stored, `nav.xhtml` and
`toc.ncx`, the note id as a URN (`urn:x-apple-notes:<percent-encoded id>`) in
`dc:identifier`, its modified date as `dc:date` and `dcterms:modified`, created
as `dcterms:created`, and the account and folder path as `dc:subject`.
`dc:language` is `NOTES_EXPORT_EPUB_LANGUAGE` or `und`. Images missing from disk
or on the web are left out with a `message` warning event; HEIC and TIFF images
are converted to JPEG (Pillow or `sips`) or left out.

## Renames, moves and deletes

| In Notes | In the manifest | On disk |
|---|---|---|
| Edited | `changed_this_run: true`, new `sha256` | files rewritten in place |
| Renamed (with `&title` in the filename format) | `previous_outputs` with the old paths | old files and attachments already removed |
| Moved to another folder | new `folder_path`, `previous_outputs` | exported again in the new folder; the old copy removed |
| Moved to another account | a new `id`; the old one in `deleted` | as a delete plus an add |
| Deleted (into *Recently Deleted*) | in `deleted`, when that folder is excluded; otherwise a move into it | files kept, unless `--prune-deleted` |
| Purged from *Recently Deleted* | in `deleted` | files kept, unless `--prune-deleted` |
| Locked after export | in `skipped` (`locked`), entry kept in `notes` | old files kept |

When `previous_outputs` is given, the old files are gone by the time the
manifest is written, so a reader can re-point its records at the new path.

## Locking

One export runs per root directory. The script creates
`<root>/.notes-exporter.lock/` (with the process id in `pid`) and removes
it on exit. A second run exits with code 4 and touches nothing. A lock
whose process no longer exists is taken over.

## macOS permissions

- **Automation (required).** Reading Notes needs the app that started the
  export (Terminal, a launchd job, your server's app) to be allowed in
  *System Settings > Privacy & Security > Automation > Notes*. The script
  checks first without asking (`notes_permission.py`): with
  `--non-interactive` a check that would prompt is exit code 3. Run one
  export interactively while someone is at the Mac to grant it.
  `NOTES_EXPORT_SKIP_PERMISSION_CHECK=true` skips the check.
- **Full Disk Access (only for `--tags`).** Tags, pinned and checklist flags
  come from a copy of Notes' database, which needs Full Disk Access for the
  same app. Without it `--tags` logs a warning and the run is partial.

## Environment variables

Every option has a variable (see [REFERENCE.md](REFERENCE.md#environment-variables)).
The ones specific to integration:

| Variable | Option | |
|---|---|---|
| `NOTES_EXPORT_ROOT_DIR` | `--root-dir` | |
| `NOTES_EXPORT_PYTHON` | `--python` | interpreter with the requirements |
| `NOTES_EXPORT_JSON_LOG` | `--json-log [FILE]` | `-` for stdout |
| `NOTES_EXPORT_NON_INTERACTIVE` | `--non-interactive` | |
| `NOTES_EXPORT_SUBDIR_FORMAT` | `--subdir-format`, `--folder-hierarchy` | `&account/&folderpath` for nested folders |
| `NOTES_EXPORT_PRUNE_DELETED` | `--prune-deleted` | |
| `NOTES_EXPORT_TAGS` | `--tags` | |
| `NOTES_EXPORT_CONVERT_EPUB` | `--convert-epub` | |
| `NOTES_EXPORT_EPUB_BOOKS` | `--epub-books` | `none` or `folder` |
| `NOTES_EXPORT_EPUB_BOOK_ORDER` | `--epub-book-order` | `modified`, `created`, `title` |
| `NOTES_EXPORT_EPUB_BOOK_SUBFOLDERS` | `--epub-book-subfolders` | `separate`, `nested` |
| `NOTES_EXPORT_EPUB_LANGUAGE` | | `dc:language` of EPUBs (BCP 47; default `und`) |
| `NOTES_EXPORT_SKIP_PERMISSION_CHECK` | | `true` to skip the automation pre-check |
| `NOTES_EXPORT_NOTES_DB` | | another NoteStore.sqlite for `--tags` (tests) |
| `NOTES_EXPORT_CHROME` | | the Chrome binary for PDF output |

## What the exporter cannot see

- **Locked notes**: AppleScript cannot read password-protected notes. They
  are listed in `skipped`.
- **Tags, pinned, checklists**: not visible to AppleScript; `--tags` reads
  them from the database (Full Disk Access).
- **Attachments other than images**: AppleScript gives the note body with
  images inline; PDFs, audio and other files are not exported yet.
- ***Recently Deleted***: AppleScript shows it as a normal folder; exclude
  it (above) to see deletions straight away. Records exported from it by
  earlier runs stay in the manifest until removed.
