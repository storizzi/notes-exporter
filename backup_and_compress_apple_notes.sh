#!/bin/bash

echo "Running AppleScript to export notes..."
backup_directory=$(osascript ./apple-export-notes.scpt)

echo "Extracting backup directory path from the script output..."
backup_dir=$(echo "$backup_directory" | grep -o 'Backup Directory Folder: .*' | sed 's/Backup Directory Folder: //')

zip_location="$1"

if [ -z "$zip_location" ]; then
    echo "No zip file location argument provided, using the current directory."
    zip_location="./"
else
    echo "Zip file location provided: $zip_location"
    [[ "$zip_location" != */ ]] && zip_location="$zip_location/"
fi

if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
    echo "Backup directory found: $backup_dir"

    backup_dir_name="${backup_dir##*/}"

    echo "Zipping the backup directory..."
    zip -r "${zip_location}${backup_dir_name}.zip" "$backup_dir"

    echo "Converting backup directory path to an absolute path..."
    absolute_backup_dir="$(pwd)/$backup_dir"

    echo "Deleting the backup directory..."
    osascript -e "tell application \"Finder\" to delete POSIX file \"$absolute_backup_dir\""

    echo "Backup directory processed and moved to Trash."
else
    echo "Error: Backup directory does not exist."
fi
