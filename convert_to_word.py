import os
from pathlib import Path
import pypandoc
from notes_export_utils import get_tracker

def convert_html_to_docx():
    """Convert HTML files to Word (DOCX) using JSON tracking"""
    tracker = get_tracker()
    
    # Get notes that need Word conversion
    notes_to_process = tracker.get_notes_to_process('word')
    
    if not notes_to_process:
        print("No notes need Word conversion - all up to date!")
        return
    
    print(f"Processing {len(notes_to_process)} notes for Word conversion...")
    
    for note in notes_to_process:
        try:
            print(f"Converting: {note['filename']} from {note['notebook']}")
            
            # Get output path
            output_file = tracker.get_output_path('docx', note['notebook'], note['filename'], '.docx')
            
            # Ensure source_file is a Path object
            source_file = Path(note['source_file'])
            
            # Read the HTML content first
            with open(source_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Store the current working directory
            original_cwd = os.getcwd()
            
            try:
                # Change to the source file directory for relative paths
                os.chdir(str(source_file.parent))
                
                # Use pypandoc to convert HTML text to DOCX
                pypandoc.convert_text(
                    html_content,
                    'docx', 
                    format='html', 
                    outputfile=str(output_file)
                )
                
                print(f"Created: {output_file}")
                
                # Mark as exported in JSON
                tracker.mark_note_exported(str(note['json_file']), note['note_id'], 'word')
                
            finally:
                # Always reset the current working directory
                os.chdir(original_cwd)
            
        except Exception as e:
            print(f"Error converting {note['filename']}: {e}")
            import traceback
            traceback.print_exc()
            # Ensure we're back in the original directory even if there's an error
            try:
                os.chdir(original_cwd)
            except:
                pass

if __name__ == "__main__":
    convert_html_to_docx()