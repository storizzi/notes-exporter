# AI assistants (MCP) <!-- omit from toc -->

notes-exporter includes a [Model Context Protocol](https://modelcontextprotocol.io) server,
so an AI assistant — Claude Code, Claude Desktop, or any MCP client that runs a local
(stdio) server — can search and read your exported notes, see and start exports, and, only
if you allow it, change and create notes.

- [How it works](#how-it-works)
- [Set it up](#set-it-up)
  - [From the command line](#from-the-command-line)
  - [From the web page](#from-the-web-page)
  - [A client on another computer](#a-client-on-another-computer)
  - [Any other MCP client](#any-other-mcp-client)
- [The tools](#the-tools)
- [Letting it change notes](#letting-it-change-notes)
- [Check, rotate, remove](#check-rotate-remove)
- [Reference](#reference)
- [Troubleshooting](#troubleshooting)

## How it works

```
Claude Code / Claude Desktop ──stdio──▶ notes-exporter mcp serve ──HTTP + API key──▶ the service (127.0.0.1:8790)
                                                                                      └─ export folder, Apple Notes
```

The MCP server is a client of the [service](SERVICE-API.md), with an **API key of its own**
(named `MCP`). It never reads Apple Notes or the export folder itself, so everything the
service enforces applies to it unchanged: the key's scopes, *Allow clients to write notes*,
conflict checks, one export at a time, locked notes never written. It reads the same export
every other client does — a copy made by the last export run — and can start a run to catch up.

The key is kept in an env file, `~/Library/Application Support/notes-exporter/mcp.env`
(mode 0600), which the server reads when the client starts it. It is never printed and never
written into a client's configuration: Claude's config only holds a command line.

The server uses only Python's standard library; it starts with the repository's `.venv`
Python, or any `python3`.

## Set it up

You need the service running with an admin user (the [Quick start](SERVICE-API.md#quick-start)
steps 1–2, or `notes-exporter service install`).

### From the command line

```bash
cd notes-exporter
./setup_mcp.zsh
```

That checks the dependencies, that there is an admin and that the service answers, then runs
`notes-exporter mcp setup`, which

1. makes an API key named **MCP** with scopes **read, run** for the only admin (`--owner` to
   choose) and writes it into `mcp.env`;
2. registers the server with **Claude Code** (`claude mcp add --scope user notes-exporter …`,
   so every project has it) and with **Claude Desktop** (`mcpServers` in
   `~/Library/Application Support/Claude/claude_desktop_config.json`, after saving a
   `.bak-<time>` copy), whichever are installed;
3. checks the key against the service and lists the tools it gets.

Start a new Claude Code session (`/mcp` shows *notes-exporter*), or quit and reopen Claude
Desktop. Then ask, for example, *"find my notes about scones"* or *"what changed in my notes
this week?"*.

Options (`./setup_mcp.zsh --help`):

| Option | |
|---|---|
| `--write` | also the `write` scope: change and create notes ([below](#letting-it-change-notes)) |
| `--no-run` | no `run` scope: it can't start or cancel exports |
| `--read-only` | register the server with `--read-only`: only the reading tools, whatever the key may do |
| `--client claude-code\|claude-desktop\|print` | where to register it (repeat it); `print` shows the JSON for another client |
| `--claude-scope user\|project\|local` | Claude Code's config scope (default `user`) |
| `--name NAME`, `--server-name NAME` | the key's name (`MCP`), the server's name in the client (`notes-exporter`) |
| `--owner USER`, `--expires-days N` | the key's owner and lifetime |
| `--url URL --key-stdin` | a service on another Mac ([below](#a-client-on-another-computer)) |
| `--keep-key` | keep the key already in `mcp.env` (just register the clients) |
| `--env-file PATH` | keep the key somewhere else |
| `--dry-run` | print what it would do |

### From the web page

Sign in as an admin at <http://127.0.0.1:8790/> and open the **MCP** tab:

1. Tick what the assistant may do (*read* always; *run*; *write*), leave **On this Mac**
   selected and press **Make key**. The key goes straight into `mcp.env`; the page never
   shows it.
2. Under **Connect a client on this Mac**, copy the `claude mcp add …` line into Terminal for
   Claude Code, and/or the JSON into Claude Desktop's config file, then reopen Claude Desktop.

The tab also shows which key the file holds, its scopes and when it was last used. Pressing
**Make key** again makes a new key and revokes the old one; clients keep working, because
they read the file each time they start the server.

### A client on another computer

The service only answers this Mac unless it is started with `--allow-remote`, and then it
should sit behind a reverse proxy with HTTPS (see [Running it](SERVICE-API.md#running-it)) —
the MCP server talks plain HTTP to whatever URL it is given.

With that in place: on the web page's **MCP** tab choose **On another computer — show the
key once** (it is named `MCP (other computer)`, so remaking this Mac's key doesn't revoke it),
copy the key, and on the other computer, in a clone of notes-exporter:

```bash
./notes-exporter mcp setup --url https://notes.example.com --key-stdin   # paste the key, press Return
```

(or `notes-exporter apikey create --name "MCP (laptop)" --scopes read,run` on the service's
Mac). The other computer needs only `python3` and the repository; not the service's
dependencies.

### Any other MCP client

```bash
./notes-exporter mcp setup --client print
```

prints the entry to add to a client's `mcpServers` (the web page's MCP tab shows it too):

```json
{
  "mcpServers": {
    "notes-exporter": {
      "command": "/path/to/notes-exporter/notes-exporter",
      "args": ["mcp", "serve"]
    }
  }
}
```

## The tools

Which tools the client sees follows the key's scopes (and `--read-only`).

| Tool | Scope | |
|---|---|---|
| `notes_status` | read | last and next export, notes in the export, formats, whether writing is allowed, the key's scopes |
| `list_folders` | read | every account and folder, with note counts |
| `list_notes` | read | notes newest first; by account, folder (and subfolders), `modified_after`, `changed_since_sequence`, `title_contains`; paged |
| `search_notes` | read | every word (or `"a phrase"`) in title, folder, tags or text; best first, with a snippet; `titles_only` for speed |
| `read_note` | read | a note's text — Markdown if exported, else plain text, else its HTML as text — and its details and attachments; `max_chars` |
| `get_attachment` | read | a picture as an image (up to 4 MB), a text file as text |
| `list_runs`, `get_run` | read | export runs; a run's status and the end of its log |
| `start_export`, `cancel_export` | run | an incremental or full run, optionally some folders / accounts / extra formats |
| `update_note` | write | replace a note's content with Markdown |
| `create_note` | write | a new note in a folder the export already holds |

Full-text search reads each note's exported text through the service (and remembers it while
the server runs, by its SHA-256), so the first search over a large export takes a few seconds.
Locked notes are listed but their text isn't exported, so it can't be searched or read.

## Letting it change notes

Writing is off twice over until you turn it on:

1. the key needs the **write** scope (`./setup_mcp.zsh --write`, or tick *write* on the MCP
   tab), and
2. an admin ticks **Allow clients to write notes** in the web page's Settings.

Then `update_note` replaces a note's whole content with Markdown and `create_note` makes a
note, through the service's [Writing notes](SERVICE-API.md#writing-notes) — with all its
checks: the assistant must send back the `modified` it read (a note changed since, in the
export or in Notes, is refused), a rewrite that would lose non-picture attachments or
checklist ticks is refused until the user agrees, and nothing is written during an export.
The server tells the assistant to change notes only when you ask, and to report conflicts
and losses to you rather than forcing them. Every write is logged (who, which note, never the
text) in `writes.ndjson`, under the key `key:<prefix>`.

## Check, rotate, remove

```bash
./notes-exporter mcp check                 # the key in mcp.env works? which scopes and tools?
./setup_mcp.zsh                            # again: a new key, the old one revoked (rotate)
./notes-exporter mcp uninstall             # unregister from Claude Code and Claude Desktop, revoke the MCP keys
./notes-exporter mcp uninstall --keep-key  # unregister only
```

The key also appears on the **API keys** tab (name `MCP`), where it can be revoked like any
other; the MCP tab then says the file's key is revoked.

## Reference

`notes-exporter mcp serve [--url URL] [--env-file PATH] [--read-only]` — what a client runs.
JSON-RPC 2.0 over stdio, one message per line (MCP protocol versions 2024-11-05 to
2025-11-25); everything else it prints goes to stderr.

| Variable | Default | |
|---|---|---|
| `NOTES_EXPORTER_URL` | `http://127.0.0.1:<NOTES_SERVICE_PORT>` | the service (`--url` wins) |
| `NOTES_EXPORTER_API_KEY` | — | the key; else read from the env file |
| `NOTES_EXPORTER_MCP_ENV_FILE` | `<NOTES_SERVICE_HOME>/mcp.env` | the env file (`--env-file` wins) |
| `NOTES_EXPORTER_MCP_READ_ONLY` | `false` | as `--read-only` |
| `NOTES_SERVICE_CLAUDE_BIN` | `claude` on `PATH` | what `mcp setup` runs to register with Claude Code (tests use a fake) |
| `NOTES_SERVICE_CLAUDE_DESKTOP_CONFIG` | `~/Library/Application Support/Claude/claude_desktop_config.json` | (tests use a file under a temporary folder) |

The web page's tab uses `GET /api/admin/mcp` and `POST /api/admin/mcp` (scope admin): see
[SERVICE-API.md](SERVICE-API.md#mcp).

## Troubleshooting

* **The tools say the service isn't answering** — start it: `notes-exporter service install`
  (or `notes-exporter serve`); `notes-exporter service status`.
* **"The service refused the API key"** — it was revoked or has expired: run
  `./setup_mcp.zsh` again, or **Make key** on the MCP tab.
* **A tool is missing** — the key lacks the scope (`notes_status` shows `this_key_scopes`), or
  the server runs `--read-only`.
* **"There is no export yet"** — ask it to `start_export`, or press **Run now** on the web page.
* **Notes look out of date** — the assistant reads the export, not Notes: start an export, or
  set a schedule in Settings.
* **Claude Code doesn't list it** — `claude mcp list`; it is added with `--scope user`, so it
  is in every project, from the next session.
