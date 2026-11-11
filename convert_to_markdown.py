import os
import sys

from bs4 import BeautifulSoup
from markdownify import markdownify as md

from notes_export_utils import get_tracker, run_for_notes, file_sha256


def convert_note(tracker, note, no_overwrite: bool, protect_edits: bool):
    print(f"Converting: {note['filename']} from {note['notebook']}")
    output_file = tracker.get_output_path('md', note['notebook'], note['filename'], '.md')
    if no_overwrite and output_file.exists():
        print(f"Skipping (no-overwrite): {output_file}")
        return None

    # Never overwrite Markdown edited locally since it was exported or synced
    # (it would be lost before the sync step could send it back).
    info = note['note_info']
    baseline = info.get('localFileHashAtLastSync') or info.get('markdownHash')
    if protect_edits and baseline and output_file.exists() and file_sha256(output_file) != baseline:
        print(f"Kept locally edited {output_file}; the note changed in Apple Notes too. "
              f"Sync it (--sync) or delete the file to take the Apple Notes version.")
        return None

    with open(note['source_file'], "r", encoding="utf-8") as file:
        soup = BeautifulSoup(file, "html.parser")
        markdown_text = md(str(soup), heading_style="ATX")
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(markdown_text)
    print(f"Created: {output_file}")

    tracker.copy_attachments(note['source_file'], output_file)
    tracker.mark_note_exported(note['json_file'], note['note_id'], 'markdown',
                               extra={'markdownHash': file_sha256(output_file),
                                      'modifiedAtMarkdownExport': info.get('modified', '')})
    return True


def convert_html_to_md() -> int:
    """Convert HTML files to Markdown using JSON tracking. Returns an exit code."""
    tracker = get_tracker()
    notes_to_process = tracker.get_notes_to_process('markdown')
    if not notes_to_process:
        print("No notes need markdown conversion - all up to date!")
        return 0
    print(f"Processing {len(notes_to_process)} notes for markdown conversion...")
    no_overwrite = os.getenv('NOTES_EXPORT_NO_OVERWRITE', 'false').lower() == 'true'
    # 'remote' means Apple Notes wins conflicts, so the export may overwrite.
    protect_edits = os.getenv('NOTES_EXPORT_CONFLICT_STRATEGY', '') != 'remote'
    return run_for_notes('markdown', notes_to_process,
                         lambda n: convert_note(tracker, n, no_overwrite, protect_edits))


if __name__ == "__main__":
    sys.exit(convert_html_to_md())
