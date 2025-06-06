# Releases

Release information follows...

## 6 June 2025 - Release 0.3 - Automated Scheduling & Output Improvements

### New Features
* **Automated Scheduling System**: Added comprehensive LaunchD scheduling support for macOS
  * New Python script (`setup_launchd.py`) for creating, managing, and debugging scheduled exports
  * Automatic wrapper script generation that properly sources shell environment and conda
  * Support for both daily scheduling (`--hour`, `--minute`) and interval-based scheduling (`--interval`)
  * Complete job lifecycle management: `--load`, `--unload`, `--test`, `--status`, `--remove`, `--debug`
  * Automatic permission handling and environment variable setup
  * Comprehensive logging with separate stdout/stderr streams
  * Smart job reloading that automatically unloads existing jobs before loading new ones

### Improvements
* **Better Output Handling**: Modified AppleScript to properly route informational messages to stdout and errors to stderr
* **Combined Commands**: Support for chaining multiple actions in a single command (e.g., `--hour 22 --minute 15 --load --test`)
* **Environment File Support**: Added `.env` file support for custom environment variables in scheduled jobs
* **Enhanced Debugging**: Added comprehensive debugging tools to troubleshoot scheduling and permission issues
* **Documentation**: Added detailed scheduling section to README.md with setup instructions and troubleshooting

### Bug Fixes
* Fixed AppleScript filename validation to handle edge case where removing trailing dash could result in empty filename
* Improved error handling for file write operations in AppleScript
* Fixed permission issues that could cause "Input/output error" when loading jobs
* Enhanced environment variable detection and sourcing for scheduled execution

### Technical Details
* LaunchD integration provides more reliable scheduling than cron for GUI applications
* Automatic detection of conda installations and proper environment activation
* Support for multiple scheduling patterns and easy reconfiguration
* Comprehensive permission setup guide for macOS security requirements

## 10 Jun 2024 - Release 0.2 - Filename format / other file types

* `--filename-format` Format of main part of filename before the filetype for word/pdf/html - default is &title but can contain &title for a santitized version of the title (note this can change), and / or &id for the internal id apple uses for the note to generate a filename with a specific format. Thanks to @cromulus for the suggestion and sample code - I decided rather than to have an ID option to have a more general file format option so if more file format requirements appear, we don't need to have lots of new command line options / environment variables!
* Similar for `--subdir-format` - the notes folder subdirectory is now optional and can be formatted
* Added requirements.txt to pip install easily
* Option to create / teardown conda environment before / after running
* Use python instead of python3 in case using conda
* Update README.md to include better install instructions, including miniconda
* Fix issue where problematic parameters could cause an infinite while loop in shell script

## 8 Dec 2023 - Release 0.1 - Initial Release

Initial release with features like:

* Load data from all Apple Notes linked accounts and folders as HTML and Text - great for a basic backup
* Extract embedded attachments from HTML and put into subfolder as .htm files
* Convert to PDF files with embedded images
* Convert to Word (.DOCX) files with embedded images
* Convert to Markdown format with files in a subfolder (e.g. for use in another note-taking tool like Obsidian)
* Command line parameters and environment variables to help customize how to use the tool