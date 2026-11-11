import os
import sys
from pathlib import Path

from notes_export_utils import get_tracker, run_for_notes


def convert_note(tracker, note, no_overwrite: bool):
    import pypandoc
    print(f"Converting: {note['filename']} from {note['notebook']}")
    output_file = tracker.get_output_path('docx', note['notebook'], note['filename'], '.docx')
    if no_overwrite and output_file.exists():
        print(f"Skipping (no-overwrite): {output_file}")
        return None
    source_file = Path(note['source_file'])
    html_content = source_file.read_text(encoding='utf-8')
    original_cwd = os.getcwd()
    try:
        # Relative image paths resolve from the HTML file's folder
        os.chdir(str(source_file.parent))
        pypandoc.convert_text(html_content, 'docx', format='html', outputfile=str(output_file))
    finally:
        os.chdir(original_cwd)
    print(f"Created: {output_file}")
    tracker.mark_note_exported(str(note['json_file']), note['note_id'], 'word')
    return True


def convert_html_to_docx() -> int:
    """Convert HTML files to Word (DOCX) using JSON tracking. Returns an exit code."""
    tracker = get_tracker()
    notes_to_process = tracker.get_notes_to_process('word')
    if not notes_to_process:
        print("No notes need Word conversion - all up to date!")
        return 0
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
    except (ImportError, OSError) as e:
        print(f"Error: Word conversion needs pypandoc and Pandoc (brew install pandoc): {e}")
        return 1
    print(f"Processing {len(notes_to_process)} notes for Word conversion...")
    no_overwrite = os.getenv('NOTES_EXPORT_NO_OVERWRITE', 'false').lower() == 'true'
    return run_for_notes('word', notes_to_process, lambda n: convert_note(tracker, n, no_overwrite))


if __name__ == "__main__":
    sys.exit(convert_html_to_docx())
