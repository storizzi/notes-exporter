import os
import shutil
from pathlib import Path
from markdownify import markdownify as md
from bs4 import BeautifulSoup
from notes_export_utils import get_tracker


def copy_note_sidecars(tracker, note, output_file: Path):
    """Place source HTML and text beside Markdown in note-folder mode."""
    if not tracker._uses_note_folders():
        return

    filename = note['filename']
    sidecar_dir = output_file.parent

    html_target = sidecar_dir / f"{filename}.html"
    shutil.copy2(note['source_file'], html_target)

    text_source = Path(tracker.root_directory) / 'text'
    if tracker._uses_subdirs():
        text_source = text_source / note['notebook']
    text_source = text_source / f"{filename}.txt"

    if text_source.exists():
        shutil.copy2(text_source, sidecar_dir / f"{filename}.txt")

def convert_html_to_md():
    """Convert HTML files to Markdown using JSON tracking"""
    tracker = get_tracker()
    
    # Get notes that need markdown conversion
    notes_to_process = tracker.get_notes_to_process('markdown')
    
    if not notes_to_process:
        print("No notes need markdown conversion - all up to date!")
        return
    
    print(f"Processing {len(notes_to_process)} notes for markdown conversion...")
    
    no_overwrite = os.getenv('NOTES_EXPORT_NO_OVERWRITE', 'false').lower() == 'true'

    for note in notes_to_process:
        try:
            print(f"Converting: {note['filename']} from {note['notebook']}")

            # Get output path (check early for no-overwrite)
            output_file = tracker.get_output_path('md', note['notebook'], note['filename'], '.md')
            if no_overwrite and output_file.exists():
                print(f"Skipping (no-overwrite): {output_file}")
                continue

            # Read and convert HTML to Markdown
            with open(note['source_file'], "r", encoding="utf-8") as file:
                soup = BeautifulSoup(file, "html.parser")
                if tracker._uses_note_folders():
                    for tag in soup.find_all(["img", "a"]):
                        attr = "src" if tag.name == "img" else "href"
                        value = tag.get(attr)
                        if value and value.startswith("./attachments/"):
                            tag[attr] = "./" + value[len("./attachments/"):]
                markdown_text = md(str(soup), heading_style="ATX")
                if tracker._uses_note_folders():
                    markdown_text = markdown_text.replace("](./attachments/", "](./")
                    markdown_text = markdown_text.replace("](attachments/", "](./")
            
            # Write Markdown content
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(markdown_text)
            
            print(f"Created: {output_file}")

            # Keep the note bundle together in note-folder mode.
            copy_note_sidecars(tracker, note, output_file)
            
            # Copy attachments if any
            tracker.copy_attachments(note['source_file'], output_file)
            
            # Mark as exported in JSON
            tracker.mark_note_exported(note['json_file'], note['note_id'], 'markdown')
            
        except Exception as e:
            print(f"Error converting {note['filename']}: {e}")

if __name__ == "__main__":
    convert_html_to_md()
