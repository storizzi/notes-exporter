# Advanced Guide: Sync, AI Search & More

This guide covers bidirectional sync (edit locally, push back to Apple Notes), AI-powered semantic search with Qdrant, reconciliation, and machine-readable output.

For basic export and search, see the [Basic Guide](./GUIDE-BASIC.md).

## Bidirectional Sync

Edit exported markdown files locally and sync changes back to Apple Notes.

### Getting Started

Sync requires `fullNoteId` in your tracking data. If upgrading from an earlier version, run a full re-export first:

```bash
# Step 1: Full re-export to populate fullNoteId
./exportnotes.zsh --update-all --convert-markdown

# Step 2: Preview what would sync (dry run)
./exportnotes.zsh --sync-only --sync-dry-run

# Step 3: Edit a markdown file, then sync it back
./exportnotes.zsh --sync-only
```

On the first sync run, no notes will appear as "locally changed" — this is expected. The sync engine records a baseline hash at this point. After that, any local edits will be detected.

### How It Works

1. **Export** creates markdown files and tracks metadata (including full note IDs)
2. **Edit** the markdown files locally with any editor
3. **Sync back** converts markdown to HTML, embeds images as base64, and updates Apple Notes

Change detection:
- **Local changes**: SHA-256 hash comparison of the markdown file
- **Remote changes**: Modification date comparison from Apple Notes metadata

Four outcomes:
- **Neither changed** — skip
- **Only local changed** — sync local to Apple Notes
- **Only remote changed** — re-export handles this
- **Both changed** — conflict (creates `.conflict.md` sidecar)

### Sync Commands

```bash
# Sync after export
./exportnotes.zsh --sync

# Sync without exporting first
./exportnotes.zsh --sync-only

# Dry run — see what would sync
./exportnotes.zsh --sync-only --sync-dry-run

# Create new Apple Notes from unmatched local markdown files
./exportnotes.zsh --sync-only --create-new

# Sync specific folders only
./exportnotes.zsh --sync-only --filter-folders Notes

# Override conflict strategy
./exportnotes.zsh --sync-only --conflict local    # local wins
./exportnotes.zsh --sync-only --conflict remote   # remote wins
./exportnotes.zsh --sync-only --conflict abort    # default, creates .conflict.md
```

### Settings File

Create `.notes-exporter-settings.json` for persistent sync configuration:

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

Settings precedence: CLI flags > environment variables > settings file > defaults.

After sync, formats listed in `autoRegenerate` are automatically re-exported.

## AI Search with Qdrant

Semantic search finds notes by meaning, not just keywords. Searching for "cooking ideas" will find notes about recipes, meal planning, and food preparation even if they don't contain those exact words.

### Prerequisites

You need:
1. **Qdrant** — vector database (local Docker or Qdrant Cloud)
2. **Ollama** — for generating embeddings locally (or sentence-transformers)
3. **Exported notes** — at least one export run

```bash
# Check if everything is set up
python qdrant_integration.py check
```

### Setup: Local with Docker + Ollama (Recommended)

Everything stays on your machine — no data sent externally.

```bash
# Start Qdrant
docker run -d -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant

# Install and start Ollama
brew install ollama
ollama serve

# Pull the embedding model
ollama pull mxbai-embed-large

# Verify
python qdrant_integration.py check
```

### Setup: Qdrant Cloud

For cloud-hosted Qdrant (no Docker needed):

```bash
export NOTES_EXPORT_QDRANT_URL="https://your-cluster.cloud.qdrant.io:6333"
export NOTES_EXPORT_QDRANT_API_KEY="your-api-key"
```

You still need Ollama locally for embeddings.

### Setup: sentence-transformers (No Ollama)

```bash
pip install sentence-transformers
export NOTES_EXPORT_EMBEDDING_PROVIDER="sentence-transformers"
```

### Choosing an Embedding Provider

| | **Ollama + mxbai-embed-large** | **sentence-transformers + all-MiniLM-L6-v2** |
|---|---|---|
| **Dimensions** | 1024 | 384 |
| **Search quality** | Excellent | Good |
| **Setup** | Needs Ollama server | Just `pip install` |
| **Speed** | Fast (native binary) | Slower (Python) |
| **Best for** | Best results, already using Ollama | Simplest setup |

Higher dimensions = better search. `mxbai-embed-large` captures more semantic nuance. If you care about search quality, use Ollama.

**Ollama models** (install with `ollama pull <model>`):
| Model | Dimensions | Notes |
|-------|-----------|-------|
| `mxbai-embed-large` | 1024 | Best quality, recommended |
| `nomic-embed-text` | 768 | Good balance |
| `all-minilm` | 384 | Fastest, smallest |

**sentence-transformers models** (auto-downloaded):
| Model | Dimensions | Notes |
|-------|-----------|-------|
| `all-MiniLM-L6-v2` | 384 | Default, fast |
| `all-mpnet-base-v2` | 768 | Higher quality |

If you change models after indexing, reset and re-index:
```bash
python qdrant_integration.py reset
python qdrant_integration.py sync --force
```

### Indexing Notes

```bash
# Index all exported notes (incremental — only changed notes)
python qdrant_integration.py sync

# Or as part of the export pipeline
./exportnotes.zsh --convert-markdown --update-qdrant

# Preview what would be indexed
python qdrant_integration.py dry-run

# Force re-embed everything
python qdrant_integration.py sync --force

# Custom chunk size (default: 800 chars, 200 overlap)
python qdrant_integration.py sync --chunk-size 600 --chunk-overlap 150
```

### How Indexing Works

Long notes are split into overlapping chunks (default: 800 chars, 200 overlap) so the full content is searchable. Each chunk gets its own vector. The sync is **incremental** — tracked via `lastIndexedToQdrant` in the JSON:

- **New/changed notes**: Re-embedded and upserted
- **Deleted notes**: Automatically removed from Qdrant
- **Unchanged notes**: Skipped (no embedding cost)

### AI Search

```bash
# Semantic search
python query_notes.py --ai-search "ideas about cooking"

# Top 5 results
python query_notes.py --ai-search -n 5 "project deadlines"

# Only results above 70% similarity
python query_notes.py --ai-search --threshold 0.7 "travel plans"

# List file paths only
python query_notes.py --ai-search -l "meeting notes"

# Direct search via qdrant_integration
python qdrant_integration.py search "your query"
```

### Managing the Index

```bash
python qdrant_integration.py check      # Verify prerequisites
python qdrant_integration.py status     # Collection info and point count
python qdrant_integration.py sync       # Sync changes
python qdrant_integration.py dry-run    # Preview sync
python qdrant_integration.py reset      # Delete and start fresh
```

## Reconciliation

Compare note counts across Apple Notes, tracking JSON, disk files, and Qdrant.

```bash
# Quick check (instant — JSON + disk only)
python reconcile.py --skip-apple --skip-qdrant

# Include Apple Notes count
python reconcile.py --skip-qdrant

# Full check including Qdrant
python reconcile.py

# Per-notebook breakdown
python reconcile.py --notebooks

# List specific exceptions (orphans, missing files, etc.)
python reconcile.py --details

# Fast details without live queries
python reconcile.py --skip-apple --skip-qdrant --details

# Show fix suggestions
python reconcile.py --details --fix
```

What it checks:
- Apple Notes vs tracking JSON (missing exports, undetected deletions)
- Tracking JSON vs disk files (orphan files, missing exports)
- Format coverage (has HTML but missing markdown?)
- Deleted notes still on disk
- Sync readiness (fullNoteId present?)
- Qdrant coverage (all notes indexed?)

## JSON Lines Output

All commands support `--json-log` for machine-readable output.

```bash
# JSON to stdout (human output goes to stderr)
python query_notes.py --json-log - "search term"

# JSON to file (human output still prints normally)
python query_notes.py --json-log results.jsonl "search term"
python reconcile.py --json-log reconcile.jsonl --skip-apple
python qdrant_integration.py --json-log status.jsonl status
```

Each JSON line has a `type` field. Use `jq` to process:

```bash
# Count matches
python query_notes.py --json-log - "term" | jq 'select(.type=="summary") | .total_matches'

# Get filenames from AI search
python query_notes.py --json-log - --ai-search "cooking" | jq -r 'select(.type=="result") | .filename'

# Check Qdrant point count
python qdrant_integration.py --json-log - status | jq '.count'
```

## Export Enhancements

### No-Overwrite Mode

Skip files that already exist (useful when you've edited exported files):

```bash
./exportnotes.zsh --no-overwrite --convert-markdown
```

### Date Range Filter

Only export notes modified after a given date:

```bash
./exportnotes.zsh --modified-after 2026-01-15
```

### Images Beside Documents

Place images next to HTML files instead of in `attachments/`:

```bash
./exportnotes.zsh --images-beside-docs
```

### HTML Wrapping

Wrap exported HTML with proper `<!DOCTYPE>`, `<head>`, `<title>`, `<body>`:

```bash
./exportnotes.zsh --html-wrap
```

### Image Deduplication

Identical images saved once and referenced from multiple notes:

```bash
./exportnotes.zsh --dedup-images
```

## Virtual Environment

Use a Python venv instead of system Python:

```bash
# Create and activate venv
./exportnotes.zsh --venv-dir .venv --convert-markdown

# Clean up after
./exportnotes.zsh --venv-dir .venv --remove-venv
```

The `--conda-env` flag still works but maps to `--venv-dir` with a deprecation warning.

## Next Steps

- **[Basic Guide](./GUIDE-BASIC.md)** — Simple backup and search
- **[Technical Reference](./REFERENCE.md)** — All CLI options, environment variables, JSON schemas
