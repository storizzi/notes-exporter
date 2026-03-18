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

# Install Python dependencies
pip install -r requirements.txt
```

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
python query_notes.py "meeting"

# Case-insensitive search
python query_notes.py -i "project"

# List just the matching filenames
python query_notes.py -l "budget"

# Show context around matches
python query_notes.py -c 3 "deadline"
```

### Regex Search

```bash
# Find patterns
python query_notes.py -E "TODO|FIXME"

# Find dates
python query_notes.py -E "[0-9]{4}-[0-9]{2}-[0-9]{2}"
```

### Filter by Date

```bash
# Notes modified in the last 3 days
python query_notes.py --modified-within 3d "."

# Notes modified in the last week
python query_notes.py --modified-within 1w -l "."

# Notes created in the last 2 months
python query_notes.py --created-within 2m "."

# Notes modified after a specific date
python query_notes.py --modified-after 2026-01-15 "."
```

Timespan units: `h` (hours), `d` (days), `w` (weeks), `m` (months), `y` (years).

### Filter by Images

```bash
# Only notes that contain images
python query_notes.py --has-images "photo"

# Only notes without images
python query_notes.py --no-images "text"
```

### Filter by Folder

```bash
# Search only in the Notes folder
python query_notes.py -F Notes "important"

# Search only markdown files
python query_notes.py --format md "recipe"
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
```

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

First run creates the venv and installs dependencies. Subsequent runs just activate it.

### Set Filesystem Dates

Make exported files show the original Apple Notes dates in Finder:

```bash
./exportnotes.zsh --set-file-dates --convert-markdown
```

## Scheduling Automatic Backups

Run exports automatically on a schedule:

```bash
# Set up daily export at 9 AM
python setup_launchd.py --hour 9 --load

# Or every 60 minutes
python setup_launchd.py --interval 60 --load

# Check status
python setup_launchd.py --status

# Stop scheduling
python setup_launchd.py --unload
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
python reconcile.py --skip-apple --skip-qdrant

# Full check including Apple Notes count
python reconcile.py --skip-qdrant

# See per-notebook breakdown
python reconcile.py --skip-qdrant --notebooks
```

## Next Steps

- **[Advanced Guide](./GUIDE-ADVANCED.md)** — Bidirectional sync, AI search with Qdrant, JSON output
- **[Technical Reference](./REFERENCE.md)** — All CLI options, environment variables, JSON schemas
