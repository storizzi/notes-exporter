# 📝 notexport

<img src="notes-exporter.jpg" alt="notes exporter" width="200" align="right">

export your apple notes to html, markdown, pdf, and word (docx) with images intact. 📄

**requirements:** macos only (uses applescript) 🍎

## ✨ features

- 📦 export notes to multiple formats (html, markdown, pdf, word)
- 🖼️ extract and preserve images from notes
- 🔄 incremental updates (only processes changed notes)
- 📁 filter specific folders to export
- 🧹 cleanup source files after pdf conversion
- 📜 continuous pdf export for handwritten notes (no page breaks)
- ⏰ schedule automatic exports

## 🚀 quick start

### 1. install dependencies

```bash
# install homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# install git and python
brew install git python
```

### 2. clone the repository

```bash
git clone https://github.com/gablilli/notexport.git
cd notexport
pip install -r requirements.txt
```

### 3. run the export

```bash
chmod +x exportnotes.zsh
./exportnotes.zsh
```

notes will be exported to `~/Downloads/AppleNotesExport` by default.

## 📖 usage examples

```bash
# basic export (incremental)
./exportnotes.zsh

# export all formats (html, markdown, pdf, word)
./exportnotes.zsh --all

# export only specific folders (comma-separated)
./exportnotes.zsh --folders "Work,Personal,Projects"

# export folders with spaces in names (spaces after commas are optional)
./exportnotes.zsh --folders "My Work Notes,Personal Diary,Class Notes"

# export to pdf with cleanup (removes source files after)
./exportnotes.zsh --convert-pdf true --cleanup

# continuous pdf for handwritten notes (no page breaks)
./exportnotes.zsh --convert-pdf true --continuous-pdf

# export to custom directory
./exportnotes.zsh --root-dir ~/Documents/MyNotes

# force full re-export
./exportnotes.zsh --update-all
```

## ⚙️ options

| option | short | description |
|--------|-------|-------------|
| `--root-dir` | `-r` | output directory (default: `~/Downloads/AppleNotesExport`) |
| `--folders` | `-F` | comma-separated folder names to export (matches all folders with given names) |
| `--convert-pdf` | `-p` | convert to pdf |
| `--convert-markdown` | `-m` | convert to markdown |
| `--convert-word` | `-w` | convert to word (docx) |
| `--continuous-pdf` | `-P` | export pdf as continuous page (for handwritten notes) |
| `--cleanup` | `-C` | cleanup source directories after pdf conversion |
| `--all` | `-a` | enable all format conversions |
| `--update-all` | `-U` | force full update (disable incremental) |
| `--suppress-header-pdf` | `-s` | suppress pdf headers/footers (default: true) |
| `--help` | `-h` | show help message |

**Note on `--folders` filter:**
- Use exact folder names as they appear in Notes.app
- Separate multiple folders with commas (spaces after commas are automatically trimmed)
- The filter matches all folders with the given name, including nested folders with the same name
- Example: filtering for "Esercizi" will match all folders named "Esercizi" regardless of their parent
- The filter matches both original folder names and sanitized names (with special characters replaced)

## 📁 output structure

```
AppleNotesExport/
├── data/          # json tracking files
├── raw/           # raw html from apple notes
├── html/          # processed html with extracted images
├── text/          # plain text content
├── markdown/      # markdown files (if enabled)
├── pdf/           # pdf files (if enabled)
└── word/          # word files (if enabled)
```

## 🔧 additional dependencies

| format | dependency |
|--------|------------|
| pdf | [google chrome](https://www.google.com/chrome/) |
| word | `brew install pandoc` |

## 📅 scheduled exports

you can schedule automatic exports using macos launchd:

```bash
# setup daily export at 9:00 am
python setup_launchd.py

# setup export every 60 minutes
python setup_launchd.py --interval 60

# manage scheduled job
python setup_launchd.py --status  # check status
python setup_launchd.py --load    # start
python setup_launchd.py --unload  # stop
python setup_launchd.py --remove  # remove
```

## 🧪 tests

```bash
./tests/test.zsh
```

## 📄 license

[mit license](./LICENSE.txt)
