# Apple Notes Export Tool <!-- omit from toc -->

**Version 1.3.0**

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

## Quick Start

```bash
# Install
brew install git python
git clone https://github.com/storizzi/notes-exporter.git
cd notes-exporter
pip install -r requirements.txt

# Export all notes to Markdown
chmod +x exportnotes.zsh
./exportnotes.zsh --convert-markdown

# Search your notes
python query_notes.py "meeting notes"
python query_notes.py --modified-within 7d -l "."
```

Output goes to `~/Downloads/AppleNotesExport/` by default.

## What It Does

**Export** from Apple Notes to multiple formats:
- Raw HTML, processed HTML (with extracted images), plain text
- Markdown (for Obsidian, etc.), PDF, Word (DOCX)
- Incremental — only re-exports changed notes (~3x faster than full export)

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

## What's New in 1.3.0

### Bidirectional Sync
Edit exported markdown locally, then sync back to Apple Notes with `--sync` or `--sync-only`. Conflict detection creates `.conflict.md` sidecars. Create new notes with `--create-new`.

### AI Search with Qdrant
Semantic search using Ollama embeddings and Qdrant vector database. `--ai-search "cooking ideas"` finds recipe notes even without matching keywords. Incremental indexing with `--update-qdrant`.

### Search & Query Tool
Full-text search with regex (`-E`), date filtering (`--modified-within 3d`), image filtering (`--has-images`), and folder filtering (`-F Notes`).

### Reconciliation
`reconcile.py` compares counts across Apple Notes, tracking JSON, disk files, and Qdrant. `--details` pinpoints specific exceptions.

### Export Enhancements
`--no-overwrite`, `--modified-after DATE`, `--images-beside-docs`, `--html-wrap`, `--dedup-images`.

### Venv Support
`--venv-dir .venv` replaces conda. `--conda-env` still works (maps to venv with deprecation warning).

### JSON Lines Output
All commands support `--json-log` for machine-readable output.

### Upgrading from 1.2.x

Sync requires `fullNoteId` in tracking JSON. Run a full re-export after upgrading:

```bash
./exportnotes.zsh --update-all --convert-markdown
```

See [RELEASES.md](./RELEASES.md) for full details.

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
pip install -r requirements.txt
chmod +x exportnotes.zsh
```

### First Export

```bash
./exportnotes.zsh --convert-markdown
```

macOS will prompt for Notes app permissions on first run.

## Tests

```bash
# Run all tests (258 tests)
pytest -v

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

All tests use isolated temp directories — never touches your live data.
