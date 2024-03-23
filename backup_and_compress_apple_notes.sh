#!/bin/bash

echo "Running AppleScript to export notes..."
backup_directory=$(osascript ./apple-export-notes.scpt)

echo "Extracting backup directory path from the script output..."
backup_dir=$(echo "$backup_directory" | grep -o 'Backup Directory Folder: .*' | sed 's/Backup Directory Folder: //')

if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
    echo "Backup directory found: $backup_dir"

    echo "Zipping the backup directory..."
    zip -r "${backup_dir}.zip" "$backup_dir" # Quote the directory path

    echo "Converting backup directory path to an absolute path..."
    absolute_backup_dir="$(pwd)/$backup_dir"

    echo "Deleting the backup directory..."
    osascript -e "tell application \"Finder\" to delete POSIX file \"$absolute_backup_dir\""

    echo "Backup directory processed and moved to Trash."
else
    echo "Error: Backup directory does not exist."
fi
