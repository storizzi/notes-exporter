import os
from pathlib import Path
import pypandoc

def convert_html_to_docx(html_folder_path):
    root_directory = os.getenv('NOTES_EXPORT_ROOT_DIR', './notes')
    docx_folder_path = os.path.join(root_directory, 'docx')
    os.makedirs(docx_folder_path, exist_ok=True)
    print(f"Docx directory created at: {docx_folder_path}")

    html_folder = Path(html_folder_path)
    for html_file in html_folder.rglob("*.htm"):
        print(f"Processing file: {html_file}")

        # Determine new file paths
        relative_path = html_file.relative_to(html_folder)
        new_docx_file = Path(docx_folder_path) / relative_path.with_suffix('.docx')
        os.makedirs(new_docx_file.parent, exist_ok=True)

        try:
            # Store the current working directory
            original_cwd = os.getcwd()

            # Change the current working directory to the location of the HTML file
            os.chdir(html_file.parent)

            # Use pypandoc to convert HTML to DOCX and specify the input format
            pypandoc.convert_file(str(html_file), 'docx', format='html', outputfile=str(new_docx_file))
            
            print(f"Word document created: {new_docx_file}")

        except Exception as e:
            print(f"Error converting HTML to DOCX: {str(e)}")

        finally:
            # Reset the current working directory back to the original CWD
            os.chdir(original_cwd)

# Specify the HTML folder path
html_folder_path = os.path.join(os.getenv('NOTES_EXPORT_ROOT_DIR', './notes'), 'html')

# Call the function to convert HTML to DOCX
convert_html_to_docx(html_folder_path)
