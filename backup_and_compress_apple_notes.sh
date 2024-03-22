#!/bin/bash

backup_directory=$(osascript ./export-notes.scpt)
backup_dir=${backup_directory#*Backup Directory: }
echo $backup_dir

zip -r "${backup_dir}.zip" "${backup_dir}" # Quote the directory path
rm -rf "${backup_dir}"