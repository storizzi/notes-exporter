import subprocess
import os
from pathlib import Path

def convert_html_to_pdf_chromium(html_folder_path):

    root_directory = os.getenv('NOTES_EXPORT_ROOT_DIR')
    suppress_header = os.getenv('SUPPRESS_CHROME_HEADER_PDF', 'false').lower() == 'true'
    print(f"Suppress header: {suppress_header}")

    # Check if root_directory is None or a relative path
    if root_directory is None or not os.path.isabs(root_directory):
        print("Error: Root directory is not set or is a relative path.")
        sys.exit(1)

    print(f"Root directory: {root_directory}")
    pdf_folder_path = os.path.join(root_directory, 'pdf')
    os.makedirs(pdf_folder_path, exist_ok=True)

    html_folder = Path(html_folder_path)
    for html_file in html_folder.rglob("*.htm"):
        print(f"Processing file: {html_file}")

        # Determine new file path
        relative_path = html_file.relative_to(html_folder)
        new_pdf_file = Path(pdf_folder_path) / relative_path.with_suffix('.pdf')

        # Ensure the directory for the new PDF file exists
        os.makedirs(new_pdf_file.parent, exist_ok=True) 

        # Prepare headless Chrome command
        cmd = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", 
            "--headless", 
        #    "--disable-gpu"
        ]
        if suppress_header:
            cmd.append("--no-pdf-header-footer")
        cmd.extend(["--print-to-pdf=" + str(new_pdf_file), str(html_file)])

        # Run headless Chrome command
        subprocess.run(cmd)

        print(f"PDF created: {new_pdf_file}")

html_folder_path = os.path.join(os.getenv('NOTES_EXPORT_ROOT_DIR', './notes'), 'html')
convert_html_to_pdf_chromium(html_folder_path)