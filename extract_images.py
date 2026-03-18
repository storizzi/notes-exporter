import os
import base64
import hashlib
from bs4 import BeautifulSoup
from pathlib import Path
from notes_export_utils import get_tracker


def _should_skip_existing(output_path: Path) -> bool:
    """Check if we should skip writing because the file exists and no-overwrite is set."""
    if os.getenv('NOTES_EXPORT_NO_OVERWRITE', 'false').lower() == 'true':
        if output_path.exists():
            print(f"Skipping (no-overwrite): {output_path}")
            return True
    return False


def _images_beside_docs() -> bool:
    """Check if images should be placed next to documents instead of in attachments/."""
    return os.getenv('NOTES_EXPORT_IMAGES_BESIDE_DOCS', 'false').lower() == 'true'


def _html_wrap_enabled() -> bool:
    """Check if HTML should be wrapped with proper page tags."""
    return os.getenv('NOTES_EXPORT_HTML_WRAP', 'false').lower() == 'true'


def _dedup_images_enabled() -> bool:
    """Check if image deduplication is enabled."""
    return os.getenv('NOTES_EXPORT_DEDUP_IMAGES', 'false').lower() == 'true'


def _wrap_html(html_content: str, title: str) -> str:
    """Wrap HTML content with proper page structure."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body>
{html_content}
</body>
</html>"""


def extract_and_replace_base64_images():
    """Extract base64 images from raw HTML files and create processed HTML files"""
    tracker = get_tracker()

    # Get notes that need image extraction
    notes_to_process = tracker.get_notes_to_process('images')

    if not notes_to_process:
        print("No notes need image extraction - all up to date!")
        return

    print(f"Processing {len(notes_to_process)} notes for image extraction...")

    # Set up directories
    raw_folder_path = os.path.join(tracker.root_directory, 'raw')
    html_folder_path = os.path.join(tracker.root_directory, 'html')

    beside_docs = _images_beside_docs()
    wrap_html = _html_wrap_enabled()
    dedup = _dedup_images_enabled()

    # Image hash registry for deduplication (hash -> filepath)
    image_hash_registry = {}

    for note in notes_to_process:
        try:
            print(f"Extracting images from: {note['filename']} from {note['notebook']}")

            # Build paths for raw and processed HTML files
            if tracker._uses_subdirs():
                raw_file = Path(raw_folder_path) / note['notebook'] / f"{note['filename']}.html"
                html_file = Path(html_folder_path) / note['notebook'] / f"{note['filename']}.html"
                if beside_docs:
                    attachments_dir = html_file.parent
                else:
                    attachments_dir = html_file.parent / 'attachments'
            else:
                raw_file = Path(raw_folder_path) / f"{note['filename']}.html"
                html_file = Path(html_folder_path) / f"{note['filename']}.html"
                if beside_docs:
                    attachments_dir = Path(html_folder_path)
                else:
                    attachments_dir = Path(html_folder_path) / 'attachments'

            # No-overwrite check
            if _should_skip_existing(html_file):
                continue

            # Ensure output directory exists
            html_file.parent.mkdir(parents=True, exist_ok=True)

            # Check if raw file exists
            if not raw_file.exists():
                print(f"Warning: Raw file not found: {raw_file}")
                continue

            # Read the raw HTML file, try different encodings
            html_content = None
            for encoding in ['utf-8', 'MacRoman', 'latin-1']:
                try:
                    with open(raw_file, "r", encoding=encoding) as file:
                        html_content = file.read()
                    break
                except UnicodeDecodeError:
                    continue

            if html_content is None:
                print(f"Error: Could not read {raw_file} with any encoding")
                continue

            soup = BeautifulSoup(html_content, "html.parser")
            img_ctr = 0
            images_extracted = False

            for img_tag in soup.find_all("img"):
                img_src = img_tag.get("src")
                if img_src and img_src.startswith("data:image"):
                    img_ctr += 1

                    # Extract image format and data
                    try:
                        header, image_data = img_src.split(",", 1)
                        img_format = header.split(";")[0].split("/")[1]

                        # Decode the image
                        image = base64.b64decode(image_data)

                        # Deduplication check
                        if dedup:
                            img_hash = hashlib.sha256(image).hexdigest()
                            if img_hash in image_hash_registry:
                                # Reuse existing image
                                existing_path = image_hash_registry[img_hash]
                                try:
                                    img_relative_path = os.path.relpath(existing_path, html_file.parent)
                                except ValueError:
                                    img_relative_path = str(existing_path)
                                img_tag['src'] = img_relative_path
                                images_extracted = True
                                print(f"  Dedup: reusing {existing_path.name}")
                                continue

                        # Ensure output directory exists
                        if not attachments_dir.exists():
                            os.makedirs(attachments_dir)

                        # Save the image
                        img_filename = f"{note['filename']}-attachment-{str(img_ctr).zfill(3)}.{img_format}"
                        img_filepath = attachments_dir / img_filename

                        with open(img_filepath, "wb") as img_file:
                            img_file.write(image)

                        # Register for dedup
                        if dedup:
                            image_hash_registry[img_hash] = img_filepath

                        # Log the image writing (relative to root directory)
                        relative_path = img_filepath.relative_to(Path(tracker.root_directory))
                        print(f"Image written: {relative_path}")

                        # Update src attribute in HTML to point to extracted image
                        if beside_docs:
                            img_relative_path = f"./{img_filename}"
                        else:
                            img_relative_path = f"./attachments/{img_filename}"
                        img_tag['src'] = img_relative_path

                        images_extracted = True

                    except Exception as e:
                        print(f"Error extracting image {img_ctr} from {raw_file}: {e}")
                        continue

            # Build final HTML content
            final_html = str(soup)

            # Optionally wrap with proper HTML page tags
            if wrap_html:
                # Use the note filename as the title (convert dashes to spaces)
                title = note['filename'].replace('-', ' ')
                final_html = _wrap_html(final_html, title)

            # Save the processed HTML file
            with open(html_file, "w", encoding="utf-8") as file:
                file.write(final_html)

            if images_extracted:
                print(f"Processed HTML with extracted images saved: {html_file}")
            else:
                print(f"Processed HTML saved (no images found): {html_file}")

            # Mark as exported in JSON
            tracker.mark_note_exported(note['json_file'], note['note_id'], 'images')

        except Exception as e:
            print(f"Error processing {note['filename']}: {e}")

if __name__ == "__main__":
    extract_and_replace_base64_images()
