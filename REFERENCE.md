# Technical Reference

Complete reference for all CLI options, environment variables, JSON schemas, file structure, and Python APIs.

## Commands

### exportnotes.zsh

Main export script. Orchestrates AppleScript extraction, image processing, format conversion, sync, and Qdrant indexing.

### query_notes.py

Search exported notes by text, regex, date, images, or semantic similarity.

### sync_to_notes.py

Sync local markdown changes back to Apple Notes.

### qdrant_integration.py

Manage Qdrant vector database: sync, search, status, check, reset.

### reconcile.py

Compare note counts across Apple Notes, tracking JSON, disk files, and Qdrant.

### setup_launchd.py

Configure scheduled automatic exports via macOS launchd.

---

## CLI Options: exportnotes.zsh

### Export Control

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--root-dir DIR` | `-r` | `~/Downloads/AppleNotesExport` | Output directory |
| `--extract-data` | `-d` | `true` | Extract from Apple Notes |
| `--extract-images` | `-i` | `true` | Extract images from HTML |
| `--extract-pdf-attachments` | — | `false` | Copy original PDFs and link from Markdown |
| `--convert-markdown` | `-m` | `false` | Convert to Markdown |
| `--convert-pdf` | `-p` | `false` | Convert to PDF |
| `--convert-word` | `-w` | `false` | Convert to Word (DOCX) |
| `--all-formats` | `-a` | — | Enable all conversions |
| `--update-all` | `-U` | `false` | Force full re-export |
| `--include-deleted` | `-I` | `false` | Include deleted records |
| `--clean` | `-C` | `false` | Clear output dirs before export |

### Filtering

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--filter-accounts LIST` | `-A` | — | Comma-separated account names |
| `--filter-folders LIST` | `-F` | — | Comma-separated folder names |
| `--note-limit NUM` | `-n` | — | Max total notes |
| `--note-limit-per-folder NUM` | `-f` | — | Max notes per folder |
| `--note-pick-probability NUM` | `-b` | `100` | % probability per note |
| `--modified-after DATE` | — | — | Only notes modified after date |

### File Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--filename-format FORMAT` | `-t` | `&title-&id` | Filename template |
| `--subdir-format FORMAT` | `-u` | `&account-&folder` | Subdirectory template |
| `--use-subdirs` | `-x` | `true` | Use subdirectories |
| `--suppress-header-pdf` | `-s` | `true` | No headers in PDF |
| `--set-file-dates` | `-D` | `false` | Set filesystem dates |
| `--no-overwrite` | `-O` | `false` | Skip existing files |
| `--images-beside-docs` | — | `false` | Images next to files |
| `--html-wrap` | — | `false` | Proper HTML page tags |
| `--dedup-images` | — | `false` | Deduplicate images |

### Sync

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--sync` | `-S` | `false` | Sync after export |
| `--sync-only` | — | `false` | Sync without exporting |
| `--sync-dry-run` | — | `false` | Preview sync |
| `--create-new` | — | `false` | Create new notes from local files |
| `--conflict STRATEGY` | — | `abort` | `abort`, `local`, or `remote` |

### Qdrant & Search

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--update-qdrant` | — | `false` | Sync to Qdrant after export |
| `--query PATTERN` | `-Q` | — | Search notes (passes to query_notes.py) |

### Environment

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--venv-dir DIR` | `-v` | — | Python virtual environment |
| `--remove-venv` | — | `false` | Remove venv after export |
| `--conda-env NAME` | `-c` | — | Deprecated, maps to `--venv-dir` |
| `--remove-conda-env` | `-e` | — | Deprecated, maps to `--remove-venv` |

### Filename Format Placeholders

| Placeholder | Description |
|-------------|-------------|
| `&title` | Sanitized note title |
| `&id` | Apple Notes internal ID |
| `&account` | Account name |
| `&folder` | Folder name |
| `&accountid` | Account UUID |
| `&shortaccountid` | Short account ID |

All boolean options accept: flag only (implies `true`), explicit `true`/`false`, or environment variable.

---

## CLI Options: query_notes.py

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `pattern` | — | required | Search term or regex |
| `--regex` | `-E` | `false` | Treat pattern as regex |
| `--ignore-case` | `-i` | `false` | Case-insensitive |
| `--context NUM` | `-c` | `0` | Context lines |
| `--files-only` | `-l` | `false` | List files only |
| `--max-matches NUM` | `-m` | `0` | Max matches per file |
| `--format LIST` | — | auto | Formats to search: `md`, `html`, `text`, `raw` |
| `--filter-folders LIST` | `-F` | — | Folder filter |
| `--has-images` | — | — | Only notes with images |
| `--no-images` | — | — | Only notes without images |
| `--created-after DATE` | — | — | Created after (YYYY-MM-DD) |
| `--created-before DATE` | — | — | Created before |
| `--modified-after DATE` | — | — | Modified after |
| `--modified-before DATE` | — | — | Modified before |
| `--created-within SPAN` | — | — | Created within timespan |
| `--modified-within SPAN` | — | — | Modified within timespan |
| `--ai-search` | — | `false` | Semantic search via Qdrant |
| `--num-results NUM` | `-n` | `10` | AI search result count |
| `--threshold FLOAT` | — | `0.0` | Minimum similarity (0.0-1.0) |
| `--json-log [FILE]` | — | — | JSON Lines output |
| `--root-dir DIR` | `-r` | — | Override export directory |

### Timespan Format

`NUMBER` + `UNIT`: `5h`, `3d`, `2w`, `2m`, `1y`, `30s`, `15min`

| Unit | Meaning |
|------|---------|
| `s`, `sec` | Seconds |
| `min` | Minutes |
| `h`, `hr`, `hours` | Hours |
| `d`, `day`, `days` | Days |
| `w`, `week`, `weeks` | Weeks |
| `m`, `month`, `months` | Months (30 days) |
| `y`, `year`, `years` | Years (365 days) |

Fractional values supported: `1.5d`, `0.5h`.

---

## CLI Options: qdrant_integration.py

### Subcommands

| Command | Description |
|---------|-------------|
| `sync` | Sync changed notes to Qdrant (incremental) |
| `search QUERY` | Semantic search |
| `status` | Show collection info |
| `check` | Verify prerequisites (Docker, Qdrant, Ollama) |
| `dry-run` | Preview what sync would do |
| `reset` | Delete collection and start fresh |

### Sync Options

| Option | Default | Description |
|--------|---------|-------------|
| `--force` | `false` | Re-embed all notes |
| `--chunk-size NUM` | `800` | Characters per chunk |
| `--chunk-overlap NUM` | `200` | Overlap between chunks |

### Search Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `-n`, `--limit` | — | `10` | Result count |
| `--threshold` | — | `0.0` | Minimum similarity |

### Global

| Option | Description |
|--------|-------------|
| `--json-log [FILE]` | JSON Lines output |

---

## CLI Options: reconcile.py

| Option | Default | Description |
|--------|---------|-------------|
| `--notebooks` | `false` | Per-notebook breakdown |
| `--details` | `false` | List specific exceptions |
| `--fix` | `false` | Show fix suggestions |
| `--skip-apple` | `false` | Skip Apple Notes query (faster) |
| `--skip-qdrant` | `false` | Skip Qdrant query (faster) |
| `--json-log [FILE]` | — | JSON Lines output |

---

## CLI Options: sync_to_notes.py

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | `false` | Preview sync |
| `--create-new` | `false` | Create new notes from unmatched files |
| `--conflict STRATEGY` | `abort` | `abort`, `local`, `remote` |
| `--filter-folders LIST` | — | Folder filter |
| `--filter-accounts LIST` | — | Account filter |
| `--json-log [FILE]` | — | JSON Lines output |

---

## Environment Variables

### Export

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_ROOT_DIR` | `~/Downloads/AppleNotesExport` | Output directory |
| `NOTES_EXPORT_EXTRACT_DATA` | `true` | Extract from Apple Notes |
| `NOTES_EXPORT_EXTRACT_IMAGES` | `true` | Extract images |
| `NOTES_EXPORT_CONVERT_TO_MARKDOWN` | `false` | Convert to Markdown |
| `NOTES_EXPORT_CONVERT_TO_PDF` | `false` | Convert to PDF |
| `NOTES_EXPORT_CONVERT_TO_WORD` | `false` | Convert to Word |
| `NOTES_EXPORT_UPDATE_ALL` | `false` | Force full re-export |
| `NOTES_EXPORT_INCLUDE_DELETED` | `false` | Include deleted records |
| `NOTES_EXPORT_CLEAN` | `false` | Clear output dirs first |
| `NOTES_EXPORT_SET_FILE_DATES` | `false` | Set filesystem dates |
| `NOTES_EXPORT_NO_OVERWRITE` | `false` | Skip existing files |
| `NOTES_EXPORT_MODIFIED_AFTER` | — | Date filter |
| `NOTES_EXPORT_IMAGES_BESIDE_DOCS` | `false` | Images next to files |
| `NOTES_EXPORT_HTML_WRAP` | `false` | HTML page tags |
| `NOTES_EXPORT_DEDUP_IMAGES` | `false` | Deduplicate images |

### Filenames & Directories

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_FILENAME_FORMAT` | `&title-&id` | Filename template |
| `NOTES_EXPORT_SUBDIR_FORMAT` | `&account-&folder` | Subdirectory template |
| `NOTES_EXPORT_USE_SUBDIRS` | `true` | Use subdirectories |
| `NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF` | `true` | No PDF headers |

### Filtering

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_FILTER_ACCOUNTS` | — | Comma-separated account names |
| `NOTES_EXPORT_FILTER_FOLDERS` | — | Comma-separated folder names |
| `NOTES_EXPORT_NOTE_LIMIT` | — | Max total notes |
| `NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER` | — | Max per folder |
| `NOTES_EXPORT_NOTE_PICK_PROBABILITY` | `100` | % probability |

### Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_SYNC` | `false` | Run sync after export |
| `NOTES_EXPORT_SYNC_ONLY` | `false` | Sync without export |
| `NOTES_EXPORT_SYNC_DRY_RUN` | `false` | Preview sync |
| `NOTES_EXPORT_CREATE_NEW` | `false` | Create new notes |
| `NOTES_EXPORT_CONFLICT_STRATEGY` | — | `abort`, `local`, `remote` |

### Qdrant

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_UPDATE_QDRANT` | `false` | Sync to Qdrant |
| `NOTES_EXPORT_QDRANT_URL` | `http://localhost:6333` | Qdrant URL |
| `NOTES_EXPORT_QDRANT_API_KEY` | — | API key (Qdrant Cloud) |
| `NOTES_EXPORT_QDRANT_COLLECTION` | `apple_notes` | Collection name |
| `NOTES_EXPORT_CHUNK_SIZE` | `800` | Chars per chunk |
| `NOTES_EXPORT_CHUNK_OVERLAP` | `200` | Overlap between chunks |

### Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_EMBEDDING_PROVIDER` | `ollama` | `ollama` or `sentence-transformers` |
| `NOTES_EXPORT_OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `NOTES_EXPORT_OLLAMA_MODEL` | `mxbai-embed-large` | Ollama model |
| `NOTES_EXPORT_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_EXPORT_VENV_DIR` | — | Python venv directory |
| `NOTES_EXPORT_REMOVE_VENV` | `false` | Remove venv after export |

### Testing

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTES_TEST_LIMIT` | `10` | Max items per test (0 = unlimited) |

---

## JSON Tracking Schema

Each note in `data/*.json`:

```json
{
  "note_id": {
    "filename": "My-Note-1234",
    "created": "Monday, January 1, 2024 at 9:00:00 AM",
    "modified": "Tuesday, January 2, 2024 at 10:00:00 AM",
    "firstExported": "2024-01-15 14:30:45",
    "lastExported": "2024-01-20 09:15:30",
    "exportCount": 5,
    "fullNoteId": "x-coredata://UUID/ICNote/p1234",
    "lastExportedToMarkdown": "2024-01-20 09:15:30",
    "lastExportedToPdf": "2024-01-20 09:15:30",
    "lastExportedToWord": "2024-01-20 09:15:30",
    "lastExportedToImages": "2024-01-20 09:15:30",
    "lastSyncedToNotes": "2024-01-21 10:00:00",
    "localFileHashAtLastSync": "sha256hex...",
    "appleNotesModifiedAtLastSync": "Tuesday, January 2, 2024 at 10:00:00 AM",
    "syncCount": 1,
    "syncSource": "markdown",
    "lastIndexedToQdrant": "2024-01-20 09:15:30",
    "qdrantChunkCount": 3,
    "deletedDate": "Wednesday, March 1, 2024 at 12:00:00 PM"
  }
}
```

| Field | Added by | Description |
|-------|----------|-------------|
| `filename` | Export | Sanitized filename stem |
| `created` | Export | Apple Notes creation date |
| `modified` | Export | Apple Notes modification date |
| `firstExported` | Export | First export timestamp |
| `lastExported` | Export | Last export timestamp |
| `exportCount` | Export | Number of times exported |
| `fullNoteId` | Export (v1.3+) | Full Apple Notes ID for sync |
| `lastExportedTo*` | Converters | Per-format export tracking |
| `lastSyncedToNotes` | Sync engine | Last sync-back timestamp |
| `localFileHashAtLastSync` | Sync engine | SHA-256 for change detection |
| `appleNotesModifiedAtLastSync` | Sync engine | Remote date at last sync |
| `syncCount` | Sync engine | Times synced back |
| `syncSource` | Sync engine | Format driving sync |
| `lastIndexedToQdrant` | Qdrant sync | Last Qdrant index timestamp |
| `qdrantChunkCount` | Qdrant sync | Chunks stored in Qdrant |
| `deletedDate` | Export | When note was detected as deleted |

---

## JSON Lines Output Schema

Each JSON line has a `type` field. Consistent key names across all commands:

### Record Types

| Type | Commands | Description |
|------|----------|-------------|
| `match` | query_notes (text) | Text search match |
| `result` | query_notes (AI), qdrant search | Search result |
| `summary` | All | Operation summary |
| `status` | qdrant check/status | System status |
| `count` | reconcile | Count from a source |
| `discrepancy` | reconcile | Mismatch found |
| `detail` | reconcile | Specific exception |
| `synced` | sync_to_notes | Note synced successfully |
| `conflict` | sync_to_notes | Conflict detected |
| `error` | All | Error occurred |

### Key Reference

| Key | Type | Used in | Description |
|-----|------|---------|-------------|
| `type` | string | All | Record type |
| `file` | string | match, result | File path |
| `line_num` | int | match | Line number |
| `line` | string | match | Matched line text |
| `score` | float | result | Similarity score (0-1) |
| `note_id` | string | result, synced | Note identifier |
| `notebook` | string | result, synced, count | Notebook name |
| `filename` | string | result, synced, conflict | Note filename |
| `created` | string | result | Creation date |
| `modified` | string | result | Modification date |
| `total_matches` | int | summary | Match count |
| `matching_files` | int | summary | File count |
| `search_type` | string | summary | `text` or `ai` |
| `total_results` | int | summary | Result count |
| `command` | string | summary, status | Command name |
| `upserted` | int | summary | Notes upserted |
| `deleted` | int | summary | Notes deleted |
| `unchanged` | int | summary | Notes unchanged |
| `skipped` | int | summary | Notes skipped |
| `errors` | int | summary | Error count |
| `synced` | int | summary | Notes synced |
| `conflicts` | int | summary | Conflicts found |
| `collection` | string | status | Qdrant collection |
| `points` | int | status, count | Qdrant points |
| `unique_notes` | int | count | Unique notes in Qdrant |
| `source` | string | count | Data source name |
| `active` | int | count | Active note count |
| `issue` | string | discrepancy | Issue description |
| `message` | string | error | Error message |
| `docker` | bool | status (check) | Docker available |
| `qdrant` | bool | status (check) | Qdrant available |
| `embeddings` | bool | status (check) | Embeddings available |
| `all_ok` | bool | status (check) | All prerequisites met |

---

## Console (Human) Output Format

When `--json-log` is not used, all commands print human-readable output to stdout. Here is what each command outputs:

### query_notes.py (text search)

```
md/iCloud-Notes/Meeting-Notes-1234.md:15
  Discussion about Q1 goals and deadlines

md/iCloud-Notes/Project-Plan-567.md:3
  Phase 1: Research. Phase 2: Implementation

2 match(es) in 2 file(s)                        ← stderr
```

With `-c 2` (context):
```
md/iCloud-Notes/Meeting-Notes-1234.md:15
     14 | Previous line
  >  15 | Discussion about Q1 goals and deadlines
     16 | Next line
```

With `-l` (files only):
```
md/iCloud-Notes/Meeting-Notes-1234.md
md/iCloud-Notes/Project-Plan-567.md

2 file(s) matched                                ← stderr
```

### query_notes.py (AI search)

```
1. md/iCloud-Notes/Recipe-Chicken-Curry-2.md  [71.5% match]
   Modified: Wednesday, 24 July 2024 at 22:51:54

2. md/iCloud-Notes/Meal-Planning-45.md  [65.2% match]
   Modified: Monday, 1 January 2026 at 10:00:00

2 result(s) from AI search                       ← stderr
```

### qdrant_integration.py sync

```
Embedding 50 changed notes (800 unchanged, skipping those)...
Upserting 312 points to Qdrant...
Deleting 5 removed notes from Qdrant...
Qdrant sync: 312 upserted, 800 unchanged, 5 deleted, 2 skipped, 0 errors
```

### qdrant_integration.py status

```
Collection: apple_notes
Exists: True
Points: 15347
```

### qdrant_integration.py check

```
=== Qdrant Integration Prerequisites ===

  Docker: running
  Qdrant: responding at http://localhost:6333
  Ollama: running, model 'mxbai-embed-large' available

All prerequisites met. Ready to sync.
```

### reconcile.py

```
============================================================
APPLE NOTES RECONCILIATION REPORT
============================================================

--- Apple Notes (live) ---
Total notes in Apple Notes: 841

--- Tracking JSON ---
Active notes tracked: 842
Deleted notes tracked: 11
With fullNoteId (sync-ready): 841

--- Exported Files on Disk ---
  raw/: 853 files
  html/: 851 files
  md/: 851 files

--- Qdrant Vector Database ---
Collection: apple_notes
Total points (chunks): 15347
Unique notes indexed: 839

--- Comparison ---
Source                            Count
----------------------------------------
Apple Notes (live)                  841
Tracking JSON (active)              842
Qdrant (unique notes)               839

--- Discrepancies ---
  * Tracking JSON has 1 more active notes than Apple Notes.

============================================================
```

With `--details`, adds specific exceptions:
```
--- Specific Exceptions ---

  [iCloud-Notes] Orphan raw/ files (on disk but not tracked, 2):
    - some-orphan-file
  [iCloud-Notes] Deleted note still on disk: Old-Note-123
    Formats: raw, md, html
    Deleted: Thursday, 24 July 2025 at 00:17:21
```

### sync_to_notes.py

```
  Syncing: My-Note-123 -> Apple Notes
    Synced successfully
  CONFLICT: Other-Note-456.md - both sides changed. Created Other-Note-456.conflict.md

SYNC SUMMARY:
  Synced to Apple Notes: 1
  New notes created: 0
  Skipped (no changes): 45
  Conflicts: 1
  Errors: 0
```

### exportnotes.zsh

```
Running in INCREMENTAL UPDATE mode - only modified notes will be processed
Extracting note data...
Extracting images...
Converting to Markdown...

====================================
Export completed successfully!
Total elapsed time: 2m 15s

PROCESSING STATISTICS:
  Folders processed: 5
  Total notes examined: 841
  Notes processed/updated: 12
  Notes skipped (unchanged): 829

PERFORMANCE METRICS:
  Overall examination rate: 6.2 notes/second
  Update rate: 0.1 notes/second

TIME BREAKDOWN:
  AppleScript processing: 29s (21.5%)
  Other operations: 106s (78.5%)
====================================
```

---

## File Structure

```
notes-exporter/
  exportnotes.zsh              # Main CLI script
  exportnotes_wrapper.zsh      # Wrapper for scheduled execution
  export_notes.scpt            # AppleScript: extract from Apple Notes
  sync_notes.scpt              # AppleScript: write back to Apple Notes
  extract_images.py            # Extract base64 images from HTML
  convert_to_markdown.py       # HTML to Markdown
  convert_to_pdf.py            # HTML to PDF (via Chrome)
  convert_to_word.py           # HTML to Word (via Pandoc)
  set_file_dates.py            # Set filesystem timestamps
  notes_export_utils.py        # Shared tracking utilities
  query_notes.py               # Search tool
  sync_to_notes.py             # Sync engine
  sync_notes_bridge.py         # Python-AppleScript bridge
  sync_settings.py             # Settings file handling
  qdrant_integration.py        # Qdrant vector DB management
  reconcile.py                 # Cross-system reconciliation
  output_format.py             # JSON Lines output formatting
  setup_launchd.py             # Scheduling setup
  requirements.txt             # Python dependencies
  .notes-exporter-settings.json # User settings (gitignored)
  .env                         # Environment variables (gitignored)
  tests/
    conftest.py                # Shared fixtures and markers
    test.zsh                   # Test runner script
    test_integration.py        # Integration tests
    test_query_notes.py        # Search tests
    test_sync_to_notes.py      # Sync tests
    test_sync_bridge.py        # Bridge tests
    test_qdrant_integration.py # Qdrant tests
    test_reconcile.py          # Reconciliation tests
    test_embed_images.py       # Image embedding tests
    test_settings.py           # Settings tests
    test_output_format.py      # JSON output tests
    test_cli_options.py        # CLI option parsing tests
    test_notes_export_utils.py # Tracker utility tests
    test_set_file_dates.py     # File date tests
    test_tracker.py            # Tracker subdirectory tests
```

### Export Output Structure

```
AppleNotesExport/              # NOTES_EXPORT_ROOT_DIR
  data/                        # JSON tracking files
    iCloud-Notes.json
    iCloud-Evernote.json
  raw/                         # Raw HTML (base64 images embedded)
    iCloud-Notes/
      My-Note-1234.html
  html/                        # Processed HTML (images extracted)
    iCloud-Notes/
      My-Note-1234.html
      attachments/
        My-Note-1234-attachment-001.png
  text/                        # Plain text
    iCloud-Notes/
      My-Note-1234.txt
  md/                          # Markdown
    iCloud-Notes/
      My-Note-1234.md
      attachments/
        My-Note-1234-pdf-001-Contract.pdf
  pdf/                         # PDF (via Chrome)
    iCloud-Notes/
      My-Note-1234.pdf
  docx/                        # Word (via Pandoc)
    iCloud-Notes/
      My-Note-1234.docx
```

---

## Tests

### Test Categories (Markers)

| Marker | Description | Example |
|--------|-------------|---------|
| `unit` | Unit tests — fast, no external dependencies | `pytest -m unit` |
| `integration` | Integration tests — runs commands as subprocesses | `pytest -m integration` |
| `search` | Search/query feature tests | `pytest -m search` |
| `sync` | Bidirectional sync tests | `pytest -m sync` |
| `qdrant` | Qdrant vector DB tests | `pytest -m qdrant` |
| `reconcile` | Reconciliation tests | `pytest -m reconcile` |
| `export` | Export feature tests | `pytest -m export` |
| `settings` | Settings/config tests | `pytest -m settings` |
| `json_output` | JSON Lines output tests | `pytest -m json_output` |

Combine markers:
```bash
pytest -m "search and unit"       # Only unit tests for search
pytest -m "search and integration" # Only integration tests for search
pytest -m "not integration"       # Everything except integration
```

### Scope Control

| Method | Description |
|--------|-------------|
| `NOTES_TEST_LIMIT=10` | Default: limit to 10 items per test |
| `NOTES_TEST_LIMIT=0` | Unlimited items |
| `pytest --all-items` | Same as `NOTES_TEST_LIMIT=0` |

### Test Isolation

All tests use temporary directories via the `test_export_dir` fixture. `NOTES_EXPORT_ROOT_DIR` is always overridden to a temp path. No test reads from or writes to the live `~/Downloads/AppleNotesExport/`.

### Test Files

#### test_cli_options.py — 65 tests `[unit, export]`

CLI option parsing via embedded zsh mini-parser.

| Class | Tests | Covers |
|-------|-------|--------|
| `TestBooleanFlagOptions` | 22 | All boolean flags with/without explicit values |
| `TestShortFormOptions` | 11 | Short-form flags (`-m`, `-p`, `-S`, `-O`, etc.) |
| `TestValueOptions` | 12 | Value options (`--root-dir`, `--venv-dir`, `--conflict`, `--modified-after`, conda-to-venv mapping) |
| `TestAllFormatsFlag` | 4 | `--all` enables markdown, pdf, word, images |
| `TestCombinedOptions` | 3 | Multiple flags together, flag-after-flag parsing |

#### test_query_notes.py — 39 tests `[unit, search]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestSearchFile` | 9 | Literal search, regex, case-insensitive, no matches, files-only, context lines, max matches, binary files, multi-encoding |
| `TestNoteHasImages` | 4 | Attachments dir, images beside docs, no matching attachments, no images |
| `TestParseTimespan` | 11 | Hours, days, weeks, months, years, seconds, minutes, long form, fractional, invalid, whitespace |
| `TestParseDateArg` | 3 | ISO format, ISO with time, invalid |
| `TestParseAppleDate` | 3 | 12-hour, 24-hour, empty/None |
| `TestPassesDateFilter` | 7 | No filters, modified after/before, created before, combined, missing date |
| `TestGetNoteDates` | 2 | Lookup from tracking JSON, unknown file returns None |

#### test_qdrant_integration.py — 28 tests `[unit, qdrant]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestConfig` | 2 | Defaults, env var overrides (including API key) |
| `TestChunkText` | 9 | Short text, empty, whitespace, long text splits, overlap, paragraph breaks, no empty chunks, content coverage, custom size |
| `TestMakePointId` | 5 | Deterministic, different IDs, different notebooks, numeric string, different chunks |
| `TestNoteToText` | 1 | Title + content combination |
| `TestQdrantHTTP` | 3 | API key header, no auth, URL trailing slash |
| `TestQdrantNotesManagerSearch` | 3 | Formatted results, empty results, chunk deduplication |
| `TestQdrantNotesManagerStatus` | 2 | Exists, not exists |
| `TestQdrantNotesManagerSync` | 3 | Dry run, failed embed does NOT mark indexed (regression), batch fallback to individual |

#### test_reconcile.py — 8 tests `[unit, reconcile]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestCountTrackingJson` | 1 | Active, deleted, total, fullNoteId counts |
| `TestCountDiskFiles` | 1 | Counts by format |
| `TestFindSpecificDiscrepancies` | 6 | Orphan files, missing disk files, deleted still on disk, missing fullNoteId, missing from Qdrant, clean state (no discrepancies) |

#### test_sync_to_notes.py — 10 tests `[unit, sync]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestComputeFileHash` | 2 | Consistent hash, different content |
| `TestGetSyncStatus` | 5 | No changes, local changed, remote changed, both changed, never synced |
| `TestCreateConflictFile` | 1 | Creates sidecar with both versions |
| `TestSyncEngineDryRun` | 1 | Dry run doesn't call AppleScript |
| `TestFindNewLocalFiles` | 1 | Finds unmatched files, excludes tracked and .conflict.md |

#### test_sync_bridge.py — 8 tests `[unit, sync]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestRunSyncCommand` | 4 | Timeout handling, nonzero exit, temp file write, temp file cleanup |
| `TestUpdateNote` | 1 | Correct operation and parameters |
| `TestCreateNote` | 1 | Correct operation and parameters |
| `TestGetModifiedDate` | 2 | Returns date on success, None on failure |

#### test_embed_images.py — 12 tests `[unit, export]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestEmbedImagesAsBase64` | 7 | Data URIs unchanged, local image, `./` paths, missing image, attachments subdir, non-img HTML, multiple images |
| `TestShouldSkipExisting` | 3 | Enabled+exists skips, disabled doesn't skip, nonexistent doesn't skip |
| `TestWrapHtml` | 2 | DOCTYPE/title/body wrapping, title content |

#### test_settings.py — 10 tests `[unit, settings]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestDefaultSettings` | 2 | Required keys, default values |
| `TestLoadSettings` | 3 | Defaults without file, env var overrides, create_new false |
| `TestSaveDefaultSettings` | 1 | Creates valid JSON |
| `TestApplyCliOverrides` | 4 | Conflict override, create_new, no override preserves, CLI overrides env |

#### test_output_format.py — 16 tests `[unit, json_output]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestIsJsonMode` | 2 | Default false, true after enable |
| `TestEmit` | 4 | No-op when disabled, writes JSON line, multiple emits, non-serializable values |
| `TestAddJsonArg` | 3 | Adds argument, with file path, without flag |
| `TestSetupFromArgs` | 2 | Enables to file, no JSON when not specified |
| `TestJsonOutputConsistency` | 5 | Match/result/summary/discrepancy/error record keys |

#### test_notes_export_utils.py — 19 tests `[unit, export]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestNotesExportTracker` | 15 | Init, directory detection, subdirs, file paths, JSON load/save, notes to process, deletion skip, export marking |
| `TestGetOutputPathFormats` | 4 | Markdown, PDF, Word, HTML paths |

#### test_set_file_dates.py — 10 tests `[unit, export]`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestParseAppleDate` | 5 | 12-hour, AM, non-breaking space, invalid, empty |
| `TestProcessNotebookData` | 5 | Active notes, deleted skip, missing dates, missing file, without subdirs |

#### test_tracker.py — 4 tests `[unit, export]`

Standalone functions testing `_uses_subdirs` and `get_output_path` with/without subdirs.

#### test_integration.py — 29 tests `[integration]`

End-to-end subprocess tests against isolated temp data.

| Class | Markers | Tests | Covers |
|-------|---------|-------|--------|
| `TestQueryNotesIntegration` | `search` | 12 | Text search, regex, case-insensitive, files-only, context, format filter, JSON to stdout, JSON to file, date filter, image filter, max matches |
| `TestReconcileIntegration` | `reconcile` | 5 | Basic, notebooks, details with orphans, JSON output, JSON counts |
| `TestSyncIntegration` | `sync` | 2 | Dry run human output, dry run JSON output |
| `TestQdrantIntegration` | `qdrant` | 4 | Check command, check JSON, status (handles Qdrant down), dry-run JSON |
| `TestSettingsIntegration` | `settings` | 1 | Settings file loaded from disk |
| `TestExportFeaturesIntegration` | `export` | 4 | Help output for query, reconcile, qdrant, sync (verifies --json-log present) |

---

## Settings File Schema

`.notes-exporter-settings.json`:

```json
{
  "editFormat": "markdown",
  "autoRegenerate": {
    "html": true,
    "pdf": false,
    "word": false
  },
  "conflictStrategy": "abort",
  "syncSource": "markdown",
  "createNewNotes": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `editFormat` | string | `markdown` | Primary edit format |
| `autoRegenerate` | object | — | Formats to regenerate after sync |
| `conflictStrategy` | string | `abort` | `abort`, `local`, `remote` |
| `syncSource` | string | `markdown` | Format driving sync |
| `createNewNotes` | bool | `false` | Create notes from unmatched files |
