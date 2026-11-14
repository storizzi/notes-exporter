"""Turn raw note HTML into processed HTML with images saved as files.

Raw HTML from Apple Notes carries images inline as base64 ``data:`` URIs.
Each one is written to ``attachments/`` (or beside the document with
--images-beside-docs) and the ``<img src>`` is pointed at the file.

Options (environment variables set by exportnotes.zsh):
    NOTES_EXPORT_IMAGES_BESIDE_DOCS   images next to the HTML file
    NOTES_EXPORT_HTML_WRAP            full HTML page with <title>
    NOTES_EXPORT_DEDUP_IMAGES         identical images stored once
    NOTES_EXPORT_IMAGE_FORMAT         convert images (jpeg, png, heic, tiff, webp) (#28)
    NOTES_EXPORT_IMAGE_FORMAT_FROM    only convert these source types (comma list)
    NOTES_EXPORT_IMAGE_QUALITY        1-100 for lossy targets
    NOTES_EXPORT_TAGS_IN_CONTENT      add a "Tags:" line from the note's tags (#16)
    NOTES_EXPORT_NO_OVERWRITE         keep existing processed HTML
"""

import base64
import hashlib
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup

from notes_export_utils import decode_note_bytes, get_tracker, run_for_notes


def _encode_src(relative_path: str) -> str:
    """Percent-encode an attachment reference so filenames containing spaces,
    parentheses, or other reserved characters produce a valid link once the
    HTML is converted to Markdown.

    Path separators are preserved. Without this, a filename such as
    ``note-)-attachment-001.png`` becomes ``![](./attachments/note-)-...)`` in
    Markdown, where the first ``)`` terminates the link early and the image
    fails to render.
    """
    return quote(relative_path, safe="/")


def _env_true(name: str) -> bool:
    return os.getenv(name, 'false').lower() == 'true'


def _should_skip_existing(output_path: Path) -> bool:
    """Check if we should skip writing because the file exists and no-overwrite is set."""
    if _env_true('NOTES_EXPORT_NO_OVERWRITE') and output_path.exists():
        print(f"Skipping (no-overwrite): {output_path}")
        return True
    return False


def _images_beside_docs() -> bool:
    return _env_true('NOTES_EXPORT_IMAGES_BESIDE_DOCS')


def _html_wrap_enabled() -> bool:
    return _env_true('NOTES_EXPORT_HTML_WRAP')


def _dedup_images_enabled() -> bool:
    return _env_true('NOTES_EXPORT_DEDUP_IMAGES')


def _wrap_html(html_content: str, title: str, tags=()) -> str:
    """Wrap HTML content with proper page structure."""
    keywords = ""
    if tags:
        keywords = f'\n<meta name="keywords" content="{html.escape(", ".join(tags), quote=True)}">'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>{keywords}
</head>
<body>
{html_content}
</body>
</html>"""


# ── image conversion (#28) ───────────────────────────────────────────────

# Normalised extension for a MIME subtype / file extension
_EXT_ALIASES = {"jpg": "jpeg", "jpe": "jpeg", "heif": "heic", "tif": "tiff"}
# sips type names
_SIPS_TYPES = {"jpeg": "jpeg", "png": "png", "heic": "heic", "tiff": "tiff", "gif": "gif"}
_OUTPUT_EXT = {"jpeg": "jpg", "png": "png", "heic": "heic", "tiff": "tiff", "webp": "webp"}


def normalise_format(name: str) -> str:
    name = (name or "").lower().strip().lstrip(".")
    if name.startswith("x-"):
        name = name[2:]
    return _EXT_ALIASES.get(name, name)


def conversion_target() -> Tuple[Optional[str], Optional[set], Optional[int]]:
    target = normalise_format(os.getenv('NOTES_EXPORT_IMAGE_FORMAT', ''))
    if not target:
        return None, None, None
    if target not in _OUTPUT_EXT:
        raise ValueError(f"unsupported --image-format '{target}' "
                         f"(use one of {', '.join(sorted(_OUTPUT_EXT))})")
    from_list = os.getenv('NOTES_EXPORT_IMAGE_FORMAT_FROM', '')
    sources = {normalise_format(s) for s in from_list.split(',') if s.strip()} or None
    quality = os.getenv('NOTES_EXPORT_IMAGE_QUALITY', '')
    return target, sources, int(quality) if quality.isdigit() else None


def should_convert(source_format: str, target: Optional[str], sources: Optional[set]) -> bool:
    source_format = normalise_format(source_format)
    if not target or source_format == target:
        return False
    if source_format in ("gif", "svg+xml", "svg"):
        return False  # animation / vector would be lost
    return sources is None or source_format in sources


def convert_image(data: bytes, source_format: str, target: str,
                  quality: Optional[int] = None) -> bytes:
    """Convert image bytes with macOS sips (or Pillow / cwebp for WebP)."""
    with tempfile.TemporaryDirectory(prefix="notes-img-") as tmp:
        src = Path(tmp) / f"in.{normalise_format(source_format)}"
        dst = Path(tmp) / f"out.{_OUTPUT_EXT[target]}"
        src.write_bytes(data)
        if target == "webp":
            _to_webp(src, dst, quality)
        else:
            if not shutil.which("sips"):
                raise RuntimeError("sips not found (image conversion needs macOS)")
            cmd = ["sips", "-s", "format", _SIPS_TYPES[target]]
            if quality and target in ("jpeg", "heic"):
                cmd += ["-s", "formatOptions", str(quality)]
            cmd += [str(src), "--out", str(dst)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 or not dst.exists():
                raise RuntimeError(f"sips failed: {result.stderr.strip() or result.stdout.strip()}")
        return dst.read_bytes()


def _to_webp(src: Path, dst: Path, quality: Optional[int]):
    """sips cannot write WebP; use Pillow if installed, else cwebp."""
    try:
        from PIL import Image  # optional dependency
        with Image.open(src) as im:
            im.save(dst, "WEBP", quality=quality or 80)
        return
    except ImportError:
        pass
    cwebp = shutil.which("cwebp")
    if not cwebp:
        raise RuntimeError("WebP output needs Pillow (pip install pillow) or cwebp (brew install webp)")
    png = src
    if normalise_format(src.suffix) not in ("png", "jpeg", "tiff"):
        png = src.with_suffix(".png")
        subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(png)],
                       check=True, capture_output=True)
    subprocess.run([cwebp, "-quiet", "-q", str(quality or 80), str(png), "-o", str(dst)],
                   check=True, capture_output=True)


# ── tags (#16) ───────────────────────────────────────────────────────────

def add_tags_line(soup: BeautifulSoup, tags) -> None:
    """Append a 'Tags: #a #b' paragraph (only with --tags-in-content)."""
    if not tags:
        return
    p = soup.new_tag("p")
    p["class"] = "note-tags"
    p.string = "Tags: " + " ".join(f"#{t}" for t in tags)
    soup.append(p)


# ── main ─────────────────────────────────────────────────────────────────

def process_note(tracker, note, settings, image_hash_registry) -> Optional[bool]:
    beside_docs, wrap_html, dedup, target, sources, quality, tags_in_content = settings
    print(f"Extracting images from: {note['filename']} from {note['notebook']}")

    root = Path(tracker.root_directory)
    if tracker._uses_subdirs():
        raw_file = root / 'raw' / note['notebook'] / f"{note['filename']}.html"
        html_file = root / 'html' / note['notebook'] / f"{note['filename']}.html"
    else:
        raw_file = root / 'raw' / f"{note['filename']}.html"
        html_file = root / 'html' / f"{note['filename']}.html"
    attachments_dir = html_file.parent if beside_docs else html_file.parent / 'attachments'

    if _should_skip_existing(html_file):
        return None
    html_file.parent.mkdir(parents=True, exist_ok=True)
    if not raw_file.exists():
        print(f"Warning: Raw file not found: {raw_file}")
        return False

    try:
        # UTF-8, any stray old Mac Roman bytes read as Mac Roman (never the whole file)
        html_content = decode_note_bytes(raw_file.read_bytes())
    except OSError as exc:
        print(f"Error: Could not read {raw_file}: {exc}")
        return False

    soup = BeautifulSoup(html_content, "html.parser")
    img_ctr = 0
    failed = False

    for img_tag in soup.find_all("img"):
        img_src = img_tag.get("src")
        if not (img_src and img_src.startswith("data:image")):
            continue
        img_ctr += 1
        try:
            header, image_data = img_src.split(",", 1)
            img_format = header.split(";")[0].split("/")[1]
            image = base64.b64decode(image_data)

            if should_convert(img_format, target, sources):
                try:
                    image = convert_image(image, img_format, target, quality)
                    img_format = _OUTPUT_EXT[target]
                except Exception as e:
                    print(f"  Could not convert image {img_ctr} to {target}, kept as {img_format}: {e}")
            ext = _OUTPUT_EXT.get(normalise_format(img_format), img_format.replace("+xml", ""))

            if dedup:
                img_hash = hashlib.sha256(image).hexdigest()
                if img_hash in image_hash_registry:
                    existing_path = image_hash_registry[img_hash]
                    try:
                        rel_path = os.path.relpath(existing_path, html_file.parent)
                    except ValueError:
                        rel_path = str(existing_path)
                    img_tag['src'] = _encode_src(rel_path)
                    print(f"  Dedup: reusing {existing_path.name}")
                    continue

            attachments_dir.mkdir(parents=True, exist_ok=True)
            img_filename = f"{note['filename']}-attachment-{str(img_ctr).zfill(3)}.{ext}"
            img_filepath = attachments_dir / img_filename
            img_filepath.write_bytes(image)
            if dedup:
                image_hash_registry[img_hash] = img_filepath
            print(f"Image written: {img_filepath.relative_to(root)}")

            rel_path = f"./{img_filename}" if beside_docs else f"./attachments/{img_filename}"
            img_tag['src'] = _encode_src(rel_path)
        except Exception as e:
            print(f"Error extracting image {img_ctr} from {raw_file}: {e}")
            failed = True

    tags = note['note_info'].get('tags') or []
    if tags_in_content:
        add_tags_line(soup, tags)

    final_html = str(soup)
    if wrap_html:
        title = note['note_info'].get('title') or note['filename'].replace('-', ' ')
        final_html = _wrap_html(final_html, title, tags)

    html_file.write_text(final_html, encoding="utf-8")
    print(f"Processed HTML saved ({img_ctr} images): {html_file}")
    tracker.mark_note_exported(note['json_file'], note['note_id'], 'images')
    return not failed


def extract_and_replace_base64_images() -> int:
    """Extract base64 images from raw HTML files. Returns an exit code."""
    tracker = get_tracker()
    notes_to_process = tracker.get_notes_to_process('images')
    if not notes_to_process:
        print("No notes need image extraction - all up to date!")
        return 0
    try:
        target, sources, quality = conversion_target()
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    print(f"Processing {len(notes_to_process)} notes for image extraction...")
    settings = (_images_beside_docs(), _html_wrap_enabled(), _dedup_images_enabled(),
                target, sources, quality, _env_true('NOTES_EXPORT_TAGS_IN_CONTENT'))
    registry = {}
    return run_for_notes('images', notes_to_process,
                         lambda n: process_note(tracker, n, settings, registry))


if __name__ == "__main__":
    sys.exit(extract_and_replace_base64_images())
