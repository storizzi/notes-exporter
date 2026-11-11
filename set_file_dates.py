#!/usr/bin/env python3
"""
Set filesystem dates for exported notes to match Apple Notes dates.

Reads the JSON tracking data and sets the creation date and modification date
of exported files to match the dates from Apple Notes.

Based on a contribution by David Lowenfels (@dfl).
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def parse_apple_date(date_string):
    """
    Parse Apple Notes date format to datetime object.

    Apple Notes format: "Thursday, August 26, 2021 at 7:38:15 PM"
    Note: May contain non-breaking space (\u202f) before AM/PM.
    """
    # Remove non-breaking space
    date_string = date_string.replace('\u202f', ' ')

    formats = [
        "%A, %B %d, %Y at %I:%M:%S %p",    # 12-hour format, month before day
        "%A, %d %B %Y at %I:%M:%S %p",     # 12-hour format, day before month
        "%A, %d %B %Y at %H:%M:%S",        # 24-hour format, day before month
        "%A, %B %d, %Y at %H:%M:%S",       # 24-hour format, month before day
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue

    print(f"Warning: Could not parse date '{date_string}'", file=sys.stderr)
    return None


def set_file_dates(file_path, creation_date, modification_date):
    """
    Set both creation and modification dates on a file.

    Uses touch -t for modification date and SetFile (from Xcode tools)
    for creation date on macOS.
    """
    if not os.path.exists(file_path):
        return False

    try:
        # Set modification date using touch -t (format: [[CC]YY]MMDDhhmm[.SS])
        mod_timestamp = modification_date.strftime("%Y%m%d%H%M.%S")
        subprocess.run(['touch', '-t', mod_timestamp, file_path], check=True)

        # Set creation date (birth time) using SetFile from Xcode tools
        create_timestamp = creation_date.strftime("%m/%d/%Y %H:%M:%S")
        try:
            subprocess.run(
                ['SetFile', '-d', create_timestamp, file_path],
                check=True, capture_output=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # SetFile not available - creation date won't be set
            pass

        return True
    except subprocess.CalledProcessError as e:
        print(f"Error setting dates for {file_path}: {e}", file=sys.stderr)
        return False


def process_notebook_data(data_file, root_dir, use_subdirs, subdir_name=None):
    """Process a single notebook JSON file and set dates for all its files."""
    if not os.path.exists(data_file):
        return 0

    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    files_updated = 0

    for note_id, note_data in data.items():
        filename = note_data.get('filename')
        created_str = note_data.get('created')
        modified_str = note_data.get('modified')

        if not filename or not created_str or not modified_str:
            continue

        # Skip deleted notes
        if 'deletedDate' in note_data:
            continue

        created_date = parse_apple_date(created_str)
        modified_date = parse_apple_date(modified_str)

        if not created_date or not modified_date:
            continue

        # Build file paths for all possible export formats
        if use_subdirs and subdir_name:
            base = root_dir / '{format_dir}' / subdir_name
        else:
            base = root_dir / '{format_dir}'

        file_specs = [
            ('html', f"{filename}.html"),
            ('text', f"{filename}.txt"),
            ('raw', f"{filename}.html"),
            ('md', f"{filename}.md"),
            ('pdf', f"{filename}.pdf"),
            ('docx', f"{filename}.docx"),
        ]

        for format_dir, file_name in file_specs:
            if use_subdirs and subdir_name:
                file_path = root_dir / format_dir / subdir_name / file_name
            else:
                file_path = root_dir / format_dir / file_name

            if file_path.exists():
                if set_file_dates(str(file_path), created_date, modified_date):
                    files_updated += 1

    return files_updated


def main():
    """Process all notebooks and set filesystem dates."""
    root_dir = Path(os.environ.get(
        'NOTES_EXPORT_ROOT_DIR',
        os.path.expanduser('~/Downloads/AppleNotesExport')
    ))
    use_subdirs = os.environ.get('NOTES_EXPORT_USE_SUBDIRS', 'true').lower() == 'true'

    data_dir = root_dir / 'data'

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}", file=sys.stderr)
        print("Please run the export script first to create tracking data.", file=sys.stderr)
        sys.exit(1)

    print("Setting file dates from Apple Notes tracking data...")
    print(f"Root directory: {root_dir}")

    total_files_updated = 0

    for json_file in sorted(data_dir.glob('*.json')):
        if json_file.name == 'export_stats.tmp':
            continue

        subdir_name = json_file.stem
        files_updated = process_notebook_data(json_file, root_dir, use_subdirs, subdir_name)
        if files_updated > 0:
            print(f"  {subdir_name}: updated {files_updated} files")
        total_files_updated += files_updated

    print(f"Completed - updated dates for {total_files_updated} files.")

    # Check if SetFile is available for creation date support
    try:
        subprocess.run(['which', 'SetFile'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print()
        print("Note: SetFile not found - creation dates were not set.")
        print("Install Xcode Command Line Tools for creation date support:")
        print("  xcode-select --install")


if __name__ == '__main__':
    main()
