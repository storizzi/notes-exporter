"""End-to-end tests of exportnotes.zsh with a fake ``osascript``.

Apple Notes is never touched: tests/fake_osascript.py stands in for
``osascript export_notes.scpt`` (installed first on PATH), so the shell
pipeline - options, lock, events, tracking, tidy, conversions, manifest and
exit codes - runs for real against a described library.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "exportnotes.zsh"

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("zsh"),
                                reason="exportnotes.zsh needs macOS and zsh")


def _note(nid, title, folder=("Food",), modified="2026-03-05T07:08:09", **extra):
    note = {"account": "iCloud", "folder": list(folder), "folder_id": "-".join(folder),
            "id": nid, "title": title, "modified": modified,
            "html": f"<div><h1>{title}</h1><div>Body of {title}</div></div>",
            "text": f"{title}\nBody of {title}"}
    note.update(extra)
    return note


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "osascript"
    fake.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{REPO / 'tests' / 'fake_osascript.py'}' \"$@\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    library = tmp_path / "library.json"
    e = {k: v for k, v in os.environ.items() if not k.startswith("NOTES_EXPORT_")}
    e.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_NOTES_LIBRARY=str(library),
             NOTES_EXPORT_SKIP_PERMISSION_CHECK="true", HOME=str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return {"env": e, "library": library, "root": tmp_path / "export", "tmp": tmp_path}


def write_library(env, notes, fail=None):
    env["library"].write_text(json.dumps({"notes": notes, "fail": fail}))


def run(env, *args, extra_env=None):
    e = dict(env["env"])
    e.update(extra_env or {})
    cmd = ["zsh", str(SCRIPT), "--python", sys.executable, "--root-dir", str(env["root"]),
           "--filename-format", "&title", *args]
    return subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=120)


def events_of(result):
    return [json.loads(l) for l in result.stdout.splitlines() if l.strip()]


def manifest(env):
    return json.loads((env["root"] / "manifest.json").read_text())


# ── basics ───────────────────────────────────────────────────────────────

def test_version(env):
    r = run(env, "--version")
    assert r.returncode == 0
    assert r.stdout.strip() == f"notes-exporter {(REPO / 'VERSION').read_text().strip()}"
    r = run(env, "--json-log", "--version")
    assert json.loads(r.stdout)["type"] == "version"


def test_unknown_option_exits_1(env):
    assert run(env, "--frobnicate").returncode == 1


def test_first_run_ok_with_manifest_and_json_events(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Bread", folder=("Food", "Baking"))])
    r = run(env, "--json-log", "--folder-hierarchy", "--convert-markdown", "true")
    assert r.returncode == 0, r.stderr
    evs = events_of(r)  # stdout is JSON Lines only
    types = [e["type"] for e in evs]
    assert types[0] == "start" and types[-1] == "result"
    assert evs[-1]["status"] == "ok" and evs[-1]["exit_code"] == 0
    progress = [e for e in evs if e["type"] == "progress"]
    assert progress and all({"done", "total", "stage"} <= e.keys() for e in progress)
    assert any(e["stage"] == "export" and e["done"] == e["total"] for e in progress)

    m = manifest(env)
    assert m["format"] == "notes-exporter.manifest" and m["version"] == 1
    assert m["run"]["status"] == "ok" and m["run"]["mode"] == "incremental"
    assert m["run"]["sequence"] == 1
    by_title = {n["title"]: n for n in m["notes"]}
    bread = by_title["Bread"]
    assert bread["folder_path"] == ["Food", "Baking"]
    assert bread["id"] == "x-coredata://S/ICNote/p2"
    assert set(bread["outputs"]) >= {"raw", "text", "html", "md"}
    assert bread["outputs"]["md"]["path"] == "md/iCloud/Food/Baking/Bread.md"
    assert len(bread["outputs"]["md"]["sha256"]) == 64
    assert bread["changed_this_run"] is True
    assert m["deleted"] == [] and m["skipped"] == []
    assert not (env["root"] / ".notes-exporter.lock").exists()


def test_incremental_rerun_changes_nothing(env):
    write_library(env, [_note(1, "Scones")])
    assert run(env).returncode == 0
    r = run(env)
    assert r.returncode == 0, r.stderr
    m = manifest(env)
    assert m["run"]["sequence"] == 2
    assert [n["changed_this_run"] for n in m["notes"]] == [False]
    assert m["notes"][0]["changed_in_run"] == 1


def test_rename_move_and_delete(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Bread"), _note(3, "Soup")])
    assert run(env, "--convert-markdown", "true").returncode == 0
    root = env["root"]
    assert (root / "md/iCloud-Food/Soup.md").exists()

    # 1 renamed, 2 moved to another folder, 3 deleted
    write_library(env, [_note(1, "Cream Scones", modified="2026-04-01T10:00:00"),
                        _note(2, "Bread", folder=("Baking",), modified="2026-04-01T10:00:00")])
    r = run(env, "--convert-markdown", "true")
    assert r.returncode == 0, r.stderr
    m = manifest(env)
    notes = {n["short_id"]: n for n in m["notes"]}

    assert notes["1"]["previous_outputs"]["md"] == "md/iCloud-Food/Scones.md"
    assert notes["1"]["outputs"]["md"]["path"] == "md/iCloud-Food/Cream-Scones.md"
    assert not (root / "md/iCloud-Food/Scones.md").exists()

    assert notes["2"]["folder_path"] == ["Baking"]
    assert notes["2"]["previous_outputs"]["md"] == "md/iCloud-Food/Bread.md"
    assert not (root / "md/iCloud-Food/Bread.md").exists()  # old copy tidied
    assert (root / "md/iCloud-Baking/Bread.md").exists()

    assert [d["short_id"] for d in m["deleted"]] == ["3"]
    gone = m["deleted"][0]
    assert gone["deleted_this_run"] is True and gone["removed_outputs"] == []
    assert "md/iCloud-Food/Soup.md" in gone["remaining_outputs"]  # kept without --prune-deleted

    r = run(env, "--convert-markdown", "true", "--prune-deleted", "true")
    assert r.returncode == 0, r.stderr
    gone = manifest(env)["deleted"][0]
    assert "md/iCloud-Food/Soup.md" in gone["removed_outputs"] and gone["remaining_outputs"] == []
    assert not (root / "md/iCloud-Food/Soup.md").exists()


def test_note_moved_to_recently_deleted_is_deleted_when_that_folder_is_excluded(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Bread")])
    args = ("--exclude-folders", "Recently Deleted")
    assert run(env, *args).returncode == 0
    write_library(env, [_note(1, "Scones"),
                        _note(2, "Bread", folder=("Recently Deleted",))])
    assert run(env, *args).returncode == 0
    m = manifest(env)
    assert [n["short_id"] for n in m["notes"]] == ["1"]
    assert [d["short_id"] for d in m["deleted"]] == ["2"]
    assert not (env["root"] / "raw/iCloud-Recently-Deleted").exists()


# ── partial, failed, refused, locked ─────────────────────────────────────

def test_locked_and_failing_notes_make_a_partial_run(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Secret", locked=True),
                        _note(3, "Broken", error="Notes got an error (-1728)")])
    r = run(env, "--json-log")
    assert r.returncode == 2, r.stderr
    assert events_of(r)[-1]["status"] == "partial"
    m = manifest(env)
    assert m["run"]["status"] == "partial"
    reasons = {s["short_id"]: s["reason"] for s in m["skipped"]}
    assert reasons == {"2": "locked", "3": "error"}
    assert [n["short_id"] for n in m["notes"]] == ["1"]


def test_only_locked_notes_is_still_ok(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Secret", locked=True)])
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert [s["reason"] for s in manifest(env)["skipped"]] == ["locked"]


def test_crash_exits_5_and_records_no_deletions(env):
    write_library(env, [_note(1, "Scones"), _note(2, "Bread", folder=("Other",))])
    assert run(env).returncode == 0
    # The second folder is never reached: its note must not be called deleted
    write_library(env, [_note(1, "Scones"), _note(2, "Bread", folder=("Other",))], fail="crash")
    r = run(env, "--json-log")
    assert r.returncode == 5
    assert events_of(r)[-1]["status"] == "failed"
    m = manifest(env)  # written even after a failure
    assert m["run"]["status"] == "failed"
    assert m["deleted"] == []


def test_refused_automation_exits_3(env):
    write_library(env, [_note(1, "Scones")], fail="refuse")
    r = run(env, "--json-log")
    assert r.returncode == 3
    assert events_of(r)[-1]["exit_code"] == 3


def test_non_interactive_never_waits_for_a_permission_prompt(env):
    """The real check: on a Mac that has not granted automation it says 'prompt'."""
    write_library(env, [_note(1, "Scones")])
    check = subprocess.run([sys.executable, str(REPO / "notes_permission.py")],
                           capture_output=True, text=True)
    if check.stdout.strip() not in ("prompt", "denied"):
        pytest.skip(f"Notes automation is '{check.stdout.strip()}' here")
    r = run(env, "--non-interactive", "--json-log",
            extra_env={"NOTES_EXPORT_SKIP_PERMISSION_CHECK": "false"})
    assert r.returncode == 3
    evs = events_of(r)
    assert any(e["type"] == "permission" for e in evs)
    assert evs[-1]["exit_code"] == 3
    assert not (env["root"] / "raw").exists()  # osascript was never started


def test_lock_held_exits_4_and_stale_lock_is_taken(env):
    write_library(env, [_note(1, "Scones")])
    lock = env["root"] / ".notes-exporter.lock"
    lock.mkdir(parents=True)
    holder = subprocess.Popen(["sleep", "30"])
    try:
        (lock / "pid").write_text(str(holder.pid))
        r = run(env, "--json-log")
        assert r.returncode == 4
        assert events_of(r)[-1]["exit_code"] == 4
    finally:
        holder.kill()
        holder.wait()
    # the holder is gone: the lock is stale and taken over
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert not lock.exists()


def test_json_log_to_file_keeps_stdout_human(env):
    write_library(env, [_note(1, "Scones")])
    log = env["tmp"] / "events.jsonl"
    r = run(env, "--json-log", str(log))
    assert r.returncode == 0, r.stderr
    assert "Export completed successfully" in r.stdout
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert lines[-1]["type"] == "result"


# ── #31: sync options stay whole arguments ───────────────────────────────

def test_sync_arguments_are_passed_as_separate_words(env):
    """sync_to_notes.py is intercepted by a stub Python and never runs."""
    log = env["tmp"] / "sync-args.json"
    stub = env["tmp"] / "python-stub"
    stub.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in *sync_to_notes.py)\n"
        f"  shift; exec '{sys.executable}' -c 'import json,sys; "
        f"json.dump(sys.argv[1:], open(\"{log}\", \"w\"))' \"$@\" ;;\n"
        "esac\n"
        f"exec '{sys.executable}' \"$@\"\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    e = dict(env["env"])
    cmd = ["zsh", str(SCRIPT), "--python", str(stub), "--root-dir", str(env["root"]),
           "--sync-only", "true", "--sync-dry-run", "true", "--conflict", "local",
           "--filter-folders", "My Recipes,Work Notes"]
    r = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(log.read_text()) == ["--dry-run", "--conflict", "local",
                                           "--filter-folders", "My Recipes,Work Notes"]
