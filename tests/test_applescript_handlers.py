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
