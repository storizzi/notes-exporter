#!/usr/bin/env python3
"""
Set filesystem dates for exported notes to match Apple Notes dates.

This script reads the JSON tracking data and sets the creation date
and modification date of exported files to match the dates from Apple Notes.
"""

import json
import os
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Italian month name to number mapping
_ITALIAN_MONTHS = {
    'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
    'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
    'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12,
}

# Italian date pattern: "mercoledì 4 febbraio 2026 alle ore 08:11:17"
_ITALIAN_DATE_RE = re.compile(
    r'^\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})\s+alle\s+ore\s+(\d{2}):(\d{2}):(\d{2})$'
)


def _parse_italian_date(date_string):
    """Parse Italian Apple Notes date format to datetime object."""
    m = _ITALIAN_DATE_RE.match(date_string)
    if not m:
        return None
    day, month_name, year, hour, minute, second = m.groups()
    month = _ITALIAN_MONTHS.get(month_name.lower())
    if not month:
        return None
    return datetime(int(year), month, int(day), int(hour), int(minute), int(second))


def parse_apple_date(date_string):
    """
    Parse Apple Notes date format to datetime object.

    Apple Notes English format: "Thursday, August 26, 2021 at 7:38:15 PM"
    Apple Notes Italian format: "mercoledì 4 febbraio 2026 alle ore 08:11:17"
    Note: May contain non-breaking space (\\u202f) before AM/PM
    """
    # Remove non-breaking space
    date_string = date_string.replace('\u202f', ' ')

    # Try English format first
    # Format: "DayOfWeek, Month Day, Year at Hour:Minute:Second AM/PM"
    try:
        dt = datetime.strptime(date_string, "%A, %B %d, %Y at %I:%M:%S %p")
        return dt
    except ValueError:
        pass

    # Try Italian format: "mercoledì 4 febbraio 2026 alle ore 08:11:17"
    dt = _parse_italian_date(date_string)
    if dt:
        return dt

    print(f"Error parsing date '{date_string}': unsupported date format", file=sys.stderr)
    return None


def set_file_dates(file_path, creation_date, modification_date):
    """
    Set both creation and modification dates on a file using touch command.

    On macOS:
    - Uses touch -t for modification date
    - Uses SetFile (from Xcode tools) for creation date, or touch -t if not available
    """
    if not os.path.exists(file_path):
        return False

    try:
        # Set modification date using touch -t (format: [[CC]YY]MMDDhhmm[.SS])
        mod_timestamp = modification_date.strftime("%Y%m%d%H%M.%S")
        subprocess.run(['touch', '-t', mod_timestamp, file_path], check=True)

        # Set creation date (birth time) using touch -t with -d flag on macOS
        # Note: This requires macOS 10.13+ or we can use SetFile from Xcode tools
        create_timestamp = creation_date.strftime("%Y%m%d%H%M.%S")

        # Try using SetFile first (more reliable for creation date)
        try:
            # SetFile format: "MM/DD/YYYY HH:MM:SS"
            setfile_date = creation_date.strftime("%m/%d/%Y %H:%M:%S")
            subprocess.run(['SetFile', '-d', setfile_date, file_path],
                          check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # SetFile not available or failed, birth time stays as is
            # On macOS, we can't easily set birth time without SetFile
            pass

        return True
    except subprocess.CalledProcessError as e:
        print(f"Error setting dates for {file_path}: {e}", file=sys.stderr)
        return False


def process_notebook_data(data_file, root_dir, use_subdirs, subdir_name=None):
    """Process a single notebook JSON file and set dates for all its files."""

    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}", file=sys.stderr)
        return 0

    # Load JSON data
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    files_updated = 0

    # Process each note
    for note_id, note_data in data.items():
        filename = note_data.get('filename')
        created_str = note_data.get('created')
        modified_str = note_data.get('modified')

        if not filename or not created_str or not modified_str:
            continue

        # Parse dates
        created_date = parse_apple_date(created_str)
        modified_date = parse_apple_date(modified_str)

        if not created_date or not modified_date:
            continue

        # Determine file paths based on subdirectory usage
        if use_subdirs and subdir_name:
            base_paths = [
                root_dir / 'html' / subdir_name / f"{filename}.html",
                root_dir / 'text' / subdir_name / f"{filename}.txt",
                root_dir / 'raw' / subdir_name / f"{filename}.html",
                root_dir / 'md' / subdir_name / f"{filename}.md",
                root_dir / 'pdf' / subdir_name / f"{filename}.pdf",
                root_dir / 'word' / subdir_name / f"{filename}.docx",
            ]
        else:
            base_paths = [
                root_dir / 'html' / f"{filename}.html",
                root_dir / 'text' / f"{filename}.txt",
                root_dir / 'raw' / f"{filename}.html",
                root_dir / 'md' / f"{filename}.md",
                root_dir / 'pdf' / f"{filename}.pdf",
                root_dir / 'word' / f"{filename}.docx",
            ]

        # Update dates for all files that exist
        for file_path in base_paths:
            if file_path.exists():
                if set_file_dates(str(file_path), created_date, modified_date):
                    files_updated += 1
                    print(f"Updated: {file_path.name}")

    return files_updated


def main():
    """Main function to process all notebooks."""
    # Get root directory from environment or use default
    root_dir = os.environ.get('NOTES_EXPORT_ROOT_DIR',
                               os.path.expanduser('~/Downloads/AppleNotesExport'))
    root_dir = Path(root_dir)

    # Check if using subdirectories (default: true)
    use_subdirs = os.environ.get('NOTES_EXPORT_USE_SUBDIRS', 'true').lower() == 'true'

    data_dir = root_dir / 'data'

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}", file=sys.stderr)
        print("Please run the export script first to create tracking data.", file=sys.stderr)
        sys.exit(1)

    print(f"Setting file dates from Apple Notes tracking data...")
    print(f"Root directory: {root_dir}")
    print(f"Using subdirectories: {use_subdirs}")
    print()

    total_files_updated = 0

    # Process all JSON files in the data directory
    for json_file in data_dir.glob('*.json'):
        # Skip stats files
        if json_file.name == 'export_stats.tmp':
            continue

        # Extract subdirectory name from JSON filename (e.g., "iCloud-Notes.json" -> "iCloud-Notes")
        subdir_name = json_file.stem

        print(f"Processing: {subdir_name}")
        files_updated = process_notebook_data(json_file, root_dir, use_subdirs, subdir_name)
        total_files_updated += files_updated

    print()
    print(f"Completed! Updated dates for {total_files_updated} files.")

    # Check if SetFile is available
    try:
        subprocess.run(['which', 'SetFile'], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        print()
        print("Note: SetFile command not found. Creation dates were not set.")
        print("To set creation dates, install Xcode Command Line Tools:")
        print("  xcode-select --install")
        print("Or install just the developer tools if you have Xcode installed.")


if __name__ == '__main__':
    main()
