#!/usr/bin/env python3
"""Stand-in for ``osascript export_notes.scpt`` in end-to-end tests.

It honours the script's contract - same arguments, raw/ and text/ files,
tracking data through tracker_io.py save, data/.live_notes.tsv, the stats
file and @@ progress lines on stderr - from a JSON description of a Notes
library in $FAKE_NOTES_LIBRARY:

    {"notes": [{"account": "iCloud", "folder": ["Food", "Recipes"],
                "folder_id": "F1", "id": 12, "title": "Scones",
                "html": "<div>..</div>", "text": "..",
                "modified": "2026-03-05T07:08:09", "created": "...",
                "locked": false}],
     "fail": null | "refuse" | "crash"}

Installed by tests as an executable named ``osascript`` first on PATH.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import tracker_io as tio  # noqa: E402


def sanitize(name):
    name = re.sub(r"[/:\\|<>\"'?*_ .,\t\n\r]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "untitled"


def fill(fmt, **tokens):
    for key in ("shortaccountid", "accountid", "account", "folderpath", "path", "folder", "title", "id"):
        fmt = fmt.replace("&" + key, tokens.get(key, ""))
    return fmt


def main(argv):
    # argv: script root limit limitPerFolder prob filenameFmt subdirFmt useSubdirs updateAll
    #       includeDeleted accounts folders modifiedAfter python scriptDir exclude
    args = argv[2:] + [""] * 16
    root = Path(args[0])
    filename_fmt, subdir_fmt, use_subdirs = args[4], args[5], args[6] == "true"
    update_all = args[7] == "true"
    folder_filter = [f for f in args[10].split(",") if f]
    exclude = [f for f in args[14].split(",") if f]
    library = json.loads(Path(os.environ["FAKE_NOTES_LIBRARY"]).read_text())
    data_dir = root / "data"
    for d in ("raw", "text", "html", "data"):
        (root / d).mkdir(parents=True, exist_ok=True)

    if library.get("fail") == "refuse":
        (data_dir / "export_stats.tmp").write_text("total=0\nprocessed=0\nerrors=0\nfatal_number=-1743\n")
        print("execution error: Not authorized to send Apple events to Notes. (-1743)", file=sys.stderr)
        return 1

    folders = {}
    for note in library["notes"]:
        key = (note["account"], tuple(note["folder"]), note.get("folder_id", "/".join(note["folder"])))
        folders.setdefault(key, []).append(note)
    plan = [k for k in folders
            if (not folder_filter or k[1][-1] in folder_filter or "/".join(k[1]) in folder_filter)
            and not (k[1][-1] in exclude or "/".join(k[1]) in exclude)]
    print(f"@@PLAN\t{len(plan)}", file=sys.stderr)

    live_lines, stats = [], dict(total=0, processed=0, unchanged=0, filtered=0, locked=0, errors=0)
    for index, key in enumerate(plan, 1):
        account, path, folder_id = key
        folder_id = f"x-coredata://S/ICFolder/{folder_id}"
        account_id = "x-coredata://S/ICAccount/p1"
        safe_path = "/".join(sanitize(p) for p in path)
        if use_subdirs:
            subdir = fill(subdir_fmt, account=sanitize(account), folder=sanitize(path[-1]),
                          folderpath=safe_path, path=safe_path, accountid="S", shortaccountid="S")
            tracker = subdir.replace("%", "%25").replace("/", "%2F")
            prefix = subdir + "/"
        else:
            subdir, tracker, prefix = "", f"{sanitize(account)}-{sanitize(path[-1])}", ""
        json_path = data_dir / f"{tracker}.json"
        existing = {tio.split_line(l)[0]: tio.split_line(l) for l in tio.load_lines(json_path, False)}
        notes = folders[key]
        print(f"@@FOLDER\t{index}\t{len(plan)}\t{account}\t{'/'.join(path)}\t{len(notes)}", file=sys.stderr)
        rows = []
        for note in notes:
            nid = str(note["id"])
            full = f"x-coredata://S/ICNote/p{nid}"
            stats["total"] += 1
            sep = tio.UNIT_SEP.join(path)
            live_lines.append("\t".join(tio.escape(str(v)) for v in [
                "N", tracker, nid, full, note["title"], note.get("created", "2026-01-01T10:00:00"),
                note["modified"], account, account_id, folder_id, sep, subdir,
                "1" if note.get("locked") else "0", "0"]))
            old = existing.get(nid)
            if not update_all and old and old[2] == note["modified"]:
                stats["unchanged"] += 1
                continue
            if note.get("locked"):
                stats["locked"] += 1
                continue
            if note.get("error"):
                stats["errors"] += 1
                print(f"@@NOTE_ERROR\t{nid}\t{note['error']}", file=sys.stderr)
                live_lines.append("\t".join(["E", tracker, nid, full, tio.escape(note["error"])]))
                continue
            name = fill(filename_fmt, title=sanitize(note["title"]), id=nid)
            (root / "raw" / prefix).mkdir(parents=True, exist_ok=True)
            (root / "text" / prefix).mkdir(parents=True, exist_ok=True)
            (root / "raw" / prefix / f"{name}.html").write_text(note["html"], encoding="utf-8")
            (root / "text" / prefix / f"{name}.txt").write_text(note.get("text", ""), encoding="utf-8")
            if old and old[1] != name:  # rename: remove the old files, like handleFilenameChange
                for d, ext in (("raw", ".html"), ("html", ".html"), ("text", ".txt"), ("md", ".md")):
                    p = root / d / prefix / f"{old[1]}{ext}"
                    if p.exists():
                        p.unlink()
            rows.append("\t".join(tio.escape(str(v)) for v in [
                nid, full, name, note["title"], note.get("created", "2026-01-01T10:00:00"),
                note["modified"], "legacy created", "legacy " + note["modified"], account,
                account_id, folder_id, sep, subdir]))
            stats["processed"] += 1
            print(f"@@NOTE\t{stats['processed']}\t{nid}", file=sys.stderr)
        if rows:
            tsv = data_dir / ".save_rows.tsv"
            tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")
            subprocess.run([sys.executable, str(HERE / "tracker_io.py"), "save", str(json_path), str(tsv)],
                           check=True, capture_output=True)
            tsv.unlink()
        live_lines.append("\t".join(["F", tracker, folder_id, subdir]))
        if library.get("fail") == "crash" and index == 1:
            (data_dir / ".live_notes.tsv").write_text("\n".join(live_lines) + "\n", encoding="utf-8")
            (data_dir / "export_stats.tmp").write_text("total=1\nprocessed=1\nerrors=0\nfatal_number=-2700\n")
            print("execution error: something broke (-2700)", file=sys.stderr)
            return 1
    live_lines.append("END")
    (data_dir / ".live_notes.tsv").write_text("\n".join(live_lines) + "\n", encoding="utf-8")
    stats_text = "".join(f"{k}={v}\n" for k, v in stats.items())
    (data_dir / "export_stats.tmp").write_text(stats_text + f"folders={len(plan)}\nelapsed=1\nfatal_number=0\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
