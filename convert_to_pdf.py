import subprocess
import os
import re
import sys
import tempfile
import shutil
from pathlib import Path
from notes_export_utils import get_tracker
from datetime import datetime

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

        # Set creation date (birth time) using SetFile from Xcode tools
        create_timestamp = creation_date.strftime("%Y%m%d%H%M.%S")

        # Try using SetFile first (more reliable for creation date on macOS)
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


def add_pdf_css_to_html(source_file: Path, continuous: bool = True, title: str = None) -> Path:
    """Create a modified HTML file with improved CSS for PDF export.
    
    Args:
        source_file: Path to the source HTML file
        continuous: If True, prevents page breaks (for handwritten notes)
        title: Optional title to add as a header in the PDF
    
    Returns:
        Path to the temporary HTML file with added CSS
    """
    # Read the original HTML
    with open(source_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Base CSS for all PDFs - fixes text cutoff issues
    base_css = """
        @page {
            size: auto;
            margin: 10mm;
        }
        @media print {
            body {
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }
            html, body {
                height: auto !important;
                overflow: visible !important;
            }
            img {
                max-width: 100% !important;
                height: auto !important;
            }
            pre, code {
                white-space: pre-wrap !important;
                word-wrap: break-word !important;
                overflow-wrap: break-word !important;
            }
            * {
                word-wrap: break-word !important;
                overflow-wrap: break-word !important;
            }
        }
        body {
            width: 100%;
            max-width: none;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }
        img {
            max-width: 100%;
            height: auto;
        }
        pre, code {
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
        }
    """
    
    # Additional CSS for continuous mode (prevents page breaks)
    continuous_css = """
            * {
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }
            img {
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }
    """
    
    # Combine CSS based on mode
    if continuous:
        full_css = f"<style>{base_css}{continuous_css}</style>"
    else:
        full_css = f"<style>{base_css}</style>"
    
    # Add title header CSS
    title_css = """
        <style>
            .pdf-note-title {
                font-size: 1.5em;
                font-weight: bold;
                margin-bottom: 0.5em;
                padding-bottom: 0.5em;
                border-bottom: 1px solid #ccc;
            }
        </style>
    """
    
    # Add title header HTML if title is provided
    title_html = ""
    if title:
        title_html = f'<div class="pdf-note-title">{title}</div>'
    
    # Insert the CSS into the HTML
    if '<head>' in html_content:
        html_content = html_content.replace('<head>', f'<head>{full_css}{title_css if title else ""}')
    elif '<html>' in html_content:
        html_content = html_content.replace('<html>', f'<html><head>{full_css}{title_css if title else ""}</head>')
    else:
        html_content = f'<html><head>{full_css}{title_css if title else ""}</head><body>{html_content}</body></html>'
    
    # Insert title at the beginning of body if provided
    if title:
        if '<body>' in html_content:
            html_content = html_content.replace('<body>', f'<body>{title_html}')
        elif '</head>' in html_content:
            html_content = html_content.replace('</head>', f'</head><body>{title_html}')
        else:
            # Already wrapped in basic HTML structure above
            html_content = html_content.replace('<body>', f'<body>{title_html}')
    
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
            
            # Always use CSS-enhanced HTML (fixes text cutoff in all modes)
            # Note: note['filename'] is the sanitized note title used for the filename
            source_file = add_pdf_css_to_html(note['source_file'], continuous=continuous_pdf, title=note['filename'])
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
                
                # Set file dates to match the original note dates
                created_str = note['note_info'].get('created')
                modified_str = note['note_info'].get('modified')
                
                if created_str and modified_str:
                    created_date = parse_apple_date(created_str)
                    modified_date = parse_apple_date(modified_str)
                    
                    if created_date and modified_date:
                        if set_file_dates(str(output_file), created_date, modified_date):
                            print(f"Set dates: created={created_str}, modified={modified_str}")
                    else:
                        print(f"Warning: Could not parse dates for {note['filename']}")
                
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