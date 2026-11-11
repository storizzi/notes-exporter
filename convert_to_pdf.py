import os
import shutil
import subprocess
import sys

from notes_export_utils import get_tracker, run_for_notes

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_chrome():
    configured = os.getenv('NOTES_EXPORT_CHROME')
    if configured:
        return configured
    for candidate in CHROME_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("google-chrome") or shutil.which("chromium")


def convert_note(tracker, chrome, note, suppress_header: bool, no_overwrite: bool):
    print(f"Converting: {note['filename']} from {note['notebook']}")
    output_file = tracker.get_output_path('pdf', note['notebook'], note['filename'], '.pdf')
    if no_overwrite and output_file.exists():
        print(f"Skipping (no-overwrite): {output_file}")
        return None
    cmd = [chrome, "--headless"]
    if suppress_header:
        cmd.append("--no-pdf-header-footer")
    cmd.extend(["--print-to-pdf=" + str(output_file), str(note['source_file'])])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error converting {note['filename']}: Chrome returned code {result.returncode}")
        if result.stderr:
            print(f"Chrome error: {result.stderr}")
        return False
    print(f"Created: {output_file}")
    tracker.mark_note_exported(note['json_file'], note['note_id'], 'pdf')
    return True


def convert_html_to_pdf() -> int:
    """Convert HTML files to PDF using JSON tracking. Returns an exit code."""
    tracker = get_tracker()
    if not os.path.isabs(tracker.root_directory):
        print("Error: Root directory is not set or is a relative path.")
        return 1
    notes_to_process = tracker.get_notes_to_process('pdf')
    if not notes_to_process:
        print("No notes need PDF conversion - all up to date!")
        return 0
    chrome = find_chrome()
    if not chrome:
        print("Error: Google Chrome not found (set NOTES_EXPORT_CHROME to its executable).")
        return 1
    print(f"Processing {len(notes_to_process)} notes for PDF conversion...")
    suppress_header = os.getenv('NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF', 'true').lower() == 'true'
    no_overwrite = os.getenv('NOTES_EXPORT_NO_OVERWRITE', 'false').lower() == 'true'
    return run_for_notes('pdf', notes_to_process,
                         lambda n: convert_note(tracker, chrome, n, suppress_header, no_overwrite))


if __name__ == "__main__":
    sys.exit(convert_html_to_pdf())
