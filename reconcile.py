#!/usr/bin/env python3
"""Reconcile Apple Notes counts across all systems.

Compares:
- Apple Notes (via AppleScript)
- Tracking JSON files
- Exported files on disk (raw, html, text, md, pdf, docx)
- Qdrant vector database (if available)

Usage:
    python reconcile.py              # Full reconciliation report
    python reconcile.py --notebooks  # Break down by notebook
    python reconcile.py --fix        # Show suggestions for fixing mismatches
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path

from notes_export_utils import get_tracker
import output_format as fmt


def count_apple_notes() -> dict:
    """Count notes in Apple Notes via AppleScript. Returns {notebook: count}."""
    script = '''
    tell application "Notes"
        set output to ""
        repeat with anAccount in every account
            set accountName to name of anAccount
            repeat with aFolder in every folder of anAccount
                set folderName to name of aFolder
                set noteCount to count of notes of aFolder
                set output to output & accountName & "|" & folderName & "|" & (noteCount as string) & linefeed
            end repeat
        end repeat
        return output
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"Warning: Could not query Apple Notes: {result.stderr.strip()}", file=sys.stderr)
            return {}

        counts = {}
        for line in result.stdout.strip().split('\n'):
            if '|' not in line:
                continue
            parts = line.strip().split('|')
            if len(parts) >= 3:
                account = parts[0].strip()
                folder = parts[1].strip()
                count = int(parts[2].strip())
                key = f"{account} / {folder}"
                counts[key] = count
        return counts
    except subprocess.TimeoutExpired:
        print("Warning: Apple Notes query timed out", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"Warning: Could not query Apple Notes: {e}", file=sys.stderr)
        return {}


def count_tracking_json(tracker) -> dict:
    """Count notes in tracking JSON files. Returns {notebook: {total, active, deleted}}."""
    counts = {}
    for json_file in tracker.get_all_data_files():
        notebook = json_file.stem
        data = tracker.load_notebook_data(json_file)
        active = sum(1 for info in data.values() if 'deletedDate' not in info)
        deleted = sum(1 for info in data.values() if 'deletedDate' in info)
        has_full_id = sum(1 for info in data.values()
                         if info.get('fullNoteId') and 'deletedDate' not in info)
        counts[notebook] = {
            "total": len(data),
            "active": active,
            "deleted": deleted,
            "with_full_id": has_full_id,
        }
    return counts


def count_disk_files(tracker) -> dict:
    """Count exported files on disk by format and notebook. Returns {notebook: {format: count}}."""
    root = Path(tracker.root_directory)
    formats = {
        "raw": ".html",
        "html": ".html",
        "text": ".txt",
        "md": ".md",
        "pdf": ".pdf",
        "docx": ".docx",
    }
    uses_subdirs = tracker._uses_subdirs()

    counts = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)

    for fmt_name, ext in formats.items():
        fmt_dir = root / fmt_name
        if not fmt_dir.exists():
            continue

        if uses_subdirs:
            for subdir in sorted(fmt_dir.iterdir()):
                if subdir.is_dir():
                    file_count = len(list(subdir.glob(f"*{ext}")))
                    if file_count > 0:
                        counts[subdir.name][fmt_name] = file_count
                        totals[fmt_name] += file_count
        else:
            file_count = len(list(fmt_dir.glob(f"*{ext}")))
            counts["(flat)"][fmt_name] = file_count
            totals[fmt_name] += file_count

    counts["_totals"] = dict(totals)
    return dict(counts)


def count_qdrant() -> dict:
    """Count points in Qdrant. Returns {collection, points, unique_notes}."""
    try:
        from qdrant_integration import QdrantHTTP, _get_config
        config = _get_config()
        client = QdrantHTTP(config["qdrant_url"], api_key=config.get("qdrant_api_key", ""))
        collection = config["collection"]

        if not client.collection_exists(collection):
            return {"available": True, "collection": collection, "points": 0, "unique_notes": 0}

        total_points = client.count(collection)

        # Count unique notes by scrolling payloads
        unique_notes = set()
        offset = None
        while True:
            points, next_offset = client.scroll(collection, limit=100, offset=offset)
            for p in points:
                payload = p.get("payload", {})
                note_id = payload.get("note_id", "")
                notebook = payload.get("notebook", "")
                if note_id:
                    unique_notes.add((notebook, note_id))
            if next_offset is None:
                break
            offset = next_offset

        # Count by notebook
        notebook_counts = defaultdict(int)
        for notebook, _ in unique_notes:
            notebook_counts[notebook] += 1

        return {
            "available": True,
            "collection": collection,
            "points": total_points,
            "unique_notes": len(unique_notes),
            "by_notebook": dict(notebook_counts),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def get_tracked_notes(tracker) -> dict:
    """Get all tracked notes keyed by notebook. Returns {notebook: {note_id: info}}."""
    result = {}
    for json_file in tracker.get_all_data_files():
        notebook = json_file.stem
        data = tracker.load_notebook_data(json_file)
        result[notebook] = data
    return result


def get_disk_filenames(tracker) -> dict:
    """Get filenames on disk by format and notebook. Returns {notebook: {format: set(stems)}}."""
    root = Path(tracker.root_directory)
    formats = {
        "raw": ".html", "html": ".html", "text": ".txt",
        "md": ".md", "pdf": ".pdf", "docx": ".docx",
    }
    uses_subdirs = tracker._uses_subdirs()
    result = defaultdict(lambda: defaultdict(set))

    for fmt_name, ext in formats.items():
        fmt_dir = root / fmt_name
        if not fmt_dir.exists():
            continue
        if uses_subdirs:
            for subdir in fmt_dir.iterdir():
                if subdir.is_dir():
                    for f in subdir.glob(f"*{ext}"):
                        result[subdir.name][fmt_name].add(f.stem)
        else:
            for f in fmt_dir.glob(f"*{ext}"):
                result["(flat)"][fmt_name].add(f.stem)
    return dict(result)


def get_qdrant_note_ids() -> dict:
    """Get note IDs indexed in Qdrant. Returns {notebook: set(note_id)}."""
    try:
        from qdrant_integration import QdrantHTTP, _get_config
        config = _get_config()
        client = QdrantHTTP(config["qdrant_url"], api_key=config.get("qdrant_api_key", ""))
        collection = config["collection"]
        if not client.collection_exists(collection):
            return {}

        result = defaultdict(set)
        offset = None
        while True:
            points, next_offset = client.scroll(collection, limit=100, offset=offset)
            for p in points:
                payload = p.get("payload", {})
                result[payload.get("notebook", "")].add(payload.get("note_id", ""))
            if next_offset is None:
                break
            offset = next_offset
        return dict(result)
    except Exception:
        return {}


def find_specific_discrepancies(tracker, disk_files, tracked_notes, qdrant_ids) -> list:
    """Find and describe specific notes that are mismatched."""
    details = []

    for notebook, notes in tracked_notes.items():
        active_notes = {nid: info for nid, info in notes.items() if "deletedDate" not in info}
        deleted_notes = {nid: info for nid, info in notes.items() if "deletedDate" in info}
        active_filenames = {info.get("filename", "") for info in active_notes.values() if info.get("filename")}

        # Notes missing fullNoteId
        missing_fid = [info.get("filename", nid) for nid, info in active_notes.items()
                       if not info.get("fullNoteId")]
        if missing_fid:
            details.append(f"\n  [{notebook}] Missing fullNoteId ({len(missing_fid)}):")
            for fn in sorted(missing_fid)[:10]:
                details.append(f"    - {fn}")
            if len(missing_fid) > 10:
                details.append(f"    ... and {len(missing_fid) - 10} more")

        # Disk files without tracking entry (orphans)
        if notebook in disk_files:
            for fmt in ["raw", "md", "html"]:
                fmt_stems = disk_files[notebook].get(fmt, set())
                orphans = fmt_stems - active_filenames
                # Also exclude deleted note filenames
                deleted_filenames = {info.get("filename", "") for info in deleted_notes.values()}
                orphans = orphans - deleted_filenames
                if orphans:
                    details.append(f"\n  [{notebook}] Orphan {fmt}/ files (on disk but not tracked, {len(orphans)}):")
                    for fn in sorted(orphans)[:10]:
                        details.append(f"    - {fn}")
                    if len(orphans) > 10:
                        details.append(f"    ... and {len(orphans) - 10} more")
                    break  # Only report once per notebook (raw/md/html are same set)

        # Tracked notes without disk files
        if notebook in disk_files:
            raw_stems = disk_files[notebook].get("raw", set())
            missing_disk = active_filenames - raw_stems
            if missing_disk:
                details.append(f"\n  [{notebook}] Tracked but no raw file on disk ({len(missing_disk)}):")
                for fn in sorted(missing_disk)[:10]:
                    details.append(f"    - {fn}")
                if len(missing_disk) > 10:
                    details.append(f"    ... and {len(missing_disk) - 10} more")

            # Tracked with raw but missing markdown
            md_stems = disk_files[notebook].get("md", set())
            has_raw_no_md = (active_filenames & raw_stems) - md_stems
            if has_raw_no_md:
                details.append(f"\n  [{notebook}] Has raw HTML but no markdown ({len(has_raw_no_md)}):")
                for fn in sorted(has_raw_no_md)[:10]:
                    details.append(f"    - {fn}")
                if len(has_raw_no_md) > 10:
                    details.append(f"    ... and {len(has_raw_no_md) - 10} more")

        # Tracked notes missing from Qdrant
        if qdrant_ids:
            qdrant_notebook_ids = qdrant_ids.get(notebook, set())
            active_ids = set(active_notes.keys())
            missing_qdrant = active_ids - qdrant_notebook_ids
            if missing_qdrant:
                missing_names = [active_notes[nid].get("filename", nid) for nid in missing_qdrant]
                details.append(f"\n  [{notebook}] Not in Qdrant ({len(missing_qdrant)}):")
                for fn in sorted(missing_names)[:10]:
                    details.append(f"    - {fn}")
                if len(missing_names) > 10:
                    details.append(f"    ... and {len(missing_names) - 10} more")

        # Deleted notes still on disk
        for nid, info in deleted_notes.items():
            fn = info.get("filename", "")
            if fn and notebook in disk_files:
                still_on_disk = []
                for fmt in ["raw", "md", "html", "pdf", "docx"]:
                    if fn in disk_files[notebook].get(fmt, set()):
                        still_on_disk.append(fmt)
                if still_on_disk:
                    details.append(f"\n  [{notebook}] Deleted note still on disk: {fn}")
                    details.append(f"    Formats: {', '.join(still_on_disk)}")
                    details.append(f"    Deleted: {info.get('deletedDate', 'unknown')}")

    return details


def _sanitize_notebook_name(account: str, folder: str) -> str:
    """Convert account/folder names to the format used in subdirectory names."""
    for char in ['/', ':', '\\', '|', '<', '>', '"', "'", '?', '*', '_', ' ', '.', ',']:
        account = account.replace(char, '-')
        folder = folder.replace(char, '-')
    # Consolidate dashes
    import re
    account = re.sub(r'-+', '-', account).strip('-')
    folder = re.sub(r'-+', '-', folder).strip('-')
    return f"{account}-{folder}"


def run_reconciliation(show_notebooks: bool = False, show_fix: bool = False,
                       show_details: bool = False, skip_apple: bool = False,
                       skip_qdrant: bool = False):
    """Run full reconciliation and print report."""
    tracker = get_tracker()

    print("=" * 60)
    print("APPLE NOTES RECONCILIATION REPORT")
    print("=" * 60)

    # 1. Apple Notes
    print("\n--- Apple Notes (live) ---")
    if skip_apple:
        apple_total = None
        print("  (skipped — using tracking JSON only)")
    else:
        apple_counts = count_apple_notes()
        if apple_counts:
            apple_total = sum(apple_counts.values())
            fmt.emit("count", source="apple_notes", total=apple_total, by_notebook=apple_counts)
            print(f"Total notes in Apple Notes: {apple_total}")
            if show_notebooks:
                for notebook, count in sorted(apple_counts.items()):
                    print(f"  {notebook}: {count}")
        else:
            apple_total = None
            print("  (could not query Apple Notes)")

    # 2. Tracking JSON
    print("\n--- Tracking JSON ---")
    json_counts = count_tracking_json(tracker)
    json_active_total = sum(c["active"] for c in json_counts.values())
    json_deleted_total = sum(c["deleted"] for c in json_counts.values())
    json_full_id_total = sum(c["with_full_id"] for c in json_counts.values())
    fmt.emit("count", source="tracking_json", active=json_active_total,
             deleted=json_deleted_total, with_full_id=json_full_id_total)
    print(f"Active notes tracked: {json_active_total}")
    print(f"Deleted notes tracked: {json_deleted_total}")
    print(f"With fullNoteId (sync-ready): {json_full_id_total}")
    if show_notebooks:
        for notebook, counts in sorted(json_counts.items()):
            print(f"  {notebook}: {counts['active']} active, {counts['deleted']} deleted, "
                  f"{counts['with_full_id']} with fullNoteId")

    # 3. Disk files
    print("\n--- Exported Files on Disk ---")
    disk_counts = count_disk_files(tracker)
    totals = disk_counts.get("_totals", {})
    disk_counts_for_details = {k: v for k, v in disk_counts.items() if k != "_totals"}
    fmt.emit("count", source="disk", **{k: v for k, v in totals.items()})
    for fmt_name in ["raw", "html", "text", "md", "pdf", "docx"]:
        count = totals.get(fmt_name, 0)
        if count > 0:
            print(f"  {fmt_name}/: {count} files")
    if show_notebooks:
        print()
        for notebook in sorted(disk_counts_for_details.keys()):
            fmt_counts = disk_counts_for_details[notebook]
            parts = [f"{fmt}: {c}" for fmt, c in sorted(fmt_counts.items())]
            print(f"  {notebook}: {', '.join(parts)}")

    # 4. Qdrant
    print("\n--- Qdrant Vector Database ---")
    if skip_qdrant:
        qdrant = {"available": False}
        print("  (skipped)")
    else:
        qdrant = count_qdrant()
        if qdrant.get("available"):
            fmt.emit("count", source="qdrant", collection=qdrant['collection'],
                     points=qdrant['points'], unique_notes=qdrant['unique_notes'],
                     by_notebook=qdrant.get('by_notebook', {}))
            print(f"Collection: {qdrant['collection']}")
            print(f"Total points (chunks): {qdrant['points']}")
            print(f"Unique notes indexed: {qdrant['unique_notes']}")
            if show_notebooks and qdrant.get("by_notebook"):
                for notebook, count in sorted(qdrant["by_notebook"].items()):
                    print(f"  {notebook}: {count} notes")
        else:
            print(f"  Not available: {qdrant.get('error', 'Qdrant not running')}")

    # 5. Comparison
    print("\n--- Comparison ---")
    print(f"{'Source':<30} {'Count':>8}")
    print("-" * 40)
    if apple_total is not None:
        print(f"{'Apple Notes (live)':<30} {apple_total:>8}")
    print(f"{'Tracking JSON (active)':<30} {json_active_total:>8}")
    print(f"{'Tracking JSON (+ deleted)':<30} {json_active_total + json_deleted_total:>8}")
    raw_count = totals.get("raw", 0)
    if raw_count:
        print(f"{'Disk: raw HTML files':<30} {raw_count:>8}")
    md_count = totals.get("md", 0)
    if md_count:
        print(f"{'Disk: markdown files':<30} {md_count:>8}")
    if qdrant.get("available") and qdrant["unique_notes"] > 0:
        print(f"{'Qdrant (unique notes)':<30} {qdrant['unique_notes']:>8}")
        print(f"{'Qdrant (chunks)':<30} {qdrant['points']:>8}")

    # 6. Discrepancies
    print("\n--- Discrepancies ---")
    issues = []

    if apple_total is not None and apple_total != json_active_total:
        diff = apple_total - json_active_total
        if diff > 0:
            issues.append(f"Apple Notes has {diff} more notes than tracking JSON. "
                          "Run a full export: exportnotes.zsh --update-all")
        else:
            issues.append(f"Tracking JSON has {-diff} more active notes than Apple Notes. "
                          "These may have been deleted. Run export to detect deletions.")

    if raw_count and raw_count != json_active_total:
        issues.append(f"Raw HTML count ({raw_count}) differs from tracked active ({json_active_total}).")

    if json_full_id_total < json_active_total:
        missing = json_active_total - json_full_id_total
        issues.append(f"{missing} notes missing fullNoteId (needed for sync). "
                      "Run: exportnotes.zsh --update-all")

    if qdrant.get("available") and qdrant["unique_notes"] > 0:
        if qdrant["unique_notes"] != json_active_total:
            diff = json_active_total - qdrant["unique_notes"]
            if diff > 0:
                issues.append(f"Qdrant is missing {diff} notes. "
                              "Run: python qdrant_integration.py sync")
            else:
                issues.append(f"Qdrant has {-diff} more notes than tracking JSON. "
                              "Run: python qdrant_integration.py sync (will clean up)")

    if not issues:
        fmt.emit("summary", command="reconcile", discrepancies=0)
        print("  No discrepancies found.")
    else:
        fmt.emit("summary", command="reconcile", discrepancies=len(issues))
        for issue in issues:
            fmt.emit("discrepancy", issue=issue)
            print(f"  * {issue}")

    # 7. Specific discrepancies (opt-in, can be slow with Qdrant)
    if show_details:
        print("\n--- Specific Exceptions ---")
        tracked_notes = get_tracked_notes(tracker)
        qdrant_note_ids = get_qdrant_note_ids() if qdrant.get("available") else {}
        disk_filenames = get_disk_filenames(tracker)
        details = find_specific_discrepancies(tracker, disk_filenames, tracked_notes, qdrant_note_ids)
        if details:
            for line in details:
                fmt.emit("detail", line=line.strip()) if line.strip() else None
                print(line)
        else:
            print("  No specific exceptions found.")

    if show_fix and issues:
        print("\n--- Suggested Fix ---")
        print("  1. exportnotes.zsh --update-all --convert-markdown")
        print("  2. python qdrant_integration.py sync --force")

    print("\n" + "=" * 60)
    fmt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Apple Notes counts across all systems")
    parser.add_argument("--notebooks", action="store_true",
                        help="Show per-notebook breakdown")
    parser.add_argument("--details", action="store_true",
                        help="List specific notes that are exceptions")
    parser.add_argument("--fix", action="store_true",
                        help="Show suggestions for fixing mismatches")
    parser.add_argument("--skip-apple", action="store_true",
                        help="Skip querying Apple Notes (faster, uses tracking JSON only)")
    parser.add_argument("--skip-qdrant", action="store_true",
                        help="Skip querying Qdrant")
    fmt.add_json_arg(parser)
    args = parser.parse_args()
    fmt.setup_from_args(args)

    run_reconciliation(show_notebooks=args.notebooks, show_fix=args.fix,
                       show_details=args.details, skip_apple=args.skip_apple,
                       skip_qdrant=args.skip_qdrant)


if __name__ == "__main__":
    main()
