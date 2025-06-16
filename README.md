# Apple Notes Export Tool <!-- omit from toc -->

<figure style="float: right; margin-left: 10px;">
    <img src="notes-exporter.jpg" alt="Notes Exporter" width="200">
</figure>

This tool facilitates the export of Apple Notes into various formats including raw HTML, processed HTML (with local attachments), Plain Text, Markdown, PDF, and Word (DOCX) with images and most formatting left intact.

You can use it either as a basic backup or as a conversion tool - e.g. the Markdown format could be used in a note-taking tool like Obsidian which uses Markdown as standard.

This tool works on a Mac (macOS) not on a Windows or Linux machine because it uses AppleScript to extract the data from notes. You need to have the Notes app installed.

This allows for you to keep a local copy of your apple notes, use them in other markdown note-taking apps such as Obsidian, and quickly grab copies if you wish to send PDF versions to anyone, or work on a copy of the document from a Word document with all the images intact and inline in the right place.

It also extracts images from the notes, so they can also be referenced from local HTML, Markdown, PDF, or Word (DOCX) documents.

* Released under [MIT license](./LICENSE.txt)
* [Release Information](./RELEASES.md)
* [Possible features ](./TODO.md)for future versions

## Table of Contents <!-- omit from toc -->

- [Setup](#setup)
  - [Install homebrew](#install-homebrew)
  - [Install Git](#install-git)
  - [Decide where to download the script](#decide-where-to-download-the-script)
  - [Clone the Repository](#clone-the-repository)
  - [Install Python and Dependencies](#install-python-and-dependencies)
  - [Additional Dependencies](#additional-dependencies)
- [Basic Usage](#basic-usage)
  - [Default Behavior](#default-behavior)
  - [Update Modes](#update-modes)
  - [Running the Script](#running-the-script)
  - [Examples](#examples)
- [Advanced Usage](#advanced-usage)
  - [Command-Line Parameters](#command-line-parameters)
  - [Environment Variables](#environment-variables)
  - [Configure Zsh](#configure-zsh)
- [Scheduling Automatic Exports](#scheduling-automatic-exports)
- [Setup Automatic Scheduling](#setup-automatic-scheduling)
    - [Permissions Setup](#permissions-setup)
  - [Install the Scheduling Tool](#install-the-scheduling-tool)
    - [Create Scheduled Export](#create-scheduled-export)
    - [Manage the Scheduled Job](#manage-the-scheduled-job)
    - [Environment Variables for Scheduled Jobs](#environment-variables-for-scheduled-jobs)
    - [Monitor Scheduled Exports](#monitor-scheduled-exports)
    - [Troubleshooting Scheduled Jobs](#troubleshooting-scheduled-jobs)
    - [Remove Scheduling](#remove-scheduling)
- [Tests](#tests)

## Setup

### Install homebrew

If Homebrew is not installed, open the Terminal and run this command:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Install Git

If Git is not already installed on your Mac, you can install it using Homebrew (or get a more up-to-date version).

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
mkdir -p ~/bin/notes-exporter
cd ~/bin/notes-exporter
git clone https://github.com/storizzi/notes-exporter.git .
```

### Install Python and Dependencies

Ensure Python 3 is installed on your Mac. Python 3 can be installed via Homebrew:

```bash
brew install python
```

or alternatively if you want to use conda to install python environments you can use:
```bash
brew install --cask miniconda
```

If you are using conda, then you can get the script to do the next bit for you (see later) in which case you can skip the 'pip install' here.

After installing Python, it is easiest to install the required libraries using the `requirements.txt` file:

```bash
pip install -r ./requirements.txt
```

Alternatively, you can install them manually (`markdownify` is only required for Markdown conversion and `pypandoc` is only required for Word conversion):

```bash
pip install beautifulsoup4  # For parsing HTML files.
pip install markdownify     # For converting HTML to Markdown.
pip install pypandoc        # For converting HTML to DOCX. Requires Pandoc.
```

**Note:** `pypandoc` requires Pandoc for generating docx (word documents). If you need this functionality, install it using Homebrew if not already installed:

```bash
brew install pandoc
```

**Note:** To convert to PDF, [Google Chrome](https://www.google.com/chrome/) needs to be installed.

### Additional Dependencies

* **Google Chrome:** Needed for converting notes to PDF format.
* **Pandoc:** Required if converting notes to Word (DOCX) format.

## Basic Usage

The `exportnotes.zsh` script is used to export Apple Notes. It accepts various command-line parameters to customize the export process.

### Default Behavior

By default, the script performs an **incremental export**, which is significantly faster for regular use. It will:

* Export notes to the `$HOME/Downloads/AppleNotesExport` directory.
* Create several subdirectories for organization:
    * `data/`: Stores JSON files to track export status and modification dates for each note. This is the key to the fast incremental updates.
    * `raw/`: Contains the raw HTML dump from Apple Notes with images embedded as base64 data.
    * `html/`: Contains processed HTML files where embedded images have been extracted and replaced with links to local files.
    * `text/`: Contains the plain text content of the notes.
* Only process notes that are new or have been modified since the last run.
* Automatically detect notes that have been deleted in the Notes app and mark them as `deleted` in the tracking files.
* Use a default filename format of `&title-&id` (e.g., "My-Note-4159.html") to prevent conflicts between notes that have the same title.
* If a note is renamed, the script automatically cleans up the old files and their attachments to prevent orphaned files.
* Extract images into an `attachments` sub-folder. The image filename is based on the note's filename (e.g., `My-Note-4159-attachment-001.png`).
* Not convert notes to Markdown, PDF, or Word unless specified.

### Update Modes

The script operates in two modes:

* **Default (Incremental Update)**: This is the standard mode. It's very fast because it only processes notes that have changed since the last export. It uses the JSON files in the `data/` directory to determine what needs updating.
* **Full Update (`--update-all`)**: This mode processes every note, regardless of its modification date. This is useful if you want to force a full regeneration of all files from scratch.

### Running the Script

Ensure the script has execution permissions:

```bash
cd ~/bin/notes-exporter
chmod +x exportnotes.zsh
```

Run the script from its directory or add the script's directory to your `PATH` in your `.zshrc` file for easy access. For example:

```bash
echo 'export PATH="$HOME/bin/notes-exporter:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Then, you can run the script from anywhere by just typing `exportnotes.zsh`.

### Examples

Export notes with default settings (runs an incremental backup to `~/Downloads/AppleNotesExport`):

```bash
exportnotes.zsh
```

Force a full re-export of all notes, disabling the incremental update:

```bash
exportnotes.zsh --update-all
```

Export to all formats (HTML, Text, Markdown, PDF, Word) and extract images:

```bash
exportnotes.zsh --all
```

Export notes with default settings in a python conda environment called `notesexport`, auto-creating and activating the environment if it doesn't exist, and auto-installing the required pip dependencies:

```bash
exportnotes.zsh --conda-env notesexport
```

Export notes to a specific directory and convert them to Markdown:

```bash
mkdir -p $HOME/Documents/NotesExport
exportnotes.zsh --root-dir $HOME/Documents/NotesExport --convert-markdown true
```

Use existing exported files in a directory and convert them to PDF without re-extracting from Apple Notes:

```bash
exportnotes.zsh --root-dir $HOME/Documents/NotesExport --extract-data false --convert-pdf true
```

Suppress headers and footers in PDF and also convert to Word:

```bash
exportnotes.zsh -s true -w true
```

Convert notes in a specific directory to Markdown without getting any apple notes, creating a conda environment at the start, and cleaning up that environment afterwards

```bash
exportnotes.zsh --root-dir $HOME/AppleNotesExport --conda-env exportnotes --extract-data false --convert-markdown true --remove-conda-env true
```

Import notes using filenames starting Note- then with the title, then another - and the internal ID of the note at the end

```bash
exportnotes.zsh  --filename-format "Note-&title-&id"
```

Import notes using filenames using the account name and the internal apple note ID and the folder ID without having subdirectories for the folder name

```bash
exportnotes.zsh --filename-format "&account-&folder-&id" --use-subdirs false
```

## Advanced Usage

### Command-Line Parameters

* `--root-dir` or `-r`: Set the root directory for exports. Defaults to `$HOME/Downloads/AppleNotesExport`.
* `--suppress-header-pdf` or `-s`: Suppress headers and footers in PDF exports. Set to `true` or `false`. Defaults to `true`.
* `--extract-data` or `-d`: Extract data from Apple Notes. Set to `true` or `false`. Defaults to `true`.
* `--extract-images` or `-i`: Extract images from notes. Set to `true` or `false`. Forced to `true` if converting to other formats. Defaults to `true`.
* `--convert-markdown` or `-m`: Convert notes to Markdown. Set to `true` or `false`. Defaults to `false`.
* `--convert-pdf` or `-p`: Convert notes to PDF. Set to `true` or `false`. Defaults to `false`.
* `--convert-word` or `-w`: Convert notes to Word (DOCX). Set to `true` or `false`. Defaults to `false`.
* `--update-all` or `-U`: Force a full update, disabling the default incremental export.
* `--all-formats` or `--all` or `-a`: A shortcut to enable all conversions (Markdown, PDF, Word) and image extraction.
* `--filename-format` or `-t`: Format for filenames. Default is `&title-&id`. Placeholders: `&title`, `&id`, `&account`, `&folder`, `&accountid`, `&shortaccountid`.
* `--subdir-format` or `-u`: Format for subdirectories. Default is `&account-&folder`.
* `--use-subdirs` or `-x`: Set to `false` to keep all files in a single directory. Default is `true`.
* `--note-limit` or `-n`: Set a limit on the total number of notes to export.
* `--note-limit-per-folder` or `-f`: Set a limit on the number of notes to export per folder.
* `--note-pick-probability` or `-b`: The probability (0-100) of picking a note for export. Default is 100.
* `--conda-env` or `-c`: Specify the Conda environment to use.
* `--remove-conda-env` or `-e`: Remove the specified Conda environment after the script runs.

### Environment Variables

You can also use environment variables to set defaults, which can be overridden by command-line parameters.

* `NOTES_EXPORT_ROOT_DIR`: Root directory for exports. Default: `$HOME/Downloads/AppleNotesExport`.
* `NOTES_EXPORT_UPDATE_ALL`: Set to `true` to disable incremental updates and force a full export. Default: `false`.
* `NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF`: `true` or `false` to control PDF headers.
* `NOTES_EXPORT_CONVERT_TO_MARKDOWN`: `true` to enable Markdown conversion.
* `NOTES_EXPORT_CONVERT_TO_PDF`: `true` to enable PDF conversion.
* `NOTES_EXPORT_CONVERT_TO_WORD`: `true` to enable Word (DOCX) conversion.
* `NOTES_EXPORT_EXTRACT_IMAGES`: `true` to extract images.
* `NOTES_EXPORT_EXTRACT_DATA`: `true` to extract data from Apple Notes.
* `NOTES_EXPORT_NOTE_LIMIT`: Limit total notes exported.
* `NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER`: Sets a limit on the number of notes to export per folder.
* `NOTES_EXPORT_NOTE_PICK_PROBABILITY`: Sets the probability (as a percentage) of picking a note for export. Default is 100%.
* `NOTES_EXPORT_FILENAME_FORMAT`: Format for filenames. Default is `&title-&id`. Placeholders are the same as the command-line option.
* `NOTES_EXPORT_SUBDIR_FORMAT`: Format for subdirectories. Default is `&account-&folder`.
* `NOTES_EXPORT_USE_SUBDIRS`: Set to `false` to keep all files in a single directory. Default is `true`.
* `NOTES_EXPORT_CONDA_ENV`: Specifies the Conda environment to use.
* `NOTES_EXPORT_REMOVE_CONDA_ENV`: Remove the specified Conda environment after the script runs. Default is `false`.

You could add these to your `.zshrc` file to set up defaults, for example:

```text
export NOTES_EXPORT_ROOT_DIR=$HOME/Documents/NotesExport
```

### Configure Zsh

To make the scripts easily accessible, add the script directory to your `PATH` in the `.zshrc` file.

1.  **Open `.zshrc` in a text editor (e.g., nano, vim):**

    ```bash
    nano ~/.zshrc
    ```
2.  **Add the following line to the file:**
    Replace `/path/to/notes-exporter` with the actual path to the `notes-exporter` directory.

    ```text
    export PATH="/path/to/notes-exporter:$PATH"
    ```
3.  **Save and close the file.**
4.  **Reload the `.zshrc` file:**

    ```bash
    source ~/.zshrc
    ```

## Scheduling Automatic Exports

You can schedule the notes export to run automatically using macOS's built-in `launchd` system. This is more reliable than using `cron` for AppleScript-based tasks.

## Setup Automatic Scheduling

#### Permissions Setup

**Important**: The first time you run the script, macOS will prompt for permissions to access the Notes app. To avoid repeated popups:

1.  **Grant Full Disk Access** to Terminal (or your shell).
2.  **Grant Accessibility permissions** to osascript.
3.  **Allow automation** for the Notes app.

Once these permissions are granted, the scheduled jobs will run without prompts.

### Install the Scheduling Tool

A Python script is provided to easily set up and manage scheduled exports. This script handles creating the necessary configuration files and setting permissions.

#### Create Scheduled Export

To set up a daily export at 9:00 AM:

```bash
cd ~/bin/notes-exporter
python setup_launchd.py
```

Or with custom scheduling options:

```bash
# Run daily at 2:30 PM
python setup_launchd.py --hour 14 --minute 30

# Run every 60 minutes
python setup_launchd.py --interval 60
```

This creates:
* A wrapper script that properly loads your shell environment.
* A launchd configuration file for scheduling.
* A `logs` directory for monitoring the exports.
* A sample `.env` file for custom environment variables.

#### Manage the Scheduled Job

After creating the setup, use these commands to manage your scheduled exports:

```bash
# Start scheduling (activate the job)
python setup_launchd.py --load

# Test run manually to verify it works
python setup_launchd.py --test

# Check if the job is currently scheduled
python setup_launchd.py --status

# Stop scheduling (but keep files)
python setup_launchd.py --unload

# Remove everything (stop scheduling and delete all setup files)
python setup_launchd.py --remove
```

#### Environment Variables for Scheduled Jobs

When running as a scheduled job, you can set custom environment variables by editing the `.env` file in your script directory:

```bash
nano .env
```

Example `.env` configuration:

```bash
# Export settings
export NOTES_EXPORT_ROOT_DIR="$HOME/Documents/NotesBackup"
export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"

# Conda environment
export NOTES_EXPORT_CONDA_ENV="notes-export"

# Custom PATH additions (if needed)
export PATH="/opt/homebrew/bin:$PATH"
```

#### Monitor Scheduled Exports

View the logs to see if your scheduled exports are working:

```bash
# View recent output
tail -f logs/stdout.log

# View any errors
tail -f logs/stderr.log

# View debug information
tail -f logs/debug.log
```

The debug log shows environment information that can help troubleshoot any issues with the scheduled execution.

#### Troubleshooting Scheduled Jobs

If your scheduled job isn't working:

1.  **Check job status**: `python setup_launchd.py --status`
2.  **Review logs**: Look at `logs/stderr.log` for errors.
3.  **Test manually**: Run `python setup_launchd.py --test`.
4.  **Check permissions**: Verify your Notes app has necessary accessibility permissions.
5.  **Environment issues**: Check `logs/debug.log` for environment variable problems.

#### Remove Scheduling

To completely remove the scheduled export setup:

```bash
python setup_launchd.py --remove
```

This unloads the job and removes the scheduling files while leaving your main `exportnotes.zsh` script and any exported data intact.

## Tests

Sample tests have been introduced to kick off unit testing on the tool. To run them, use the command:

```
tests/test.zsh
```

which kicks off pytest in verbos mode, writing the results to `test_results.txt` in the tests directory.
