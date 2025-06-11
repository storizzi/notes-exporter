# Releases <!-- omit from toc -->

- [10 June 2025 - Release 1.0.0 - Incremental Export \& Deletion Tracking - BREAKING CHANGES!](#10-june-2025---release-100---incremental-export--deletion-tracking---breaking-changes)
- [6 June 2025 - Release 0.3 - Automated Scheduling \& Output Improvements](#6-june-2025---release-03---automated-scheduling--output-improvements)
- [10 June 2024 - Release 0.2 - Filename format / other file types](#10-june-2024---release-02---filename-format--other-file-types)
- [8 December 2023 - Release 0.1 - Initial Release](#8-december-2023---release-01---initial-release)


## 10 June 2025 - Release 1.0.0 - Incremental Export & Deletion Tracking - BREAKING CHANGES!

In this release, we introduce update mode, making exports up to 5x faster and overall processing including conversions up to 12x faster for everyday use.

This involves breaking changes, so it is recommended that you regenerate your data directories, to improve performance and a few weird design decisions made early on. In particular, the html directory has been broken up into the raw directory for raw extracted html files with embedded images, and the html directory (with html extensions instead of htm) for html with the images broken out into a subdirectory.  Filenames now include the document ID to avoid overwrites of files with the same title, and a new data directory keeps track of what has been read and written allowing for a new default option of only reading documents from Apple Notes, and updating documents already exported where they have changed - including renames. Quite the overhaul, and hopefully you'll notice the difference when exporting regularly.

* **Build versioning introduced**: I'm doing n.n.n style versioning with major versions for big structural changes (like this one - 1.0.0), minor versions (e.g. 1.1.0) for things involving breaking changes, and build numbers for small feature improvements and bug fixes (e.g. 1.1.1).
* **Incremental Export System**: Complete rewrite of conversion scripts to use JSON-based tracking for dramatically improved performance
  * New shared utility module (`notes_export_utils.py`) - only processes notes that have changed since last export
  * Tracks export status per format: `lastExportedToMarkdown`, `lastExportedToPdf`, `lastExportedToWord`, `lastExportedToImages`
  * Subsequent exports are much, much faster as only changed/new notes are processed (by default)
* **Deletion Tracking**: Automatically detects when notes are removed from Apple Notes and marks them with `deletedDate` timestamp
* **Filename Collision Prevention**: Changed default filename format from `&title` to `&title-&id` to ensure unique filenames and avoiding accidental overwrites
* **All-Formats Export**: Added `--all-formats`/`--all`/`-a` flag to read data (raw / text) and export to all formats (HTML, Markdown, PDF, Word, images) in one command
* **Renaming**: When a file is renamed in an update, all converted files are deleted, and all associated images are deleted, and regenerated with new filenames so you don't end up with orphan old copies of documents and images hanging about
* **JSON Tracking Data**: New tracking system using JSON files in `data/` directory to store note metadata and export history - will be expanding on this in future versions
* **Enhanced Character Handling**: Further improved filename sanitization while preserving Unicode characters and international text
* **Performance Optimization**: All Python conversion scripts rewritten for incremental processing - first export same speed, subsequent exports dramatically faster by checking the last modification date
* **File Naming Consistency**: Standardized script filenames to use underscores instead of dashes (e.g., `convert_to_markdown.py`, `extract_images.py`)
* **Update dependencies**: Updated requirements.txt as the library versions were a bit outdated

### Speed comparison - Update mode vs Recreate everything mode <!-- omit from toc -->

| Metric                     | Fresh Export | Update Mode | Speedup (Fresh ÷ Update) |
| -------------------------- | -----------: | ----------: | -----------------------: |
| **AppleScript processing** |        687 s |       129 s |                    5.33× |
| **Other operations**       |        882 s |         1 s |                     882× |
| **Combined total**         |      1 569 s |       130 s |                   12.07× |

* **AppleScript processing** in a fresh run takes about 5.3 times as long as in update-only mode.
* **Conversion/other operations** take some 882 times longer when re-exporting everything.
* **Overall**, a full fresh export is roughly **12 times** slower than simply checking for updates with no changes.

This uses a sample size of 769 notes, many including a lot of images embedded, exporting to HTML, Docx, Markdown and PDF (as well as the default raw html and text formats).

## 6 June 2025 - Release 0.3 - Automated Scheduling & Output Improvements

### New Features <!-- omit from toc -->
* **Automated Scheduling System**: Added comprehensive LaunchD scheduling support for macOS
  * New Python script (`setup_launchd.py`) for creating, managing, and debugging scheduled exports
  * Automatic wrapper script generation that properly sources shell environment and conda
  * Support for both daily scheduling (`--hour`, `--minute`) and interval-based scheduling (`--interval`)
  * Complete job lifecycle management: `--load`, `--unload`, `--test`, `--status`, `--remove`, `--debug`
  * Automatic permission handling and environment variable setup
  * Comprehensive logging with separate stdout/stderr streams
  * Smart job reloading that automatically unloads existing jobs before loading new ones

### Improvements <!-- omit from toc -->
* **Better Output Handling**: Modified AppleScript to properly route informational messages to stdout and errors to stderr
* **Combined Commands**: Support for chaining multiple actions in a single command (e.g., `--hour 22 --minute 15 --load --test`)
* **Environment File Support**: Added `.env` file support for custom environment variables in scheduled jobs
* **Enhanced Debugging**: Added comprehensive debugging tools to troubleshoot scheduling and permission issues
* **Documentation**: Added detailed scheduling section to README.md with setup instructions and troubleshooting

### Bug Fixes <!-- omit from toc -->
* Fixed AppleScript filename validation to handle edge case where removing trailing dash could result in empty filename
* Improved error handling for file write operations in AppleScript
* Fixed permission issues that could cause "Input/output error" when loading jobs
* Enhanced environment variable detection and sourcing for scheduled execution

### Technical Details <!-- omit from toc -->
* LaunchD integration provides more reliable scheduling than cron for GUI applications
* Automatic detection of conda installations and proper environment activation
* Support for multiple scheduling patterns and easy reconfiguration
* Comprehensive permission setup guide for macOS security requirements

## 10 June 2024 - Release 0.2 - Filename format / other file types

* `--filename-format` Format of main part of filename before the filetype for word/pdf/html - default is &title but can contain &title for a santitized version of the title (note this can change), and / or &id for the internal id apple uses for the note to generate a filename with a specific format. Thanks to @cromulus for the suggestion and sample code - I decided rather than to have an ID option to have a more general file format option so if more file format requirements appear, we don't need to have lots of new command line options / environment variables!
* Similar for `--subdir-format` - the notes folder subdirectory is now optional and can be formatted
* Added requirements.txt to pip install easily
* Option to create / teardown conda environment before / after running
* Use python instead of python3 in case using conda
* Update README.md to include better install instructions, including miniconda
* Fix issue where problematic parameters could cause an infinite while loop in shell script

## 8 December 2023 - Release 0.1 - Initial Release

Initial release with features like:

* Load data from all Apple Notes linked accounts and folders as HTML and Text - great for a basic backup
* Extract embedded attachments from HTML and put into subfolder as .htm files
* Convert to PDF files with embedded images
* Convert to Word (.DOCX) files with embedded images
* Convert to Markdown format with files in a subfolder (e.g. for use in another note-taking tool like Obsidian)
* Command line parameters and environment variables to help customize how to use the tool