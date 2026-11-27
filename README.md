# Apple Notes Export Tool <!-- omit from toc -->

**Version 1.7.1** (released 27 November 2026) — see [Releases](#releases)

<figure style="float: right; margin-left: 10px;">
    <img src="notes-exporter.jpg" alt="Notes Exporter" width="200">
</figure>

Export Apple Notes to HTML, Markdown, PDF, Word and EPUB with images intact, or run it as a service that other programs use over HTTP. Search across notes by text, date, or AI-powered semantic similarity. Edit markdown locally and sync changes back to Apple Notes.

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
| **[Service API](./SERVICE-API.md)** | Other programs, over HTTP | `notes-exporter serve`: runs, schedule, manifest and files, users and API keys |
| **[AI assistants (MCP)](./MCP.md)** | Claude Code, Claude Desktop, MCP clients | `./setup_mcp.zsh` or the web page's MCP tab: search, read, export and (optionally) edit notes from an assistant |

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
- Markdown (for Obsidian, etc.), PDF, Word (DOCX), EPUB (one book per note, or one per folder)
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

**Serve** your notes to other programs and AI assistants:
- A service that exports on a schedule and serves notes over an authenticated HTTP API, with a web page ([SERVICE-API.md](./SERVICE-API.md))
- An MCP server so Claude Code, Claude Desktop and other assistants can search, read and (if you allow it) change notes ([MCP.md](./MCP.md))

## Releases

The latest first; every change, and how to upgrade, is in [RELEASES.md](./RELEASES.md).

**Recent**

| Version | Date | |
|---|---|---|
| [1.7.1](./RELEASES.md#27-november-2026---release-171---what-became-of-a-held-change) | 27 Nov 2026 | A held change can still be looked up once it has been approved or rejected |
| [1.7.0](./RELEASES.md#27-november-2026---release-170---ai-assistants--safer-writing) | 27 Nov 2026 | **AI assistants (MCP)**: Claude Code, Claude Desktop or any MCP client can search, read and export notes ([MCP.md](./MCP.md)). **Safer writing**: a backup in Notes before every change, deleting, limits on mass changes and an approval list |
| [1.6.0](./RELEASES.md#14-november-2026---release-160---updates-from-a-client) | 14 Nov 2026 | Update and restart the service from a client or the web page |
| [1.5.1](./RELEASES.md#14-november-2026---release-151---settings-for-clients--writing-notes) | 14 Nov 2026 | Settings for clients, and writing notes through the service |

**Milestones**

| Version | Date | |
|---|---|---|
| [1.5.0](./RELEASES.md#11-november-2026---release-150---service-api--epub) | 11 Nov 2026 | **The service**: `notes-exporter serve` exports on a schedule and serves the notes over an authenticated HTTP API, with a web page ([SERVICE-API.md](./SERVICE-API.md)). EPUB output |
| [1.4.0](./RELEASES.md#11-november-2026---release-140---nested-folders-manifest--reliable-incremental-export) | 11 Nov 2026 | Nested folders, `manifest.json`, JSON Lines events and exit codes for other programs ([INTEGRATION.md](./INTEGRATION.md)), reliable deletions and moves |
| [1.3.0](./RELEASES.md#18-march-2026---release-130---bidirectional-sync-search--venv-support) | 18 Mar 2026 | Sync edited Markdown back to Notes, text and AI (Qdrant) search, reconciliation |
| [1.0.0](./RELEASES.md#10-june-2025---release-100---incremental-export--deletion-tracking---breaking-changes) | 10 Jun 2025 | Incremental export and deletion tracking |

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

## Running as a service

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./notes-exporter user add simon --admin --generate-password --keychain   # the password goes to your login Keychain
./notes-exporter serve                                                   # http://127.0.0.1:8790/
./notes-exporter permission request          # (another terminal, at the Mac) click Allow when macOS asks
./notes-exporter apikey create --name FunHoard --scopes read,run,settings \
    --env-file ~/dev/storizzi/repos/apps/desktop/media-server/backend/.env --env-var NOTES_EXPORTER_API_KEY
./notes-exporter service install --replace-legacy                        # stop the serve above first
./notes-exporter permission request          # once more: the LaunchAgent asks as its own process
```

1. **The first admin.** `--generate-password --keychain` makes a strong password and keeps it in your login Keychain as `notes-exporter` (open the Passwords app to see it); it is never printed. Without them you type one.
2. **Serve.** Open <http://127.0.0.1:8790/>, sign in, and set the export folder, formats and schedule under **Settings**.
3. **The Notes permission.** macOS must let the service control Notes. `permission request` (or **Ask macOS for access to Notes** on the web page) makes macOS show its dialog on this Mac; click Allow. The permission belongs to the process that asks, so it is asked by the running service, and asked again once the LaunchAgent runs it. Until it is allowed, scheduled runs fail with exit code 3 rather than wait at a prompt.
4. **An API key for another program**, written straight into its env file (mode 0600, other lines untouched, only the key's prefix shown); add `--replace` to rotate it later. Programs send it as `Authorization: Bearer ne_…`; keys are never accepted in a URL.
5. **Keep it running** after you log in: `service install` (a LaunchAgent, `com.storizzi.notes-exporter`). If you scheduled exports with `setup_launchd.py` before, install refuses until that job is gone; `--replace-legacy` unloads it and moves its plist aside (it says what it will do first).

The service listens on this Mac only unless you pass `--allow-remote`; use a reverse proxy with HTTPS for that. Everything else, the endpoints and the settings are in [SERVICE-API.md](./SERVICE-API.md).

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

The service has its own tests (`tests/service`, `tests/e2e`), and `ikt test notes-exporter` (or `node scripts/test-all.js`) runs every tier: `unit`, `service`, `e2e` and, when `epubcheck` is installed, `epubcheck`. The `live` tier exports your real Notes through the running service and runs only with `NOTES_EXPORTER_LIVE=1` ([SERVICE-API.md](./SERVICE-API.md#the-live-check-opt-in)).

All tests use isolated temp directories and never touch your live data or Apple Notes: the end-to-end tests of `exportnotes.zsh` use a stand-in for `osascript` (`tests/fake_osascript.py`).
