"""Tests for pure handlers in export_notes.scpt (no Apple Notes access)."""

import pytest

from tests.applescript_harness import call_handler, compile_script, requires_osascript

pytestmark = [requires_osascript, pytest.mark.export]


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    return compile_script(tmp_path_factory.mktemp("scpt"))


def test_write_to_file_replaces_contents(compiled, tmp_path):
    target = tmp_path / "note.html"
    call_handler(compiled, "s's writeToFile(item 1 of argv, item 2 of argv)",
                 str(target), "first version, which is longer")
    call_handler(compiled, "s's writeToFile(item 1 of argv, item 2 of argv)",
                 str(target), "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_write_to_file_utf8(compiled, tmp_path):
    target = tmp_path / "note.txt"
    text = "Café — über 東京 🎉"
    call_handler(compiled, "s's writeToFile(item 1 of argv, item 2 of argv)",
                 str(target), text)
    assert target.read_text(encoding="utf-8") == text


def test_write_to_file_reports_failure(compiled, tmp_path):
    missing_dir = tmp_path / "does-not-exist" / "note.txt"
    out = call_handler(compiled, "s's writeToFile(item 1 of argv, item 2 of argv)",
                       str(missing_dir), "x")
    assert out == "false"


# ── names and templates ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Hello World", "Hello-World"),
    ("a/b:c", "a-b-c"),
    ("--x--", "x"),
    ("", "untitled"),
    ("line one\nline two", "line-one-line-two"),
    ("tab\there", "tab-here"),
])
def test_make_valid_filename(compiled, raw, expected):
    assert call_handler(compiled, "s's makeValidFilename(item 1 of argv)", raw) == expected


def test_generate_filename_token_order(compiled):
    """&accountid used to be eaten by &account; &folderpath by &folder."""
    out = call_handler(
        compiled,
        's\'s generateFilename(item 1 of argv, "T", "42", "iCloud", "Recipes", "STORE-UUID", "UUID", "Food/Recipes")',
        "&account|&accountid|&shortaccountid|&folder|&folderpath|&path|&title-&id")
    assert out == "iCloud|STORE-UUID|UUID|Recipes|Food/Recipes|Food/Recipes|T-42"


def test_generate_filename_does_not_rescan_values(compiled):
    """A title containing "&Id" or a folder named "&title" stays as it is."""
    out = call_handler(
        compiled,
        's\'s generateFilename(item 1 of argv, "Q&Ideas", "42", "iCloud", "&title", "S", "U", "&id")',
        "&folder/&title-&id/&folderpath")
    assert out == "&title/Q&Ideas-42/&id"


@pytest.mark.parametrize("expr,expected", [
    ('{"a", "b"}, {"a", "b"}, {{1, 2}, {3, 4}}, {{}, {true, false}}', "true"),
    ('{"a", "b"}, {"b", "a"}, {{1, 2}}, {}', "false"),          # re-sorted in between
    ('{"a", "b"}, {"a", "b", "c"}, {{1, 2}}, {}', "false"),     # a note was added
    ('{"a", "b"}, {"a", "b"}, {{1}}, {}', "false"),             # a property list is short
    ('{"a", "b"}, {"a", "b"}, {{1, 2}}, {{true}}', "false"),    # an optional one too
])
def test_lists_agree(compiled, expr, expected):
    assert call_handler(compiled, f"s's listsAgree({expr})") == expected


def test_tracker_name_encodes_slashes(compiled):
    assert call_handler(compiled, "s's trackerNameFor(item 1 of argv)",
                        "iCloud/Food/50%") == "iCloud%2FFood%2F50%25"


def test_extract_ids(compiled):
    assert call_handler(compiled, "s's extractID(item 1 of argv)",
                        "x-coredata://ABCD-1234/ICNote/p987") == "987"
    assert call_handler(compiled, "s's extractAccountID(item 1 of argv)",
                        "x-coredata://ABCD-1234/ICAccount/p1") == "ABCD-1234"
    assert call_handler(compiled, "s's extractShortAccountID(item 1 of argv)",
                        "AAAA-BBBB-CCCC") == "CCCC"


def test_iso_local(compiled):
    setup = ["set d to current date", "set day of d to 1", "set year of d to 2026",
             "set month of d to 3", "set day of d to 5", "set time of d to (7 * hours + 8 * minutes + 9)"]
    assert call_handler(compiled, "s's isoLocal(d)", setup=setup) == "2026-03-05T07:08:09"


def test_folder_path_names(compiled):
    setup = ['set ids to {"F1", "F2", "F3", "F4"}',
             'set names to {"Archief", "Food", "Recepten", "Top"}',
             'set parents to {"", "F1", "F2", ""}']
    out = call_handler(compiled, 's\'s joinList(s\'s folderPathNames(3, ids, names, parents), "/")',
                       setup=setup)
    assert out == "Archief/Food/Recepten"
    out = call_handler(compiled, 's\'s joinList(s\'s folderPathNames(4, ids, names, parents), "/")',
                       setup=setup)
    assert out == "Top"


def test_tsv_escape_matches_python(compiled):
    import tracker_io
    raw = "a\tb\\c\nd`$'\""
    escaped = call_handler(compiled, "s's tsvEscape(item 1 of argv)", raw)
    assert escaped == tracker_io.escape(raw)
    assert call_handler(compiled, "s's tsvUnescape(item 1 of argv)", escaped) == raw


# ── tracking data through tracker_io.py (#33) ────────────────────────────

NASTY_TEMPLATE = "LOOK-WHAT`S-INSTALLED $(touch {m}) `touch {m}` 'it''s' \"q\" \\ end"


def test_save_and_load_with_nasty_title(compiled, tmp_path):
    import json
    import sys
    from pathlib import Path
    import tracker_io

    script_dir = Path(tracker_io.__file__).parent
    tracker_cmd = f"'{sys.executable}' '{script_dir / 'tracker_io.py'}'"
    marker = tmp_path / "injected"
    NASTY = NASTY_TEMPLATE.format(m=marker)
    data_dir = tmp_path / "data dir with spaces"
    data_dir.mkdir()
    json_path = data_dir / "iCloud-5G's `folder`.json"
    row = "\t".join(tracker_io.escape(f) for f in [
        "44", "x-coredata://S/ICNote/p44", "LOOK-WHAT`S-44", NASTY, "2026-01-01T10:00:00",
        "2026-03-05T07:08:09", "legacy created", "legacy modified", "iCloud",
        "x-coredata://S/ICAccount/p1", "x-coredata://S/ICFolder/p3",
        tracker_io.UNIT_SEP.join(["5G", "Sub"]), "iCloud-5G"]) + "\n"
    result = call_handler(
        compiled, "s's saveNotebookData(item 1 of argv, item 2 of argv, item 3 of argv, item 4 of argv)",
        tracker_cmd, str(json_path), row, str(data_dir) + "/")
    assert result == ""
    rec = json.loads(json_path.read_text(encoding="utf-8"))["44"]
    assert rec["title"] == NASTY
    assert rec["filename"] == "LOOK-WHAT`S-44"
    assert not marker.exists(), "note data reached a shell"

    loaded = call_handler(
        compiled, 's\'s joinList(item 2 of (s\'s loadNotebookData(item 1 of argv, item 2 of argv, false)), "|")',
        tracker_cmd, str(json_path))
    assert loaded == "LOOK-WHAT`S-44"


def test_renamed_note_removes_only_its_own_attachments(compiled, tmp_path):
    """The old name is a find(1) pattern: brackets must match literally."""
    att = tmp_path / "html" / "iCloud-Food" / "attachments"
    att.mkdir(parents=True)
    own = att / "Plan-[a]-attachment-001.png"
    other = att / "Plan-a-attachment-001.png"
    own.write_bytes(b"x")
    other.write_bytes(b"y")
    call_handler(compiled, "s's handleFilenameChange(item 1 of argv, item 2 of argv, "
                 "item 3 of argv, item 4 of argv)",
                 str(tmp_path) + "/", "iCloud-Food/", "Plan-[a]", "Plan-b")
    assert not own.exists()
    assert other.exists()
