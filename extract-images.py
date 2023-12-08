import os
import base64
from bs4 import BeautifulSoup
from pathlib import Path

def extract_and_replace_base64_images(html_folder_path, use_attachments_folder=False):
    html_folder = Path(html_folder_path)
    for html_file in html_folder.rglob("*.html"):
        # Directory where the HTML file is located
        html_file_dir = html_file.parent

        # Optional attachments directory
        attachments_dir = html_file_dir / 'attachments' if use_attachments_folder else html_file_dir

        # Read the file, convert to UTF-8 if necessary
        try:
            with open(html_file, "r", encoding="MacRoman") as file:
                html_content = file.read()
        except UnicodeDecodeError:
            with open(html_file, "r", encoding="utf-8") as file:
                html_content = file.read()

        soup = BeautifulSoup(html_content, "html.parser")

        img_ctr = 0
        for img_tag in soup.find_all("img"):
            img_src = img_tag.get("src")
            if img_src and img_src.startswith("data:image"):
                img_ctr += 1
                # Ensure attachments directory exists
                if use_attachments_folder and not attachments_dir.exists():
                    os.makedirs(attachments_dir)

                # Extract image format and data
                header, image_data = img_src.split(",", 1)
                img_format = header.split(";")[0].split("/")[1]

                # Decode and save the image
                image = base64.b64decode(image_data)
                img_filename = f"{html_file.stem}-attachment-{str(img_ctr).zfill(3)}.{img_format}"
                img_filepath = attachments_dir / img_filename
                with open(img_filepath, "wb") as img_file:
                    img_file.write(image)

                # Log the image writing
                print(f"Image written: {img_filepath.relative_to(Path(root_directory))}")

                # Update src attribute in HTML
                img_relative_path = os.path.join('./attachments' if use_attachments_folder else '.', img_filename)
                img_tag['src'] = img_relative_path

        # Save the modified HTML in UTF-8 as .htm file
        new_html_file = html_file.with_suffix('.htm')
        with open(new_html_file, "w", encoding="utf-8") as file:
            file.write(str(soup))

root_directory = os.getenv('NOTES_EXPORT_ROOT_DIR', './notes')
html_folder_path = os.path.join(root_directory, 'html')
extract_and_replace_base64_images(html_folder_path, use_attachments_folder=True)
