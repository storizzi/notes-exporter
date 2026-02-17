import subprocess
import os
import sys
import tempfile
import shutil
from pathlib import Path
from notes_export_utils import get_tracker

def create_continuous_html(source_file: Path) -> Path:
    """Create a modified HTML file that prevents page breaks for continuous PDF export.
    
    This is useful for handwritten notes that should not be split across pages.
    """
    # Read the original HTML
    with open(source_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # CSS to prevent page breaks and create a continuous page
    continuous_css = """
    <style>
        @page {
            size: auto;
            margin: 10mm;
        }
        @media print {
            body {
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            * {
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }
            html, body {
                height: auto !important;
                overflow: visible !important;
            }
            img {
                max-width: 100%;
                height: auto;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }
        }
        body {
            width: 100%;
            max-width: none;
        }
        img {
            max-width: 100%;
            height: auto;
        }
    </style>
    """
    
    # Insert the CSS into the HTML
    if '<head>' in html_content:
        html_content = html_content.replace('<head>', f'<head>{continuous_css}')
    elif '<html>' in html_content:
        html_content = html_content.replace('<html>', f'<html><head>{continuous_css}</head>')
    else:
        html_content = f'<html><head>{continuous_css}</head><body>{html_content}</body></html>'
    
    # Create a temporary file with the modified HTML
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        temp_file = Path(temp_dir) / source_file.name
        
        # Copy attachments folder if it exists
        source_attachments = source_file.parent / 'attachments'
        if source_attachments.exists():
            temp_attachments = Path(temp_dir) / 'attachments'
            shutil.copytree(source_attachments, temp_attachments)
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return temp_file
    except Exception:
        # Clean up temp directory on error to prevent leaks
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

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
    
    # Check settings
    suppress_header = os.getenv('NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF', 'false').lower() == 'true'
    continuous_pdf = os.getenv('NOTES_EXPORT_CONTINUOUS_PDF', 'false').lower() == 'true'
    
    print(f"Suppress header: {suppress_header}")
    print(f"Continuous PDF (no page breaks): {continuous_pdf}")
    
    temp_files_to_cleanup = []
    
    for note in notes_to_process:
        try:
            print(f"Converting: {note['filename']} from {note['notebook']}")
            
            # Get output path
            output_file = tracker.get_output_path('pdf', note['notebook'], note['filename'], '.pdf')
            
            # Determine source file (use modified HTML for continuous mode)
            source_file = note['source_file']
            if continuous_pdf:
                source_file = create_continuous_html(note['source_file'])
                temp_files_to_cleanup.append(source_file.parent)  # Track temp directory for cleanup
            
            # Prepare headless Chrome command
            cmd = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", 
                "--headless"
            ]
            
            if suppress_header:
                cmd.append("--no-pdf-header-footer")
            
            cmd.extend([
                "--print-to-pdf=" + str(output_file), 
                str(source_file)
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
    
    # Cleanup temporary files
    for temp_dir in temp_files_to_cleanup:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass  # Ignore cleanup errors

if __name__ == "__main__":
    convert_html_to_pdf()