import os
from pathlib import Path
from markdownify import markdownify as md
from bs4 import BeautifulSoup
from notes_export_utils import get_tracker

def convert_html_to_md():
    """Convert HTML files to Markdown using JSON tracking"""
    tracker = get_tracker()
    
    # Get notes that need markdown conversion
    notes_to_process = tracker.get_notes_to_process('markdown')
    
    if not notes_to_process:
        print("No notes need markdown conversion - all up to date!")
        return
    
    print(f"Processing {len(notes_to_process)} notes for markdown conversion...")
    
    for note in notes_to_process:
        try:
            print(f"Converting: {note['filename']} from {note['notebook']}")

            # Read and convert HTML to Markdown
            with open(note['source_file'], "r", encoding="utf-8") as file:
                soup = BeautifulSoup(file, "html.parser")
                markdown_text = md(str(soup), heading_style="ATX")
            
            # Get output path
            output_file = tracker.get_output_path('md', note['notebook'], note['filename'], '.md')
            
            # Write Markdown content
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(markdown_text)
            
            print(f"Created: {output_file}")
            
            # Copy attachments if any
            tracker.copy_attachments(note['source_file'], output_file)
            
            # Mark as exported in JSON
            tracker.mark_note_exported(note['json_file'], note['note_id'], 'markdown')
            
        except Exception as e:
            print(f"Error converting {note['filename']}: {e}")

if __name__ == "__main__":
    convert_html_to_md()