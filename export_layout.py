"""Where a tracked note's files live in an export (shared by prune and manifest)."""

import os
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from tracker_io import read_json, tracker_files

# format key -> (directory, extension). Keys are the manifest's format names.
FORMATS: Dict[str, Tuple[str, str]] = {
    "raw": ("raw", ".html"),
    "html": ("html", ".html"),
    "text": ("text", ".txt"),
    "md": ("md", ".md"),
    "pdf": ("pdf", ".pdf"),
    "docx": ("docx", ".docx"),
}

# Format directories that may hold extracted attachments.
ATTACHMENT_FORMATS = ("html", "md", "pdf", "docx")


def uses_subdirs() -> bool:
    return os.getenv("NOTES_EXPORT_USE_SUBDIRS", "true").lower() == "true"


def record_subdir(tracker_stem: str, rec: dict) -> str:
    if isinstance(rec.get("subdir"), str):
        return rec["subdir"]
    return tracker_stem


def note_dir(root: Path, fmt: str, tracker_stem: str, rec: dict) -> Path:
    base = root / FORMATS[fmt][0]
    if not uses_subdirs():
        return base
    sub = record_subdir(tracker_stem, rec)
    return base / sub if sub else base


def output_paths(root: Path, tracker_stem: str, rec: dict) -> Dict[str, Path]:
    filename = rec.get("filename", "")
    if not filename:
        return {}
    return {fmt: note_dir(root, fmt, tracker_stem, rec) / f"{filename}{ext}"
            for fmt, (_, ext) in FORMATS.items()}


def attachment_files(root: Path, tracker_stem: str, rec: dict) -> List[Path]:
    """Extracted attachment files named after the note (all formats)."""
    filename = rec.get("filename", "")
    if not filename:
        return []
    found = []
    prefix = f"{filename}-attachment-"
    for fmt in ATTACHMENT_FORMATS:
        folder = note_dir(root, fmt, tracker_stem, rec)
        for directory in (folder / "attachments", folder):
            if directory.is_dir():
                found.extend(p for p in directory.iterdir()
                             if p.is_file() and p.name.startswith(prefix))
    return sorted(found)


def iter_trackers(root: Path) -> Iterator[Tuple[Path, dict]]:
    data_dir = root / "data"
    if not data_dir.is_dir():
        return
    for json_file in tracker_files(data_dir):
        data = read_json(json_file)
        if data:
            yield json_file, data


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
