#!/usr/bin/env python3
"""EPUB 3 packaging shared by convert_to_epub.py (one book per note) and
build_epub_books.py (one book per Notes folder).

Written with the standard library's zipfile (no ebooklib, which is AGPL):

* ``mimetype`` first, stored (not compressed), no extra fields;
* ``META-INF/container.xml`` -> ``OEBPS/content.opf``;
* ``nav.xhtml`` (EPUB 3) and ``toc.ncx`` (for older readers);
* each chapter is well-formed XHTML made from a note's HTML output, with
  every local image it references packaged under ``images/`` (named by
  content hash, so a picture used twice is stored once).

The output is deterministic: the same notes give byte-identical files (zip
timestamps come from the notes' dates, entries are written in a fixed order),
so an unchanged note keeps its sha256 and a re-run rewrites nothing.
"""

import base64
import hashlib
import io
import mimetypes
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

XHTML_NS = "http://www.w3.org/1999/xhtml"
CORE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/svg+xml", "image/webp"}
CONVERTIBLE = {".heic", ".heif", ".tif", ".tiff", ".bmp"}
STYLESHEET = """body { font-family: serif; line-height: 1.45; margin: 0 4%; }
h1.note-title { font-size: 1.4em; margin: 1em 0 0.6em; }
img { max-width: 100%; height: auto; }
table { border-collapse: collapse; }
td, th { border: 1px solid #999; padding: 0.2em 0.4em; }
pre, code { font-family: monospace; white-space: pre-wrap; }
"""

# Obsolete HTML elements AppleScript's note HTML uses, and their HTML5 stand-ins.
RENAME_TAGS = {"font": "span", "strike": "s", "tt": "code", "center": "div", "big": "span", "blink": "span"}
DROP_TAGS = {"script", "noscript", "iframe", "object", "embed", "applet", "form", "input", "button", "select",
             "textarea", "meta", "link", "base", "title", "head", "style"}
DROP_ATTRS = {"align", "bgcolor", "border", "face", "size", "color", "valign", "clear", "nowrap",
              "cellpadding", "cellspacing", "background", "hspace", "vspace", "frame", "rules", "char",
              "charoff", "contenteditable"}
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_ATTR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass
class Image:
    href: str          # path inside OEBPS
    media_type: str
    data: bytes


@dataclass
class Chapter:
    id: str
    title: str
    body: str          # XHTML body content (well-formed)
    href: str = ""


@dataclass
class NavNode:
    """A table-of-contents entry: a chapter, or a heading with children (a part)."""
    title: str
    chapter: Optional[Chapter] = None
    children: List["NavNode"] = field(default_factory=list)

    def first_href(self) -> Optional[str]:
        if self.chapter:
            return self.chapter.href
        for c in self.children:
            h = c.first_href()
            if h:
                return h
        return None


@dataclass
class BookMeta:
    identifier: str
    title: str
    language: str = "und"
    modified: Optional[str] = None     # ISO 8601
    created: Optional[str] = None
    subjects: List[str] = field(default_factory=list)
    creator: Optional[str] = None


def identifier_urn(kind: str, value: str) -> str:
    """dc:identifier as a URN: urn:x-apple-notes:<percent-encoded id>."""
    return f"urn:x-apple-notes{('-' + kind) if kind else ''}:{quote(value, safe='')}"


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── HTML -> XHTML ─────────────────────────────────────────────────────────

class ImageStore:
    """Images packaged in a book, de-duplicated by sha256."""

    def __init__(self, convert: bool = True):
        self.by_hash: Dict[str, Image] = {}
        self.convert = convert

    def add(self, data: bytes, name: str, media_type: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """Package an image; returns (href inside OEBPS, warning)."""
        ext = Path(name).suffix.lower()
        media_type = media_type or mimetypes.guess_type("x" + ext)[0] or ""
        if ext == ".webp":
            media_type = "image/webp"
        warning = None
        if media_type not in CORE_IMAGE_TYPES:
            converted = _to_jpeg(data, ext) if self.convert else None
            if converted:
                data, ext, media_type = converted, ".jpg", "image/jpeg"
            else:
                return None, f"image {name} is {media_type or 'an unknown type'} (not an EPUB image type) and could not be converted; left out"
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            ext = mimetypes.guess_extension(media_type) or ".img"
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.by_hash:
            self.by_hash[digest] = Image(f"images/{digest[:20]}{'.jpg' if ext == '.jpeg' else ext}", media_type, data)
        return self.by_hash[digest].href, warning

    def images(self) -> List[Image]:
        return sorted(self.by_hash.values(), key=lambda i: i.href)


def _to_jpeg(data: bytes, ext: str) -> Optional[bytes]:
    if ext not in CONVERTIBLE:
        return None
    try:
        from PIL import Image as PILImage  # optional
        with PILImage.open(io.BytesIO(data)) as im:
            out = io.BytesIO()
            im.convert("RGB").save(out, "JPEG", quality=88)
            return out.getvalue()
    except Exception:
        pass
    sips = shutil.which("sips")
    if not sips:
        return None
    with tempfile.TemporaryDirectory(prefix="notes-epub-") as tmp:
        src, dst = Path(tmp) / ("in" + ext), Path(tmp) / "out.jpg"
        src.write_bytes(data)
        try:
            subprocess.run([sips, "-s", "format", "jpeg", str(src), "--out", str(dst)],
                           capture_output=True, timeout=60, check=True)
            return dst.read_bytes()
        except (OSError, subprocess.SubprocessError):
            return None


def _clean_text(s: str) -> str:
    return _XML_INVALID.sub("", s)


def html_to_xhtml(html: str, base_dir: Path, images: ImageStore,
                  warn: Callable[[str], None] = lambda m: None) -> str:
    """The body of a note's HTML as well-formed XHTML, images packaged.

    ``base_dir`` is the folder of the HTML file (relative image links resolve
    from it). Missing images are dropped with a warning.
    """
    from bs4 import BeautifulSoup, Comment, Doctype, ProcessingInstruction

    soup = BeautifulSoup(_clean_text(html), "html.parser")
    for node in soup.find_all(string=lambda s: isinstance(s, (Comment, Doctype, ProcessingInstruction))):
        node.extract()
    body = soup.body or soup
    for tag in list(body.find_all(True)):
        if getattr(tag, "decomposed", False):
            continue
        name = (tag.name or "").lower()
        if ":" in name or name in DROP_TAGS:
            tag.decompose()
            continue
        if name in ("html", "body"):
            tag.unwrap()
            continue
        style = []
        if name == "font":
            if tag.get("color"):
                style.append(f"color: {tag['color']}")
            if tag.get("face"):
                style.append(f"font-family: {tag['face']}")
        if name in RENAME_TAGS:
            tag.name = RENAME_TAGS[name]
            if name == "center":
                style.append("text-align: center")
        for attr in list(tag.attrs):
            a = attr.lower()
            if a.startswith("on") or a in DROP_ATTRS or not _ATTR_NAME.match(attr) or ":" in attr:
                del tag.attrs[attr]
            elif isinstance(tag.attrs[attr], list):
                tag.attrs[attr] = " ".join(tag.attrs[attr])
        if style:
            tag["style"] = "; ".join(filter(None, [tag.get("style", "").strip("; ")] + style))
        if tag.name == "img":
            _package_img(tag, base_dir, images, warn)
        elif tag.name == "a":
            href = (tag.get("href") or "").strip()
            scheme = urlparse(href).scheme.lower()
            if not href or href.startswith("#") or scheme in ("http", "https", "mailto"):
                pass
            else:
                del tag["href"]  # a local file or javascript: has no target inside the book
    xhtml = body.decode_contents(formatter="minimal") if hasattr(body, "decode_contents") else str(body)
    try:
        ElementTree.fromstring(f'<div xmlns="{XHTML_NS}">{xhtml}</div>')
    except ElementTree.ParseError:
        warn("the note's HTML could not be made well-formed; using its text")
        text = _clean_text(body.get_text("\n"))
        xhtml = "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())
    return xhtml


def _package_img(tag, base_dir: Path, images: ImageStore, warn) -> None:
    src = (tag.get("src") or "").strip()
    alt = tag.get("alt") or ""
    if src.startswith("data:"):
        m = re.match(r"data:([^;,]+)?(;base64)?,(.*)$", src, re.S)
        if not m:
            warn("an inline image could not be read; left out")
            tag.decompose()
            return
        mt = (m.group(1) or "application/octet-stream").lower()
        try:
            data = base64.b64decode(m.group(3)) if m.group(2) else unquote(m.group(3)).encode()
        except ValueError:
            warn("an inline image could not be decoded; left out")
            tag.decompose()
            return
        name = "inline" + (mimetypes.guess_extension(mt) or "")
        if mt == "image/heic":
            name = "inline.heic"
        href, w = images.add(data, name, mt)
    else:
        scheme = urlparse(src).scheme.lower()
        if not src or scheme:
            warn(f"image {src[:80] or '(no source)'} is not a local file; left out")
            tag.decompose()
            return
        path = (base_dir / unquote(src.split("#")[0].split("?")[0]))
        if not path.is_file():
            warn(f"image {unquote(src)} is missing; left out")
            tag.decompose()
            return
        href, w = images.add(path.read_bytes(), path.name)
    if w:
        warn(w)
    if not href:
        tag.decompose()
        return
    tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("width", "height", "style", "class", "title")}
    tag["src"] = href
    tag["alt"] = alt


# ── documents ─────────────────────────────────────────────────────────────

def chapter_document(chapter: Chapter, language: str, heading: bool = True) -> str:
    h = f'<h1 class="note-title">{escape(chapter.title)}</h1>\n' if heading else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{XHTML_NS}" xmlns:epub="http://www.idpf.org/2007/ops" lang={quoteattr(language)} '
            f'xml:lang={quoteattr(language)}>\n<head>\n<meta charset="UTF-8"/>\n'
            f'<title>{escape(chapter.title)}</title>\n'
            '<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n'
            f'<body>\n{h}{chapter.body}\n</body>\n</html>\n')


def _nav_list(nodes: List[NavNode]) -> str:
    items = []
    for n in nodes:
        if n.chapter:
            inner = f'<a href={quoteattr(n.chapter.href)}>{escape(n.title)}</a>'
        else:
            inner = f"<span>{escape(n.title)}</span>"
        if n.children:
            inner += "\n" + _nav_list(n.children)
        items.append(f"<li>{inner}</li>")
    return "<ol>\n" + "\n".join(items) + "\n</ol>"


def nav_document(title: str, nodes: List[NavNode], language: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{XHTML_NS}" xmlns:epub="http://www.idpf.org/2007/ops" lang={quoteattr(language)} '
            f'xml:lang={quoteattr(language)}>\n<head>\n<meta charset="UTF-8"/>\n<title>{escape(title)}</title>\n'
            '</head>\n<body>\n<nav epub:type="toc" id="toc">\n'
            f'<h1>{escape(title)}</h1>\n{_nav_list(nodes)}\n</nav>\n</body>\n</html>\n')


def ncx_document(meta: BookMeta, nodes: List[NavNode]) -> str:
    counter = [0]

    def points(ns: List[NavNode], depth: int) -> Tuple[str, int]:
        out, maxd = [], depth
        for n in ns:
            href = n.first_href()
            if not href:
                continue
            counter[0] += 1
            i = counter[0]
            inner, d = points(n.children, depth + 1) if n.children else ("", depth)
            maxd = max(maxd, d)
            out.append(f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{escape(n.title)}</text></navLabel>'
                       f'<content src={quoteattr(href)}/>{inner}</navPoint>')
        return "\n".join(out), maxd

    body, depth = points(nodes, 1)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n<head>\n'
            f'<meta name="dtb:uid" content={quoteattr(meta.identifier)}/>\n'
            f'<meta name="dtb:depth" content="{depth}"/>\n'
            '<meta name="dtb:totalPageCount" content="0"/>\n<meta name="dtb:maxPageNumber" content="0"/>\n'
            f'</head>\n<docTitle><text>{escape(meta.title)}</text></docTitle>\n<navMap>\n{body}\n</navMap>\n</ncx>\n')


def opf_document(meta: BookMeta, chapters: List[Chapter], images: List[Image]) -> str:
    modified = _parse_date(meta.modified) or datetime(2000, 1, 1, tzinfo=timezone.utc)
    md = [f'<dc:identifier id="bookid">{escape(meta.identifier)}</dc:identifier>',
          f"<dc:title>{escape(meta.title)}</dc:title>",
          f"<dc:language>{escape(meta.language or 'und')}</dc:language>",
          f"<dc:date>{_utc(modified)}</dc:date>",
          f'<meta property="dcterms:modified">{_utc(modified)}</meta>']
    created = _parse_date(meta.created)
    if created:
        md.append(f'<meta property="dcterms:created">{_utc(created)}</meta>')
    if meta.creator:
        md.append(f"<dc:creator>{escape(meta.creator)}</dc:creator>")
    for s in meta.subjects:
        if s:
            md.append(f"<dc:subject>{escape(s)}</dc:subject>")
    items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
             '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
             '<item id="css" href="style.css" media-type="text/css"/>']
    for c in chapters:
        items.append(f'<item id={quoteattr(c.id)} href={quoteattr(c.href)} media-type="application/xhtml+xml"/>')
    for n, img in enumerate(images, 1):
        items.append(f'<item id="img{n}" href={quoteattr(img.href)} media-type={quoteattr(img.media_type)}/>')
    spine = "\n".join(f'<itemref idref={quoteattr(c.id)}/>' for c in chapters)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" '
            f'xml:lang={quoteattr(meta.language or "und")}>\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n' + "\n".join(md) + "\n</metadata>\n"
            "<manifest>\n" + "\n".join(items) + "\n</manifest>\n"
            f'<spine toc="ncx">\n{spine}\n</spine>\n</package>\n')


CONTAINER = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
             '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
             '</rootfiles>\n</container>\n')


def build_epub(meta: BookMeta, chapters: List[Chapter], images: ImageStore,
               nav: Optional[List[NavNode]] = None, headings: bool = True) -> bytes:
    """The EPUB file's bytes."""
    for n, c in enumerate(chapters, 1):
        if not c.href:
            c.href = f"chapter-{n:04d}.xhtml"
    nav = nav if nav is not None else [NavNode(c.title, c) for c in chapters]
    when = _parse_date(meta.modified) or datetime(2000, 1, 1, tzinfo=timezone.utc)
    stamp = max((when.year, when.month, when.day, when.hour, when.minute, when.second), (1980, 1, 1, 0, 0, 0))
    entries = [("META-INF/container.xml", CONTAINER.encode()),
               ("OEBPS/content.opf", opf_document(meta, chapters, images.images()).encode()),
               ("OEBPS/nav.xhtml", nav_document(meta.title, nav, meta.language).encode()),
               ("OEBPS/toc.ncx", ncx_document(meta, nav).encode()),
               ("OEBPS/style.css", STYLESHEET.encode())]
    entries += [(f"OEBPS/{c.href}", chapter_document(c, meta.language, headings).encode()) for c in chapters]
    entries += [(f"OEBPS/{img.href}", img.data) for img in images.images()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("mimetype", date_time=stamp)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        z.writestr(info, b"application/epub+zip")
        for name, data in entries:
            zi = zipfile.ZipInfo(name, date_time=stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data, compresslevel=9)
    return buf.getvalue()


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write atomically, only when the bytes differ. Returns True if written."""
    try:
        if path.is_file() and path.stat().st_size == len(data) and path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".epub-", suffix=".tmp")
    with open(fd, "wb") as f:
        f.write(data)
    Path(tmp).replace(path)
    return True
