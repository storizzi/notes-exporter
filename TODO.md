# To Do

Some features that might be useful to include in the future in no particular order:

* Ensure non-image files can also be downloaded to attachments (this isn't available in the API so some hackery would be needed)
* ~~Filter to specify specific accounts / notebooks~~ ✅ Done in v1.2.1 (`--filter-accounts`, `--filter-folders`)
* ~~If use short form of parameters should be able to specify parameter without true implicitly~~ ✅ Done in v1.2.1 (all boolean options now support flag form)
* ~~Option to NOT overwrite files / warn if going to do so~~ ✅ Done in v1.3.0 (`--no-overwrite`)
* ~~Clear down directory before download (optionally)~~ ✅ Done in v1.2.1 (`--clean`)
* Allow for mailbox and then notebook directory structure
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
