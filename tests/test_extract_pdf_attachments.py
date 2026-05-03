import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from extract_pdf_attachments import START_MARKER, extract_pdf_attachments


def _create_notes_db(notes_dir: Path):
    db = notes_dir / "NoteStore.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Z_PRIMARYKEY (Z_NAME TEXT, Z_ENT INTEGER)")
    conn.execute(
        """
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            ZIDENTIFIER TEXT,
            ZFILENAME TEXT,
            ZGENERATION1 TEXT,
            ZFALLBACKPDFGENERATION TEXT,
            ZNOTE INTEGER,
            ZMEDIA INTEGER,
            ZCREATIONDATE REAL,
            ZMODIFICATIONDATE REAL,
            ZTYPEUTI TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO Z_PRIMARYKEY (Z_NAME, Z_ENT) VALUES (?, ?)",
        [("ICAccount", 1), ("ICMedia", 2), ("ICAttachment", 3)],
    )
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZIDENTIFIER) VALUES (10, 1, 'ACCOUNT-1')"
    )
    conn.execute(
        """
        INSERT INTO ZICCLOUDSYNCINGOBJECT (
            Z_PK, Z_ENT, ZIDENTIFIER, ZFILENAME, ZGENERATION1, ZTYPEUTI
        ) VALUES (20, 2, 'MEDIA-1', 'Original Contract.pdf', 'GEN-1', 'public.pdf')
        """
    )
    conn.execute(
        """
        INSERT INTO ZICCLOUDSYNCINGOBJECT (
            Z_PK, Z_ENT, ZNOTE, ZMEDIA, ZCREATIONDATE, ZMODIFICATIONDATE, ZTYPEUTI
        ) VALUES (30, 3, 1, 20, 1000, 2000, 'public.pdf')
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.unit
@pytest.mark.export
def test_extracts_pdf_and_adds_markdown_links(tmp_path, monkeypatch):
    notes_dir = tmp_path / "group.com.apple.notes"
    media_dir = notes_dir / "Accounts" / "ACCOUNT-1" / "Media" / "MEDIA-1" / "GEN-1"
    media_dir.mkdir(parents=True)
    (media_dir / "Original Contract.pdf").write_bytes(b"%PDF-1.4 test")
    _create_notes_db(notes_dir)

    export_dir = tmp_path / "export"
    notebook = "iCloud-Notes"
    (export_dir / "data").mkdir(parents=True)
    (export_dir / "md" / notebook).mkdir(parents=True)
    (export_dir / "data" / f"{notebook}.json").write_text(
        json.dumps({"1": {"filename": "Test-Note-1", "lastExported": "now"}}),
        encoding="utf-8",
    )
    md_file = export_dir / "md" / notebook / "Test-Note-1.md"
    md_file.write_text("# Test Note\n\nBody\n", encoding="utf-8")

    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(export_dir))
    monkeypatch.setenv("NOTES_EXPORT_NOTES_DATA_DIR", str(notes_dir))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

    extract_pdf_attachments()

    copied = export_dir / "md" / notebook / "attachments" / "Test-Note-1-pdf-001-Original-Contract.pdf"
    assert copied.read_bytes() == b"%PDF-1.4 test"

    content = md_file.read_text(encoding="utf-8")
    assert START_MARKER in content
    assert "- [Test-Note-1-pdf-001-Original-Contract.pdf](./attachments/Test-Note-1-pdf-001-Original-Contract.pdf)" in content


@pytest.mark.unit
@pytest.mark.export
def test_managed_block_is_replaced_not_duplicated(tmp_path, monkeypatch):
    notes_dir = tmp_path / "group.com.apple.notes"
    media_dir = notes_dir / "Accounts" / "ACCOUNT-1" / "Media" / "MEDIA-1" / "GEN-1"
    media_dir.mkdir(parents=True)
    (media_dir / "Original Contract.pdf").write_bytes(b"%PDF-1.4 test")
    _create_notes_db(notes_dir)

    export_dir = tmp_path / "export"
    notebook = "iCloud-Notes"
    (export_dir / "data").mkdir(parents=True)
    (export_dir / "md" / notebook).mkdir(parents=True)
    (export_dir / "data" / f"{notebook}.json").write_text(
        json.dumps({"1": {"filename": "Test-Note-1", "lastExported": "now"}}),
        encoding="utf-8",
    )
    md_file = export_dir / "md" / notebook / "Test-Note-1.md"
    md_file.write_text("# Test Note\n\nBody\n", encoding="utf-8")

    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(export_dir))
    monkeypatch.setenv("NOTES_EXPORT_NOTES_DATA_DIR", str(notes_dir))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")

    extract_pdf_attachments()
    extract_pdf_attachments()

    content = md_file.read_text(encoding="utf-8")
    assert content.count(START_MARKER) == 1
    assert content.count("Test-Note-1-pdf-001-Original-Contract.pdf") == 2


@pytest.mark.unit
@pytest.mark.export
def test_note_folder_mode_places_pdf_beside_markdown(tmp_path, monkeypatch):
    notes_dir = tmp_path / "group.com.apple.notes"
    media_dir = notes_dir / "Accounts" / "ACCOUNT-1" / "Media" / "MEDIA-1" / "GEN-1"
    media_dir.mkdir(parents=True)
    (media_dir / "Original Contract.pdf").write_bytes(b"%PDF-1.4 test")
    _create_notes_db(notes_dir)

    export_dir = tmp_path / "export"
    notebook = "iCloud-Notes"
    (export_dir / "data").mkdir(parents=True)
    note_dir = export_dir / "md" / notebook / "Test-Note-1"
    note_dir.mkdir(parents=True)
    (export_dir / "data" / f"{notebook}.json").write_text(
        json.dumps({"1": {"filename": "Test-Note-1", "lastExported": "now"}}),
        encoding="utf-8",
    )
    md_file = note_dir / "Test-Note-1.md"
    md_file.write_text("# Test Note\n\nBody\n", encoding="utf-8")

    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(export_dir))
    monkeypatch.setenv("NOTES_EXPORT_NOTES_DATA_DIR", str(notes_dir))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    monkeypatch.setenv("NOTES_EXPORT_NOTE_FOLDERS", "true")

    extract_pdf_attachments()

    copied = note_dir / "Test-Note-1-pdf-001-Original-Contract.pdf"
    assert copied.read_bytes() == b"%PDF-1.4 test"
    content = md_file.read_text(encoding="utf-8")
    assert "(./Test-Note-1-pdf-001-Original-Contract.pdf)" in content
    assert not (note_dir / "attachments").exists()


@pytest.mark.unit
@pytest.mark.export
def test_extracts_paper_doc_pdf_fallback(tmp_path, monkeypatch):
    notes_dir = tmp_path / "group.com.apple.notes"
    fallback_dir = notes_dir / "Accounts" / "ACCOUNT-1" / "FallbackPDFs" / "PAPER-1" / "GEN-PDF"
    fallback_dir.mkdir(parents=True)
    (fallback_dir / "FallbackPDF.pdf").write_bytes(b"%PDF-1.4 paper")
    _create_notes_db(notes_dir)

    conn = sqlite3.connect(notes_dir / "NoteStore.sqlite")
    conn.execute(
        """
        INSERT INTO ZICCLOUDSYNCINGOBJECT (
            Z_PK, Z_ENT, ZIDENTIFIER, ZFALLBACKPDFGENERATION, ZNOTE, ZCREATIONDATE, ZMODIFICATIONDATE, ZTYPEUTI
        ) VALUES (40, 3, 'PAPER-1', 'GEN-PDF', 2, 3000, 4000, 'com.apple.paper.doc.pdf')
        """
    )
    conn.commit()
    conn.close()

    export_dir = tmp_path / "export"
    notebook = "iCloud-Notes"
    note_dir = export_dir / "md" / notebook / "Paper-Doc-2"
    note_dir.mkdir(parents=True)
    (export_dir / "data").mkdir(parents=True)
    (export_dir / "data" / f"{notebook}.json").write_text(
        json.dumps({"2": {"filename": "Paper-Doc-2", "lastExported": "now"}}),
        encoding="utf-8",
    )
    md_file = note_dir / "Paper-Doc-2.md"
    md_file.write_text("# Paper Doc\n", encoding="utf-8")

    monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(export_dir))
    monkeypatch.setenv("NOTES_EXPORT_NOTES_DATA_DIR", str(notes_dir))
    monkeypatch.setenv("NOTES_EXPORT_USE_SUBDIRS", "true")
    monkeypatch.setenv("NOTES_EXPORT_NOTE_FOLDERS", "true")

    extract_pdf_attachments()

    copied = note_dir / "Paper-Doc-2-pdf-001-Scan.pdf"
    assert copied.read_bytes() == b"%PDF-1.4 paper"
    assert "(./Paper-Doc-2-pdf-001-Scan.pdf)" in md_file.read_text(encoding="utf-8")
