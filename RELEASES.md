## Releases

Release information follows...

## 9 Jun 2024 - Release 0.2 - Filename format / other file types

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
