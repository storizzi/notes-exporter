import subprocess
import os
import sys
from pathlib import Path
from notes_export_utils import get_tracker

def convert_html_to_pdf():
    """Convert HTML files to PDF using JSON tracking"""
    tracker = get_tracker()
    
    # Check if root_directory is valid
    if not os.path.isabs(tracker.root_directory):
        print("Error: Root directory is not set or is a relative path.")
        sys.exit(1)
    
    # Get notes that need PDF conversion
    notes_to_process = tracker.get_notes_to_process('pdf')
    
    if not notes_to_process:
        print("No notes need PDF conversion - all up to date!")
        return
    
    print(f"Processing {len(notes_to_process)} notes for PDF conversion...")
    
    # Check suppress header setting
    suppress_header = os.getenv('NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF', 'false').lower() == 'true'
    print(f"Suppress header: {suppress_header}")
    
    for note in notes_to_process:
        try:
            print(f"Converting: {note['filename']} from {note['notebook']}")
            
            # Get output path
            output_file = tracker.get_output_path('pdf', note['notebook'], note['filename'], '.pdf')
            
            # Prepare headless Chrome command
            cmd = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", 
                "--headless"
            ]
            
            if suppress_header:
                cmd.append("--no-pdf-header-footer")
            
            cmd.extend([
                "--print-to-pdf=" + str(output_file), 
                str(note['source_file'])
            ])
            
            # Run headless Chrome command
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Created: {output_file}")
                
                # Mark as exported in JSON
                tracker.mark_note_exported(note['json_file'], note['note_id'], 'pdf')
            else:
                print(f"Error converting {note['filename']}: Chrome returned code {result.returncode}")
                if result.stderr:
                    print(f"Chrome error: {result.stderr}")
            
        except Exception as e:
            print(f"Error converting {note['filename']}: {e}")

if __name__ == "__main__":
    convert_html_to_pdf()