"""notes_db.py on synthetic copies of the Notes database schema (#16)."""

import json
import sqlite3

import pytest

import notes_db

pytestmark = pytest.mark.export


def make_db(path, variant):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER, Z_NAME TEXT)")
    conn.execute("CREATE TABLE Z_METADATA (Z_UUID TEXT)")
    conn.execute("INSERT INTO Z_METADATA VALUES ('STORE')")
    conn.executemany("INSERT INTO Z_PRIMARYKEY VALUES (?, ?)", [(12, "ICNote"), (5, "ICInlineAttachment")])
    if variant == "new":   # macOS 13+ style: ZTYPEUTI1 / ZNOTE1
        conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER, Z_ENT INTEGER, ZTYPEUTI TEXT, "
                     "ZTYPEUTI1 TEXT, ZNOTE INTEGER, ZNOTE1 INTEGER, ZALTTEXT TEXT, ZISPINNED INTEGER, "
                     "ZHASCHECKLIST INTEGER, ZMARKEDFORDELETION INTEGER)")
        rows = [
            (100, 12, None, None, None, None, None, 1, 0, 0),
            (101, 12, None, None, None, None, None, 0, 1, 0),
            (500, 5, None, notes_db.HASHTAG_UTI, None, 100, "#inthemix", None, None, 0),
            (501, 5, None, notes_db.HASHTAG_UTI, None, 100, "#Audio", None, None, 0),
            (502, 5, None, notes_db.HASHTAG_UTI, None, 100, "#inthemix", None, None, 0),
            (503, 5, None, notes_db.HASHTAG_UTI, None, 101, "#gone", None, None, 1),
        ]
        conn.executemany("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    else:                  # older style: ZTYPEUTI / ZNOTE, no flags
        conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER, Z_ENT INTEGER, ZTYPEUTI TEXT, "
                     "ZNOTE INTEGER, ZALTTEXT TEXT)")
        conn.executemany("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?,?,?,?,?)", [
            (100, 12, None, None, None),
            (500, 5, notes_db.HASHTAG_UTI, 100, "#old"),
        ])
    conn.commit()
    conn.close()


@pytest.mark.parametrize("variant", ["new", "old"])
def test_read_note_facts(tmp_path, variant):
    db = tmp_path / "NoteStore.sqlite"
    make_db(db, variant)
    with notes_db.database_copy(db) as conn:
        facts = notes_db.read_note_facts(conn)
        assert notes_db.store_uuid(conn) == "STORE"
    if variant == "new":
        assert facts[100] == {"tags": ["Audio", "inthemix"], "pinned": True, "checklist": False}
        assert facts[101]["tags"] == [] and facts[101]["checklist"] is True
    else:
        assert facts[100]["tags"] == ["old"]
        assert "pinned" not in facts[100]


def test_apply_and_cli(tmp_path):
    db = tmp_path / "NoteStore.sqlite"
    make_db(db, "new")
    root = tmp_path / "export"
    (root / "data").mkdir(parents=True)
    (root / "data" / "iCloud-Notes.json").write_text(json.dumps({
        "100": {"filename": "a-100", "fullNoteId": "x-coredata://STORE/ICNote/p100"},
        "101": {"filename": "b-101", "fullNoteId": "x-coredata://STORE/ICNote/p101"},
        "7": {"filename": "c-7", "fullNoteId": "x-coredata://OTHER/ICNote/p100"},
    }))
    assert notes_db.main(["tags", "--root", str(root), "--db", str(db)]) == 0
    data = json.loads((root / "data" / "iCloud-Notes.json").read_text())
    assert data["100"]["tags"] == ["Audio", "inthemix"] and data["100"]["pinned"] is True
    assert data["101"]["tags"] == [] and data["101"]["tagsSource"] == "database"
    assert "tags" not in data["7"], "a note from another store is left alone"


def test_database_missing(tmp_path):
    assert notes_db.main(["tags", "--root", str(tmp_path), "--db", str(tmp_path / "none.sqlite")]) == 1
