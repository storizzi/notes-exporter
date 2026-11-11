"""Tests for tracker_io.py (tracking JSON load / save / finalize)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tracker_io as tio

pytestmark = pytest.mark.export

NASTY_TITLE = "LOOK-WHAT`S $(rm -rf ~) 'quoted' \"double\" \\back\tslash"


def save_row(note_id, filename, title="Title", modified_local="2026-03-05T07:08:09",
             folder_id="x-coredata://S/ICFolder/p10", folder_path=("Food", "Recipes"),
             subdir="iCloud-Recipes"):
    fields = [note_id, f"x-coredata://S/ICNote/p{note_id}", filename, title,
              "2026-01-01T10:00:00", modified_local,
              "Thursday, 1 January 2026 at 10:00:00", "Thursday, 5 March 2026 at 07:08:09",
              "iCloud", "x-coredata://S/ICAccount/p1", folder_id,
              tio.UNIT_SEP.join(folder_path), subdir]
    return "\t".join(tio.escape(f) for f in fields)


def live_note(tracker, note_id, folder_id="x-coredata://S/ICFolder/p10", title="T",
              locked="0", shared="0", full_id=None):
    full_id = full_id or f"x-coredata://S/ICNote/p{note_id}"
    fields = ["N", tracker, note_id, full_id, title, "2026-01-01T10:00:00",
              "2026-03-05T07:08:09", "iCloud", "x-coredata://S/ICAccount/p1", folder_id,
              tio.UNIT_SEP.join(["Food", "Recipes"]), tracker, locked, shared]
    return "\t".join(tio.escape(f) for f in fields)


def live_folder(tracker, folder_id):
    return "\t".join(["F", tracker, folder_id, tracker])


class TestEscaping:
    @pytest.mark.parametrize("value", ["plain", "a\tb", "a\nb\r", "back\\slash", "\\t literal",
                                       NASTY_TITLE, "Café 東京"])
    def test_roundtrip(self, value):
        assert tio.unescape(tio.escape(value)) == value

    def test_escaped_has_no_separators(self):
        assert "\t" not in tio.escape(NASTY_TITLE)
        assert "\n" not in tio.escape("a\nb")


class TestTimes:
    def test_local_to_aware_and_back(self):
        aware = tio.local_to_aware("2026-03-05T07:08:09")
        assert aware.startswith("2026-03-05T07:08:09")
        assert aware[19] in "+-"
        assert tio.aware_to_local(aware) == "2026-03-05T07:08:09"

    def test_bad_values(self):
        assert tio.local_to_aware("") == ""
        assert tio.local_to_aware("Thursday, 5 March") == ""
        assert tio.aware_to_local("nonsense") == ""


class TestSave:
    def test_save_creates_records_with_nasty_title(self, tmp_path):
        tsv = tmp_path / "rows.tsv"
        tsv.write_text(save_row("44", "LOOK-WHAT`S-44", title=NASTY_TITLE) + "\n", encoding="utf-8")
        out = tmp_path / "data" / "iCloud-Recipes.json"
        assert tio.save(out, tsv) == 1
        rec = json.loads(out.read_text(encoding="utf-8"))["44"]
        assert rec["title"] == NASTY_TITLE
        assert rec["filename"] == "LOOK-WHAT`S-44"
        assert rec["folderPath"] == ["Food", "Recipes"]
        assert rec["subdir"] == "iCloud-Recipes"
        assert rec["exportCount"] == 1
        assert rec["modifiedAt"].startswith("2026-03-05T07:08:09")
        assert rec["fullNoteId"] == "x-coredata://S/ICNote/p44"

    def test_save_preserves_other_fields_and_records(self, tmp_path):
        out = tmp_path / "t.json"
        out.write_text(json.dumps({
            "1": {"filename": "old", "lastExportedToMarkdown": "x", "exportCount": 3,
                  "firstExported": "first", "deletedDate": "then"},
            "2": {"filename": "untouched"},
        }))
        tsv = tmp_path / "rows.tsv"
        tsv.write_text(save_row("1", "new-1") + "\n")
        tio.save(out, tsv)
        data = json.loads(out.read_text())
        assert data["1"]["filename"] == "new-1"
        assert data["1"]["lastExportedToMarkdown"] == "x"
        assert data["1"]["exportCount"] == 4
        assert data["1"]["firstExported"] == "first"
        assert "deletedDate" not in data["1"], "a re-exported note is no longer deleted (#30)"
        assert data["2"] == {"filename": "untouched"}

    def test_last_exported_changes_every_save(self, tmp_path):
        out = tmp_path / "t.json"
        tsv = tmp_path / "rows.tsv"
        tsv.write_text(save_row("1", "n-1") + "\n")
        tio.save(out, tsv)
        first = json.loads(out.read_text())["1"]["lastExported"]
        tio.save(out, tsv)
        assert json.loads(out.read_text())["1"]["lastExported"] != first

    def test_corrupt_tracker_is_kept_aside(self, tmp_path):
        out = tmp_path / "t.json"
        out.write_text("{not json")
        tsv = tmp_path / "rows.tsv"
        tsv.write_text(save_row("1", "n-1") + "\n")
        tio.save(out, tsv)
        assert (tmp_path / "t.json.corrupt").read_text() == "{not json"
        assert "1" in json.loads(out.read_text())


class TestLoad:
    def test_load_lines(self, tmp_path):
        out = tmp_path / "t.json"
        out.write_text(json.dumps({
            "1": {"filename": "a\tb", "modified": "legacy", "modifiedAt": "2026-03-05T07:08:09+00:00"},
            "2": {"filename": "gone", "deletedDate": "x"},
        }))
        lines = tio.load_lines(out, include_deleted=False)
        assert len(lines) == 1
        parts = tio.split_line(lines[0])
        assert parts[0] == "1" and parts[1] == "a\tb" and parts[3] == "legacy"
        assert len(tio.load_lines(out, include_deleted=True)) == 2

    def test_load_missing_file(self, tmp_path):
        assert tio.load_lines(tmp_path / "none.json", False) == []


class TestFinalize:
    def write_tracker(self, data_dir, name, records):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / f"{name}.json").write_text(json.dumps(records))

    def records(self, data_dir, name):
        return json.loads((data_dir / f"{name}.json").read_text())

    def test_same_named_folders_do_not_delete_each_other(self, tmp_path):
        """#37: Alpha/Dup and Beta/Dup share tracker iCloud-Dup."""
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Dup", {
            "100": {"filename": "from-alpha-100", "fullNoteId": "x-coredata://S/ICNote/p100"},
            "200": {"filename": "from-beta-200", "fullNoteId": "x-coredata://S/ICNote/p200"},
        })
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([
            live_note("iCloud-Dup", "200", folder_id="x-coredata://S/ICFolder/pBETA"),
            live_folder("iCloud-Dup", "x-coredata://S/ICFolder/pBETA"),
            live_note("iCloud-Dup", "100", folder_id="x-coredata://S/ICFolder/pALPHA"),
            live_folder("iCloud-Dup", "x-coredata://S/ICFolder/pALPHA"),
            "END"]) + "\n")
        summary = tio.finalize(data, live)
        recs = self.records(data, "iCloud-Dup")
        assert "deletedDate" not in recs["100"]
        assert "deletedDate" not in recs["200"]
        assert recs["100"]["folderId"].endswith("pALPHA")
        assert summary["deleted"] == 0

    def test_deleted_note_is_marked(self, tmp_path):
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Notes", {
            "1": {"filename": "keep-1", "fullNoteId": "x-coredata://S/ICNote/p1"},
            "2": {"filename": "gone-2", "fullNoteId": "x-coredata://S/ICNote/p2"},
        })
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([live_note("iCloud-Notes", "1"),
                                   live_folder("iCloud-Notes", "x-coredata://S/ICFolder/p10"),
                                   "END"]) + "\n")
        summary = tio.finalize(data, live)
        recs = self.records(data, "iCloud-Notes")
        assert "deletedDate" in recs["2"] and "deletedAt" in recs["2"]
        assert "deletedDate" not in recs["1"]
        assert summary["deleted"] == 1

    def test_incomplete_run_records_no_deletions(self, tmp_path):
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Notes", {"2": {"filename": "gone-2"}})
        live = tmp_path / "live.tsv"
        live.write_text(live_folder("iCloud-Notes", "x-coredata://S/ICFolder/p10") + "\n")
        summary = tio.finalize(data, live)
        assert "deletedDate" not in self.records(data, "iCloud-Notes")["2"]
        assert summary["complete"] is False

    def test_unvisited_folder_is_left_alone(self, tmp_path):
        """A folder skipped by a filter must not have its notes marked deleted."""
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Other", {"5": {"filename": "x-5"}})
        live = tmp_path / "live.tsv"
        live.write_text("END\n")
        tio.finalize(data, live)
        assert "deletedDate" not in self.records(data, "iCloud-Other")["5"]

    def test_record_of_other_folder_instance_is_left_alone(self, tmp_path):
        """Same tracker, but the record belongs to a folder not visited this run."""
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Dup", {
            "7": {"filename": "x-7", "folderId": "x-coredata://S/ICFolder/pOTHER"}})
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([live_folder("iCloud-Dup", "x-coredata://S/ICFolder/pALPHA"),
                                   "END"]) + "\n")
        tio.finalize(data, live)
        assert "deletedDate" not in self.records(data, "iCloud-Dup")["7"]

    def test_moved_note(self, tmp_path):
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-A", {"9": {"filename": "n-9", "fullNoteId": "x-coredata://S/ICNote/p9"}})
        self.write_tracker(data, "iCloud-B", {"9": {"filename": "n-9", "fullNoteId": "x-coredata://S/ICNote/p9"}})
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([live_note("iCloud-B", "9", folder_id="x-coredata://S/ICFolder/pB"),
                                   live_folder("iCloud-B", "x-coredata://S/ICFolder/pB"),
                                   "END"]) + "\n")
        summary = tio.finalize(data, live)
        a = self.records(data, "iCloud-A")["9"]
        assert a["movedTo"] == "iCloud-B" and "deletedDate" in a
        assert "deletedDate" not in self.records(data, "iCloud-B")["9"]
        assert summary["moved"] == 1

    def test_note_that_came_back_is_restored(self, tmp_path):
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Notes", {
            "3": {"filename": "n-3", "deletedDate": "then", "movedTo": "x"}})
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([live_note("iCloud-Notes", "3", locked="1", shared="1"),
                                   live_folder("iCloud-Notes", "x-coredata://S/ICFolder/p10"),
                                   "END"]) + "\n")
        summary = tio.finalize(data, live)
        rec = self.records(data, "iCloud-Notes")["3"]
        assert "deletedDate" not in rec and "movedTo" not in rec
        assert rec["locked"] is True and rec["shared"] is True
        assert rec["folderPath"] == ["Food", "Recipes"]
        assert summary["restored"] == 1

    def test_finalize_never_touches_modified_dates(self, tmp_path):
        """A note skipped by a filter keeps its old modified key, so it is exported next time."""
        data = tmp_path / "data"
        self.write_tracker(data, "iCloud-Notes", {
            "1": {"filename": "n-1", "modified": "old", "modifiedAt": "2020-01-01T00:00:00+00:00"}})
        live = tmp_path / "live.tsv"
        live.write_text("\n".join([live_note("iCloud-Notes", "1"),
                                   live_folder("iCloud-Notes", "x-coredata://S/ICFolder/p10"),
                                   "END"]) + "\n")
        tio.finalize(data, live)
        rec = self.records(data, "iCloud-Notes")["1"]
        assert rec["modified"] == "old"
        assert rec["modifiedAt"] == "2020-01-01T00:00:00+00:00"

    def test_error_lines(self, tmp_path):
        live = tmp_path / "live.tsv"
        live.write_text("E\tiCloud-Notes\t4\tx-coredata://S/ICNote/p4\tboom\\tbang\nEND\n")
        index = tio.read_live(live)
        assert index.errors == [{"tracker": "iCloud-Notes", "noteId": "4",
                                 "fullNoteId": "x-coredata://S/ICNote/p4", "message": "boom\tbang"}]


class TestCli:
    def test_cli_save_and_load(self, tmp_path):
        script = Path(tio.__file__)
        tsv = tmp_path / "rows.tsv"
        tsv.write_text(save_row("1", "n-1", title=NASTY_TITLE) + "\n", encoding="utf-8")
        out = tmp_path / "t.json"
        r = subprocess.run([sys.executable, str(script), "save", str(out), str(tsv)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([sys.executable, str(script), "load", str(out), "0"],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.startswith("1\tn-1\t")

    def test_cli_usage_error(self):
        r = subprocess.run([sys.executable, str(Path(tio.__file__)), "bogus"],
                           capture_output=True, text=True)
        assert r.returncode == 2
