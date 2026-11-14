"""notes_write_helper.py without Notes: picture embedding stays inside the export, and the
script's answer is read — osascript and pandoc are fakes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import notes_write_helper as h  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nxx"


def test_embeds_only_pictures_inside_the_export(tmp_path):
    root = tmp_path / "export"
    (root / "md" / "f" / "attachments").mkdir(parents=True)
    (root / "md" / "f" / "attachments" / "a.png").write_bytes(PNG)
    (tmp_path / "secret.png").write_bytes(PNG)
    html = ('<p><img src="attachments/a.png"><img src="../../../secret.png">'
            '<img src="/etc/x.png"><img src="https://x/y.png"></p>')
    out = h.embed_images(html, str(root / "md" / "f"), str(root))
    assert out.count("data:image/png;base64,") == 1
    assert "../../../secret.png" in out and "/etc/x.png" in out and "https://x/y.png" in out


def test_a_link_out_through_a_symlink_is_left(tmp_path):
    root = tmp_path / "export"
    (root / "md").mkdir(parents=True)
    (tmp_path / "secret.png").write_bytes(PNG)
    os.symlink(tmp_path / "secret.png", root / "md" / "s.png")
    assert "base64" not in h.embed_images('<img src="s.png">', str(root / "md"), str(root))


def _fake(tmp_path, name, body):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(0o755)
    return str(p)


def _run(tmp_path, req, osascript_out, env_extra=None):
    env = dict(os.environ,
               NOTES_WRITE_OSASCRIPT=_fake(tmp_path, "osascript", f"cat > /dev/null; printf '{osascript_out}'\n"),
               NOTES_WRITE_PANDOC=_fake(tmp_path, "pandoc", "cat\n"), **(env_extra or {}))
    r = subprocess.run([sys.executable, str(REPO / "notes_write_helper.py")], input=json.dumps(req),
                       capture_output=True, text=True, env=env, timeout=30)
    return json.loads(r.stdout)


def test_reads_the_scripts_answer(tmp_path):
    out = _run(tmp_path, {"operation": "update", "note_id": "n1", "markdown": "# T"},
               r"ok\tn1\t2026-03-05T07:08:09\n")
    assert out["ok"] and out["note_id"] == "n1" and out["modified"].startswith("2026-03-05T07:08:09")


def test_a_refusal_becomes_a_permission_code(tmp_path):
    out = _run(tmp_path, {"operation": "modified", "note_id": "n1"},
               r"error\t-1743\tNot authorized to send Apple events\n")
    assert out == {"ok": False, "error": "Not authorized to send Apple events", "code": "permission"}


def test_a_new_note_needs_a_folder(tmp_path):
    out = _run(tmp_path, {"operation": "create", "account": "iCloud", "folder_path": [], "markdown": "x"}, "")
    assert out["ok"] is False and out["code"] == "bad_request"
