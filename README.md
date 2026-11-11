# Apple Notes Export Tool <!-- omit from toc -->

**Version 1.4.0** (unreleased)

<figure style="float: right; margin-left: 10px;">
    <img src="notes-exporter.jpg" alt="Notes Exporter" width="200">
</figure>

Export Apple Notes to HTML, Markdown, PDF, and Word with images intact. Search across notes by text, date, or AI-powered semantic similarity. Edit markdown locally and sync changes back to Apple Notes.

**Thanks to [@sulkaharo](https://github.com/sulkaharo) for performance optimizations and feature improvements!**

Works on macOS only (uses AppleScript). Requires the Notes app.

* Released under [MIT license](./LICENSE.txt)
* [Release History](./RELEASES.md)
* [Possible future features](./TODO.md)

## Guides

| Guide | For | Covers |
|-------|-----|--------|
| **[Basic Guide](./GUIDE-BASIC.md)** | Getting started | Export, search, scheduling, reconciliation |
| **[Advanced Guide](./GUIDE-ADVANCED.md)** | Power users | Bidirectional sync, AI search, Qdrant, JSON output |
| **[Technical Reference](./REFERENCE.md)** | Developers | All CLI options, env vars, JSON schemas, file structure |
| **[Integration Guide](./INTEGRATION.md)** | Other programs | The manifest, JSON Lines events, exit codes, locking |

## Quick Start

```bash
# Install
brew install git python
git clone https://github.com/storizzi/notes-exporter.git
cd notes-exporter

# Export all notes to Markdown (the first run creates .venv and installs the dependencies)
./exportnotes.zsh --convert-markdown

# Search your notes
./exportnotes.zsh --query "meeting notes"
./exportnotes.zsh --query --modified-within 7d -l "."
```

Output goes to `~/Downloads/AppleNotesExport/` by default. Use `python3`, not
`python`: macOS has no `python` command.

## What It Does

**Export** from Apple Notes to multiple formats:
- Raw HTML, processed HTML (with extracted images), plain text
- Markdown (for Obsidian, etc.), PDF, Word (DOCX)
- Incremental — only re-exports changed notes (~3x faster than full export)
- Nested folders kept as nested directories (`--folder-hierarchy`)
- Images optionally converted (`--image-format jpeg`), `#tags` read with `--tags`

**Search** across all exported notes:
- Text and regex search with context, date filtering, image filtering
- AI-powered semantic search via Qdrant vector database

**Sync** changes back to Apple Notes:
- Edit exported markdown files locally, push changes back
- Conflict detection with `.conflict.md` sidecars
- Create new Apple Notes from local markdown files

**Manage** your note collection:
- Reconciliation to find orphans, missing files, and mismatches
- Qdrant vector indexing for semantic search
- Scheduled automatic exports via launchd
- Machine-readable JSON Lines output from all commands
- A `manifest.json` describing every note and its files, for other programs ([INTEGRATION.md](./INTEGRATION.md))

## What's New in 1.4.0

### Nested folders
`--folder-hierarchy` exports `Work/Projects/2026` as nested directories (or use `&folderpath` in `--subdir-format`). `--filter-folders` and the new `--exclude-folders` take folder paths. `reorganize_by_folder.py` moves an existing export into the new layout.

### For other programs
Every run writes `manifest.json`: each note's id, folder path, dates, tags, flags, files with SHA-256 hashes, attachments, renames and moves, deleted and skipped notes. `--json-log` streams progress events, `--non-interactive` never waits at a permission prompt, exit codes say what happened, and a lock stops two exports sharing a folder. See [INTEGRATION.md](./INTEGRATION.md).

### Deletions and moves
Deleted notes are recorded only after a run that read their whole folder, so an interrupted or filtered run no longer marks notes deleted. A note moved to another folder is exported there and its old copy removed. `--prune-deleted` removes the files of deleted notes, keeping locally edited Markdown.

### More
- `--image-format`, `--image-format-from`, `--image-quality`: convert extracted images (HEIC to JPEG, for example).
- `--tags`: real `#tags`, pinned and checklist flags from the Notes database (needs Full Disk Access). `--tags-in-content` writes a Tags line into the note.
- Locked notes are skipped and listed instead of stopping the export; one failing note no longer stops the rest.
- Paths with spaces, attachment names with `)`, and notes whose title contains quotes all work.
- Python is found or set up automatically (`.venv`), or named with `--python`.

### Upgrading from 1.3.x

Nothing to do: the default layout is unchanged and old tracking files are read as they are. The first 1.4 run adds folder information to each note. To switch to nested folders, run `reorganize_by_folder.py --root ~/Downloads/AppleNotesExport --dry-run`, then without `--dry-run`, then export with `--folder-hierarchy`.

See [RELEASES.md](./RELEASES.md) for full details, and for 1.3.0 (bidirectional sync, AI search, the query tool, reconciliation).

## Setup

### Prerequisites

```bash
brew install git python
```

Optional (for specific features):
- **Google Chrome** — for PDF conversion
- **Pandoc** — for Word conversion (`brew install pandoc`)
- **Docker + Ollama** — for AI search ([setup guide](./GUIDE-ADVANCED.md#setup-local-with-docker--ollama-recommended))

### Install

```bash
git clone https://github.com/storizzi/notes-exporter.git
cd notes-exporter
```

`exportnotes.zsh` creates a virtual environment in `.venv` and installs
`requirements.txt` into it on first use (and again when the file changes).
To manage it yourself:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./exportnotes.zsh --venv-dir .venv ...      # or --python .venv/bin/python
```

Homebrew's Python refuses a plain `pip install` outside a virtual environment.

### First Export

```bash
./exportnotes.zsh --convert-markdown
```

macOS will ask whether your terminal may control Notes on the first run; click Allow. A scheduled or scripted run should use `--non-interactive`, which exits with code 3 instead of waiting at that prompt.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run all tests
.venv/bin/python -m pytest -v

# By category
pytest -m unit           # Fast unit tests
pytest -m integration    # Subprocess-based integration tests
pytest -m search         # Search features
pytest -m sync           # Bidirectional sync
pytest -m qdrant         # Qdrant vector DB
pytest -m reconcile      # Reconciliation
pytest -m export         # Export features
pytest -m json_output    # JSON output

# Via test runner
tests/test.zsh           # All tests
tests/test.zsh search    # Just search tests
```

All tests use isolated temp directories and never touch your live data or Apple Notes: the end-to-end tests of `exportnotes.zsh` use a stand-in for `osascript` (`tests/fake_osascript.py`).
