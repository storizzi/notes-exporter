import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import output_format as fmt


@pytest.fixture(autouse=True)
def reset_fmt():
    """Reset output_format state between tests."""
    fmt._json_mode = False
    fmt._json_file = None
    fmt._real_stdout = sys.__stdout__
    # Restore stdout in case a test redirected it
    sys.stdout = sys.__stdout__
    yield
    fmt._json_mode = False
    fmt._json_file = None
    sys.stdout = sys.__stdout__


@pytest.mark.unit
@pytest.mark.json_output
class TestIsJsonMode:
    def test_default_is_false(self):
        assert fmt.is_json_mode() is False

    def test_true_after_enable(self):
        fmt.enable_json_mode("/dev/null")
        assert fmt.is_json_mode() is True


@pytest.mark.unit
@pytest.mark.json_output
class TestEmit:
    def test_noop_when_not_json(self, capsys):
        fmt.emit("test", key="value")
        assert capsys.readouterr().out == ""

    def test_writes_json_line_to_file(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("match", file="note.md", line_num=5, line="hello")
        fmt.close()

        lines = out_file.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "match"
        assert record["file"] == "note.md"
        assert record["line_num"] == 5
        assert record["line"] == "hello"

    def test_multiple_emits(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("match", file="a.md")
        fmt.emit("match", file="b.md")
        fmt.emit("summary", total=2)
        fmt.close()

        lines = out_file.read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["file"] == "a.md"
        assert json.loads(lines[1])["file"] == "b.md"
        assert json.loads(lines[2])["total"] == 2

    def test_handles_non_serializable_values(self, tmp_path):
        """datetime and Path objects should be serialized via default=str."""
        from datetime import datetime
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("test", date=datetime(2026, 3, 18), path=Path("/tmp/test"))
        fmt.close()

        record = json.loads(out_file.read_text().strip())
        assert "2026" in record["date"]
        assert "/tmp/test" in record["path"]


@pytest.mark.unit
@pytest.mark.json_output
class TestAddJsonArg:
    def test_adds_argument(self):
        import argparse
        parser = argparse.ArgumentParser()
        fmt.add_json_arg(parser)
        # Should not raise
        args = parser.parse_args(["--json-log"])
        assert args.json_log == "-"

    def test_with_file_path(self):
        import argparse
        parser = argparse.ArgumentParser()
        fmt.add_json_arg(parser)
        args = parser.parse_args(["--json-log", "/tmp/out.jsonl"])
        assert args.json_log == "/tmp/out.jsonl"

    def test_without_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        fmt.add_json_arg(parser)
        args = parser.parse_args([])
        assert args.json_log is None


@pytest.mark.unit
@pytest.mark.json_output
class TestSetupFromArgs:
    def test_enables_json_to_file(self, tmp_path):
        import argparse
        out_file = tmp_path / "test.jsonl"

        parser = argparse.ArgumentParser()
        fmt.add_json_arg(parser)
        args = parser.parse_args(["--json-log", str(out_file)])
        fmt.setup_from_args(args)

        assert fmt.is_json_mode() is True
        fmt.emit("test", ok=True)
        fmt.close()
        assert out_file.exists()
        record = json.loads(out_file.read_text().strip())
        assert record["ok"] is True

    def test_no_json_when_not_specified(self):
        import argparse
        parser = argparse.ArgumentParser()
        fmt.add_json_arg(parser)
        args = parser.parse_args([])
        fmt.setup_from_args(args)
        assert fmt.is_json_mode() is False


@pytest.mark.unit
@pytest.mark.json_output
class TestJsonOutputConsistency:
    """Test that JSON records use consistent key names."""

    def test_match_record_has_expected_keys(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("match", file="note.md", line_num=10, line="hello world")
        fmt.close()
        record = json.loads(out_file.read_text().strip())
        assert "type" in record
        assert "file" in record
        assert "line_num" in record
        assert "line" in record

    def test_result_record_has_expected_keys(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("result", file="note.md", score=0.95, note_id="123",
                 notebook="iCloud-Notes", filename="note-123",
                 created="2026-01-01", modified="2026-03-01")
        fmt.close()
        record = json.loads(out_file.read_text().strip())
        for key in ["type", "file", "score", "note_id", "notebook",
                     "filename", "created", "modified"]:
            assert key in record, f"Missing key: {key}"

    def test_summary_record_has_type(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("summary", command="test", total=42)
        fmt.close()
        record = json.loads(out_file.read_text().strip())
        assert record["type"] == "summary"
        assert record["command"] == "test"

    def test_discrepancy_record(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("discrepancy", issue="Something is wrong")
        fmt.close()
        record = json.loads(out_file.read_text().strip())
        assert record["type"] == "discrepancy"
        assert record["issue"] == "Something is wrong"

    def test_error_record(self, tmp_path):
        out_file = tmp_path / "test.jsonl"
        fmt.enable_json_mode(str(out_file))
        fmt.emit("error", command="sync", message="Connection refused")
        fmt.close()
        record = json.loads(out_file.read_text().strip())
        assert record["type"] == "error"
        assert record["message"] == "Connection refused"
