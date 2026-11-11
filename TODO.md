# To Do

Some features that might be useful to include in the future in no particular order:

* Ensure non-image files can also be downloaded to attachments. Two possible routes: Notes' AppleScript dictionary lets an attachment `save` itself to a file (no extra permissions; not yet tried), or the files under Notes' group container found through the database (needs Full Disk Access; PR #27 does this for PDFs)
* ~~Filter to specify specific accounts / notebooks~~ ✅ Done in v1.2.1 (`--filter-accounts`, `--filter-folders`)
* ~~If use short form of parameters should be able to specify parameter without true implicitly~~ ✅ Done in v1.2.1 (all boolean options now support flag form)
* ~~Option to NOT overwrite files / warn if going to do so~~ ✅ Done in v1.3.0 (`--no-overwrite`)
* ~~Clear down directory before download (optionally)~~ ✅ Done in v1.2.1 (`--clean`)
* ~~Allow for mailbox and then notebook directory structure~~ ✅ Done in v1.4.0 (`--folder-hierarchy`, `&folderpath`)
* ~~Filter to only include files that have been changed after a specific date~~ ✅ Done in v1.3.0 (`--modified-after`)
* ~~Option to put images at the same level as documents instead of a subdirectory~~ ✅ Done in v1.3.0 (`--images-beside-docs`)
* Option to group images at the account level
* Option to group images at the notebook level
* ~~Optionally put proper HTML page tags around the pages so they are properly formatted (e.g. with the title as the original note title)~~ ✅ Done in v1.3.0 (`--html-wrap`)
* ~~Optionally share images so they are not being duplicated~~ ✅ Done in v1.3.0 (`--dedup-images`)
* ~~Let the different format files be output in different directories to the default - params + env vars~~ ✅ Already implemented (each format uses its own directory: raw/, html/, text/, md/, pdf/, docx/)
* Optionally delete notes after they have been downloaded (e.g. for migration purposes)
* ~~Possible to change files and sync them back~~ ✅ Done in v1.3.0 (bidirectional sync with `--sync`, `--sync-only`, `--create-new`)
* Consider exports from other note taking applications - e.g. Evernote - Apple Notes does have an import, but embedded non-image files are still a problem - perhaps we could sync export from enex files and files imported into Apple Notes in some way
* ~~Machine-readable state of an export for other programs~~ ✅ Done in v1.4.0 (`manifest.json`, `--json-log` events, exit codes, see INTEGRATION.md)
* ~~Remove files of deleted notes~~ ✅ Done in v1.4.0 (`--prune-deleted`)
* ~~Convert images to another format~~ ✅ Done in v1.4.0 (`--image-format`)
* ~~Tags~~ ✅ Done in v1.4.0 (`--tags`, from the Notes database; needs Full Disk Access)
* Read tags without Full Disk Access (AppleScript does not expose them today)
* A rename that only changes letter case is not treated as a rename (AppleScript compares names ignoring case), so on a case-sensitive volume the old file stays
