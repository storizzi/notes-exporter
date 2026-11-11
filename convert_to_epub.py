#!/usr/bin/env python3
"""Convert each note's HTML output to an EPUB 3 book (epub/ folder).

One book per note, built from html/<folder>/<note>.html with its images
packaged inside (see epub_builder.py). Incremental like the other formats:
only notes whose export changed since their last EPUB are converted
(``lastExportedToEpub`` in the tracking data).

Environment: NOTES_EXPORT_EPUB_LANGUAGE (a BCP 47 tag; default "und",
unknown), NOTES_EXPORT_NO_OVERWRITE.
"""

import os
import sys
from pathlib import Path

import events
from epub_builder import BookMeta, Chapter, ImageStore, build_epub, html_to_xhtml, identifier_urn, write_if_changed
from notes_export_utils import get_tracker, run_for_notes


def note_meta(note: dict) -> BookMeta:
    info = note["note_info"]
    title = info.get("title") or note["filename"].replace("-", " ")
    full_id = info.get("fullNoteId") or f"legacy:{note['tracker']}/{note['note_id']}"
    subjects = [info.get("account") or ""]
    if info.get("folderPath"):
        subjects.append("/".join(info["folderPath"]))
    return BookMeta(identifier=identifier_urn("", full_id), title=title,
                    language=os.getenv("NOTES_EXPORT_EPUB_LANGUAGE", "") or "und",
                    modified=info.get("modifiedAt"), created=info.get("createdAt"),
                    subjects=[s for s in subjects if s])


def note_epub_bytes(source: Path, meta: BookMeta, stage: str = "epub", note_id=None) -> bytes:
    def warn(msg):
        print(f"Warning ({source.name}): {msg}")
        events.emit("message", level="warning", stage=stage, note_id=note_id, message=f"{source.name}: {msg}")
    images = ImageStore()
    body = html_to_xhtml(source.read_text(encoding="utf-8", errors="replace"), source.parent, images, warn)
    return build_epub(meta, [Chapter("note", meta.title, body, "note.xhtml")], images)


def convert_note(tracker, note, no_overwrite: bool):
    output_file = tracker.get_output_path("epub", note["notebook"], note["filename"], ".epub")
    if no_overwrite and output_file.exists():
        print(f"Skipping (no-overwrite): {output_file}")
        return None
    meta = note_meta(note)
    data = note_epub_bytes(Path(note["source_file"]), meta, note_id=note["note_id"])
    if write_if_changed(output_file, data):
        print(f"Created: {output_file}")
    tracker.mark_note_exported(str(note["json_file"]), note["note_id"], "epub")
    return True


def convert_html_to_epub() -> int:
    tracker = get_tracker()
    notes = tracker.get_notes_to_process("epub")
    if not notes:
        print("No notes need EPUB conversion - all up to date!")
        return 0
    print(f"Processing {len(notes)} notes for EPUB conversion...")
    no_overwrite = os.getenv("NOTES_EXPORT_NO_OVERWRITE", "false").lower() == "true"
    return run_for_notes("epub", notes, lambda n: convert_note(tracker, n, no_overwrite))


if __name__ == "__main__":
    sys.exit(convert_html_to_epub())
