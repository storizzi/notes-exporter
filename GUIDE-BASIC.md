# Basic Guide: Backup & Search

This guide covers the essentials: exporting your Apple Notes as a backup and searching through them.

## Quick Start

### 1. Install

```bash
# Install prerequisites
brew install git python

# Clone the tool
mkdir -p ~/bin/notes-exporter && cd ~/bin/notes-exporter
git clone https://github.com/storizzi/notes-exporter.git .

```

There is nothing else to install: the first run of `exportnotes.zsh` creates a
Python virtual environment in `.venv` and installs the dependencies into it.
The `python3 …` commands below need those dependencies too; run
`source .venv/bin/activate` first (or use `.venv/bin/python` instead of
`python3`).

### 2. Export Your Notes

```bash
cd ~/bin/notes-exporter
chmod +x exportnotes.zsh
./exportnotes.zsh
```

That's it. Your notes are now in `~/Downloads/AppleNotesExport/` with this structure:

```
AppleNotesExport/
  data/       # JSON tracking files (metadata about each note)
  raw/        # Raw HTML from Apple Notes (images embedded as base64)
  html/       # Processed HTML (images extracted to files)
  text/       # Plain text content
```

The first time you run the script, macOS will ask for permission to access Apple Notes. Grant it.

Each run also writes `manifest.json`, a list of every exported note and its
files that other programs can read ([INTEGRATION.md](./INTEGRATION.md)).
Notes you have locked with a password can't be read by the exporter; they are
skipped and counted in the summary.

### 3. Export to More Formats

```bash
# Also create Markdown files (great for Obsidian, etc.)
./exportnotes.zsh --convert-markdown

# Export to all formats at once (HTML, Markdown, PDF, Word)
./exportnotes.zsh --all

# Just Markdown and PDF
./exportnotes.zsh --convert-markdown --convert-pdf
```

This adds extra directories:

```
AppleNotesExport/
  md/         # Markdown files
  pdf/        # PDF files
  docx/       # Word documents
```

### 4. Run It Again (Incremental)

```bash
./exportnotes.zsh --convert-markdown
```

The second run is much faster. It only processes notes that have changed since the last export.

## Searching Your Notes

Once exported, you can search across all your notes:

### Basic Text Search

```bash
# Find notes containing a word
python3 query_notes.py "meeting"

# Case-insensitive search
python3 query_notes.py -i "project"

# List just the matching filenames
python3 query_notes.py -l "budget"

# Show context around matches
python3 query_notes.py -c 3 "deadline"
```

### Regex Search

```bash
# Find patterns
python3 query_notes.py -E "TODO|FIXME"

# Find dates
python3 query_notes.py -E "[0-9]{4}-[0-9]{2}-[0-9]{2}"
```

### Filter by Date

```bash
# Notes modified in the last 3 days
python3 query_notes.py --modified-within 3d "."

# Notes modified in the last week
python3 query_notes.py --modified-within 1w -l "."

# Notes created in the last 2 months
python3 query_notes.py --created-within 2m "."

# Notes modified after a specific date
python3 query_notes.py --modified-after 2026-01-15 "."
```

Timespan units: `h` (hours), `d` (days), `w` (weeks), `m` (months), `y` (years).

### Filter by Images

```bash
# Only notes that contain images
python3 query_notes.py --has-images "photo"

# Only notes without images
python3 query_notes.py --no-images "text"
```

### Filter by Folder

```bash
# Search only in the Notes folder
python3 query_notes.py -F Notes "important"

# Search only markdown files
python3 query_notes.py --format md "recipe"
```

### Search via the Main Script

You can also search through the main script:

```bash
./exportnotes.zsh --query "meeting notes"
./exportnotes.zsh --query -E "TODO|FIXME"
./exportnotes.zsh --query --modified-within 7d -l "."
```

## Common Tasks

### Export Specific Folders Only

```bash
# Only export from iCloud Notes folder
./exportnotes.zsh --filter-folders Notes

# Only export from a specific account
./exportnotes.zsh --filter-accounts iCloud

# A folder inside another folder: give its path
./exportnotes.zsh --filter-folders "Work/Projects"

# Everything except some folders
./exportnotes.zsh --exclude-folders "Recently Deleted,Archive"
```

### Keep Nested Folders

By default a folder inside another is exported as `iCloud-Projects/`. To keep
the hierarchy (`iCloud/Work/Projects/`):

```bash
./exportnotes.zsh --folder-hierarchy --convert-markdown
```

To move an existing export into that layout first (nothing in Apple Notes changes):

```bash
python3 reorganize_by_folder.py --root ~/Downloads/AppleNotesExport --dry-run
python3 reorganize_by_folder.py --root ~/Downloads/AppleNotesExport
```

### Deleted Notes

When you delete a note in Apple Notes, the next export records it as deleted
but keeps its files. To remove them as well:

```bash
./exportnotes.zsh --prune-deleted --convert-markdown
```

A Markdown file you have edited since it was exported is kept. Apple Notes'
own *Recently Deleted* folder is exported like any other folder unless you
exclude it (`--exclude-folders "Recently Deleted"`).

### Convert Images

Pictures from an iPhone are often HEIC, which many apps can't show. Convert
the extracted images:

```bash
./exportnotes.zsh --image-format jpeg --image-format-from heic,tiff --image-quality 85
```

`jpeg`, `png`, `heic` and `tiff` use macOS's own `sips`. `webp` needs Pillow
(`.venv/bin/pip install pillow`) or `brew install webp`.

### Tags

Apple Notes keeps `#tags` outside the note text, so they don't appear in the
export. `--tags` reads them (and whether a note is pinned or has a checklist)
from a copy of the Notes database and puts them in `manifest.json`;
`--tags-in-content` also writes a "Tags:" line into each note:

```bash
./exportnotes.zsh --tags --tags-in-content --convert-markdown
```

This needs **Full Disk Access** for your terminal (System Settings > Privacy &
Security > Full Disk Access).

### Export to a Different Location

```bash
./exportnotes.zsh --root-dir ~/Documents/MyNotes --convert-markdown
```

### Force Full Re-export

If something seems off, you can force a complete re-export:

```bash
./exportnotes.zsh --update-all --convert-markdown
```

### Clean Start

Delete all exported files (but keep tracking data) and re-export:

```bash
./exportnotes.zsh --clean --convert-markdown
```

### Use a Python Virtual Environment

Keep dependencies isolated:

```bash
./exportnotes.zsh --venv-dir .venv --convert-markdown
```

First run creates the venv and installs dependencies. Subsequent runs just activate it (and reinstall when `requirements.txt` changes). Without `--venv-dir` the script uses `.venv` next to itself in the same way, or `--python /path/to/python` names an interpreter that already has the dependencies.

### Set Filesystem Dates

Make exported files show the original Apple Notes dates in Finder:

```bash
./exportnotes.zsh --set-file-dates --convert-markdown
```

## Scheduling Automatic Backups

Run exports automatically on a schedule:

```bash
# Set up daily export at 9 AM
python3 setup_launchd.py --hour 9 --load

# Or every 60 minutes
python3 setup_launchd.py --interval 60 --load

# Check status
python3 setup_launchd.py --status

# Stop scheduling
python3 setup_launchd.py --unload
```

Configure what gets exported by editing `.env`:

```bash
export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"
export NOTES_EXPORT_SET_FILE_DATES="true"
```

## Checking Your Backup

Run reconciliation to see if anything is missing:

```bash
# Quick check (instant, no Apple Notes query)
python3 reconcile.py --skip-apple --skip-qdrant

# Full check including Apple Notes count
python3 reconcile.py --skip-qdrant

# See per-notebook breakdown
python3 reconcile.py --skip-qdrant --notebooks
```

## Next Steps

- **[Advanced Guide](./GUIDE-ADVANCED.md)** — Bidirectional sync, AI search with Qdrant, JSON output
- **[Technical Reference](./REFERENCE.md)** — All CLI options, environment variables, JSON schemas
