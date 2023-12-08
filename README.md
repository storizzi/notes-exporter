# Apple Notes Export Tool

<figure style="float: right; margin-left: 10px;">
    <img src="notes-exporter.jpg" alt="Notes Exporter" width="200">
</figure>

This tool facilitates the export of Apple Notes into various formats including HTML (.html) attachment-embedded, Plain Text, Markdown, PDF, and Word (DOCX) with images / attachments and most formatting left intact.

You can use it either as a basic backup, or as a conversion tool - e.g. the Markdown format could be used in a note-taking tool like Obsidian which uses Markdown as standard.

This tool works on a Mac (OSX) not on a Windows or Linux machine because it uses AppleScript to extract the data from notes. You need to have the Notes app installed.

This allows for you to keep a local copy of your apple notes in case of failure, and also to use them in other markdown note-taking apps such as Obsidian, and quickly grab copies if you wish to send PDF versions to anyone, or work on a copy of the document from a Word document with all the images intact and inline in the right place.

It also extracts images from the notes, so they can also be referenced from local HTML (.htm) documents, Markdown, PDF, or Word (DOCX) documents.

* Released under [MIT license](./LICENSE.txt)
* [Release Information](./RELEASES.md)
* [Possible features ](./TODO.md)for future versions

## Setup

### Install homebrew

If Homebrew is not installed, open the Terminal and run this command:

```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Install Git

If Git is not already installed on your Mac, you can install it using Homebrew (or get a more up-to-date version!)

1. **Install Git using Homebrew:**
   ```bash
   brew install git
   ```

### Decide where to download the script

Change directory in terminal to wherever you want the scripts to be downloaded to - e.g.

```bash
cd $HOME/Downloads
```

### Clone the Repository

Clone the `notes-exporter` repository from GitHub:

```bash
git clone https://github.com/storizzi/notes-exporter.git
cd notes-exporter
```

### Install Python and Dependencies

Ensure Python 3 is installed on your Mac. Python 3 can be installed via Homebrew:

```bash
brew install python
```

After installing Python, install the required Python libraries using pip (markdownify is not required if you do not wish to generate markdown files and pypandoc is not required if you do not wish to generate docx / word files):

```bash
pip install beautifulsoup4  # For parsing HTML files.
pip install markdownify     # For converting HTML to Markdown.
pip install pypandoc        # For converting HTML to DOCX. Requires Pandoc.
```

**Note:** `pypandoc` requires Pandoc for generating docx (word documents). If you need this functionality, install it using Homebrew if not already installed:

```bash
brew install pandoc
```

**Note:** To convert to PDF, [Google Chrome](https://www.google.com/chrome/) needs to be installed

### Additional Dependencies

- **Google Chrome:** Needed for converting notes to PDF format.
- **Pandoc:** Required if converting notes to Word (DOCX) format.

### Clone or Download the Script

Clone or download the script files from the provided repository to your local machine.

## Basic Usage

The `exportnotes.zsh` script is used to export Apple Notes. It accepts various command-line parameters to customize the export process.

### Default Behavior

By default, the script will:

- Export notes for each account and folder in each account to the `~/Downloads/AppleNotesExport` directory as html files - i.e. the AppleNotesExport folder inside the current user's Downloads folder, then the html folder underneath this, then a folder of the format `<account>-<folder/notebook>`
  - The filenames are a simplified version of the title of each note with a .html ending - these have the images embedded inside them
- Extract images from notes into the attachments folder
  - The filenames are the filename of the image in which the attachment appears followed by a dash, followed by a number - e.g. the document my-document.html will appear as attachments/my-document-001.png
- Not convert notes to Markdown, PDF, or Word unless specified.
- Effectively, this makes the script work like a 'backup' to html files which can be browsed with a web browser

### Running the Script

Ensure the script has execution permissions:

```bash
chmod +x exportnotes.zsh
```

Run the script from the directory where it is located or add the script's directory to your `PATH` in your `.zshrc` or `.bashrc` file for easy access. For example, if you place the scripts in `$HOME/bin`:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Then, you can run the script from anywhere by just typing `exportnotes.zsh`.

### Examples

Export notes with default settings:

```bash
exportnotes.zsh
```

Export notes to a specific directory and convert them to Markdown:

```bash
exportnotes.zsh --root-dir $HOME/Documents/NotesExport --convert-markdown true
```

Use existing imported files from a specific directory and convert to PDF

```bash
exportnotes.zsh --root-dir $HOME/Documents/NotesExport --extract-data false --convert-pdf true
```

Suppress headers and footers in PDF and also convert to Word:

```bash
exportnotes.zsh -s true -w true
```

## Advanced Usage

### Command-Line Parameters

- `--root-dir` or `-r`: Set the root directory for exports. Defaults to `$HOME/Downloads/AppleNotesExport`.
- `--suppress-header-pdf` or `-s`: Suppress headers and footers in PDF exports. Set to `true` or `false`. Defaults to false
- `--extract-data` or `-e`: Extract data from Apple Notes. Set to `true` or `false`. Defaults to true - useful
- `--convert-word` or `-w`: Convert notes to Word (DOCX). Set to `true` or `false`. Defaults to false
- `--convert-pdf` or `-p`: Convert notes to PDF. Set to `true` or `false`. Defaults to false
- `--suppress-header-pdf` or `-s`: Suppress headers and footers in PDF exports. Set to `true` or `false`. Defaults to false
- `--extract-images` or `-i`: Extract images from notes. Set to `true` or `false`. Ignored if extracting to Markdown, PDF or Word as this is required. Defaults to true
- `--note-limit` or `-l`: Set a limit on the number of notes to export. Defaults to no limit
- `--note-limit-per-folder` or `-f`: Set a limit on the number of notes to export per folder. Defaults to no limit
- `--note-pick-probability` or `-b`: Set the probability (percentage) of picking a note for export for 0-100 - default is 100 - if you want a random selection of notes. Defaults to 100 (all notes - 100% probability)

### Environment variables

Instead of using command line parameters, you can set up environment variables which will be used by default (and which can be overridden by command line parameters) if for example you want to set up a standard way of working when running the script but sometimes override the behaviour.

The available environment variables are:

- `NOTES_EXPORT_ROOT_DIR`: Specifies the root directory where the exported notes will be stored. Default is `$HOME/Downloads/AppleNotesExport`
- `NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF`: Controls whether headers and footers are suppressed in PDF exports. Set to `true` to suppress, `false` otherwise.
- `NOTES_EXPORT_CONVERT_TO_MARKDOWN`: Enables the conversion of notes to Markdown format. Set to `true` to enable conversion, `false` otherwise.
- `NOTES_EXPORT_CONVERT_TO_PDF`: Enables the conversion of notes to PDF format. Set to `true` to enable conversion, `false` otherwise.
- `NOTES_EXPORT_CONVERT_TO_WORD`: Enables the conversion of notes to Word (DOCX) format. Set to `true` to enable conversion, `false` otherwise.
- `NOTES_EXPORT_EXTRACT_IMAGES`: Controls the extraction of images from notes. Set to `true` to extract images, `false` otherwise.
- `NOTES_EXPORT_EXTRACT_DATA`: Determines whether to extract data from Apple Notes using the AppleScript. Set to `true` to extract, `false` otherwise.
- `NOTES_EXPORT_NOTE_LIMIT`: Sets a limit on the total number of notes to export. Default is no limit.
- `NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER`: Sets a limit on the number of notes to export per folder. Default is no limit.
- `NOTES_EXPORT_NOTE_PICK_PROBABILITY`: Sets the probability (as a percentage) of picking a note for export. Default is 100%.

You could add these to your `.zshrc` file for example to set up defaults so you don't have to use command-line parameters if you want to set up a specific location to export to, for example - e.g.

```text
export - `NOTES_EXPORT_ROOT_DIR`
```

### Configure Zsh

To make the scripts easily accessible, add the script directory to your `PATH` in the `.zshrc` file so you can just run the command when you open the terminal:

1. **Open `.zshrc` in a text editor (e.g., nano, vim):**

   ```bash
   nano ~/.zshrc
   ```
2. **Add the following line to the file:**
   Replace `/path/to/notes-exporter` with the actual path to the `notes-exporter` directory - e.g. `$HOME/bin` if you have copied the files to the `bin` directory for your user's mac account.

   ```text
   export PATH="/path/to/notes-exporter:$PATH"
   ```
3. **Save and close the file:**
   If using nano, press `CTRL + X`, then `Y` to save, and `Enter` to exit.
4. **Reload the `.zshrc` file:**

   ```bash
   source ~/.zshrc
   ```
   or just start a new Terminal window or tab.
