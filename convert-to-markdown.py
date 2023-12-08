import os
import shutil
from pathlib import Path
from markdownify import markdownify as md
from bs4 import BeautifulSoup

def convert_html_to_md(html_folder_path):
    root_directory = os.getenv('NOTES_EXPORT_ROOT_DIR', './notes')
    md_folder_path = os.path.join(root_directory, 'md')
    os.makedirs(md_folder_path, exist_ok=True)
    print(f"Markdown directory created at: {md_folder_path}")

    html_folder = Path(html_folder_path)
    for html_file in html_folder.rglob("*.htm"):
        print(f"Processing file: {html_file}")
        # Convert HTML to Markdown
        with open(html_file, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file, "html.parser")
            markdown_text = md(str(soup), heading_style="ATX")

        # Determine new file paths
        relative_path = html_file.relative_to(html_folder)
        new_md_file = Path(md_folder_path) / relative_path.with_suffix('.md')
        os.makedirs(new_md_file.parent, exist_ok=True)

        # Write Markdown content to new file
        with open(new_md_file, "w", encoding="utf-8") as file:
            file.write(markdown_text)

        # Copy attachments if any
        attachments_folder = html_file.parent / 'attachments'
        if attachments_folder.exists():
            new_attachments_folder = new_md_file.parent / 'attachments'
            shutil.copytree(attachments_folder, new_attachments_folder, dirs_exist_ok=True)
            print(f"Copied attachments from {attachments_folder} to {new_attachments_folder}")

html_folder_path = os.path.join(os.getenv('NOTES_EXPORT_ROOT_DIR', './notes'), 'html')
convert_html_to_md(html_folder_path)
