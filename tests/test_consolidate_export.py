import base64
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from consolidate_export import consolidate_export


@pytest.mark.unit
@pytest.mark.export
def test_consolidates_note_files_and_metadata(tmp_path, monkeypatch):
    export_dir = tmp_path / "export"
    notebook = "iCloud-Personal/Folder"
    filename = "Test-Note-123"

    data_dir = export_dir / "data" / "iCloud-Personal"
    data_dir.mkdir(parents=True)
    (data_dir / "Folder.json").write_text(
        json.dumps(
            {
                "123": {
                    "filename": filename,
                    "created": "created date",
                    "modified": "modified date",
                    "firstExported": "first export",
                    "lastExported": "last export",
                    "exportCount": 2,
                    "fullNoteId": "x-coredata://note/123",
                }
            }
        ),
        encoding="utf-8",
    )

    embedded_png = base64.b64encode(b"embedded png").decode("ascii")
    for folder, suffix, content in [
        ("html", ".html", "processed html"),
        ("raw", ".html", f'<p>raw</p><img src="data:image/png;base64,{embedded_png}"/>'),
        ("text", ".txt", "plain text"),
    ]:
        path = export_dir / folder / notebook / f"{filename}{suffix}"
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")

    note_dir = export_dir / "md" / notebook / filename
    note_dir.mkdir(parents=True)
    (note_dir / f"{filename}.md").write_text("# Markdown", encoding="utf-8")
    (note_dir / f"{filename}-attachment-002.png").write_bytes(b"png")
    (note_dir / f"{filename}-pdf-001-Document.pdf").write_bytes(b"pdf")

    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(export_dir))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    monkeypatch.setenv("NOTES_EXPORT_NOTE_FOLDERS", "true")

    consolidate_export()

    target_dir = export_dir / "notes" / notebook / filename
    assert (target_dir / f"{filename}.md").read_text(encoding="utf-8") == "# Markdown"
    assert (target_dir / f"{filename}.html").read_text(encoding="utf-8") == "processed html"
    raw_html = (target_dir / f"{filename}.raw.html").read_text(encoding="utf-8")
    assert "data:image" not in raw_html
    assert f'./{filename}-attachment-001.png' in raw_html
    assert (target_dir / f"{filename}.txt").read_text(encoding="utf-8") == "plain text"
    assert (target_dir / f"{filename}-attachment-001.png").read_bytes() == b"embedded png"
    assert (target_dir / f"{filename}-attachment-002.png").read_bytes() == b"png"
    assert (target_dir / f"{filename}-pdf-001-Document.pdf").read_bytes() == b"pdf"

    metadata = json.loads((target_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["noteId"] == "123"
    assert metadata["fullNoteId"] == "x-coredata://note/123"
    assert metadata["notebook"] == notebook
    assert metadata["files"]["markdown"] == f"{filename}.md"
    assert sorted(metadata["files"]["attachments"]) == [
        f"{filename}-attachment-001.png",
        f"{filename}-attachment-002.png",
        f"{filename}-pdf-001-Document.pdf",
    ]

    index = json.loads((export_dir / "notes" / "index.json").read_text(encoding="utf-8"))
    assert len(index["notes"]) == 1
    assert index["notes"][0]["path"] == f"{notebook}/{filename}"
