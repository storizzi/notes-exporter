#!/usr/bin/env python3
"""Search exported Apple Notes for text or regex patterns.

Usage:
    python query_notes.py "search term"
    python query_notes.py -E "regex pattern"
    python query_notes.py --format md "search term"
    python query_notes.py -i "case insensitive"
    python query_notes.py -c 2 "term"          # show 2 lines of context
    python query_notes.py -l "term"             # list matching files only
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from notes_export_utils import get_tracker
import output_format as outfmt


def parse_apple_date(date_string: str):
    """Parse Apple Notes date format to datetime object."""
    if not date_string:
        return None
    date_string = date_string.replace('\u202f', ' ')
    formats = [
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %d %B %Y at %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    return None


def parse_date_arg(date_str: str):
    """Parse a date argument. Accepts ISO format or common formats."""
    for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: '{date_str}'. Use YYYY-MM-DD format.")


def parse_timespan(span: str) -> timedelta:
    """Parse a human-readable timespan like '5h', '3d', '2w', '2m', '1y'.

    Supported units:
        s = seconds, min = minutes, h = hours, d = days,
        w = weeks, m = months (30 days), y = years (365 days)
    """
    span = span.strip().lower()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|sec|min|h|hr|hours?|d|days?|w|weeks?|m|months?|y|years?)$', span)
    if not match:
        raise ValueError(
            f"Cannot parse timespan: '{span}'. "
            "Use format like: 5h, 3d, 2w, 2m, 1y"
        )
    value = float(match.group(1))
    unit = match.group(2)

    if unit in ('s', 'sec'):
        return timedelta(seconds=value)
    elif unit in ('min',):
        return timedelta(minutes=value)
    elif unit in ('h', 'hr', 'hour', 'hours'):
        return timedelta(hours=value)
    elif unit in ('d', 'day', 'days'):
        return timedelta(days=value)
    elif unit in ('w', 'week', 'weeks'):
        return timedelta(weeks=value)
    elif unit in ('m', 'month', 'months'):
        return timedelta(days=value * 30)
    elif unit in ('y', 'year', 'years'):
        return timedelta(days=value * 365)
    raise ValueError(f"Unknown time unit: '{unit}'")


def search_file(file_path: Path, pattern: re.Pattern,
                context_lines: int = 0, files_only: bool = False,
                max_matches: int = 0) -> list:
    """Search a single file for the pattern. Returns list of match dicts."""
    matches = []
    try:
        # Try multiple encodings
        content = None
        for encoding in ['utf-8', 'MacRoman', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            return matches

        lines = content.splitlines()

        for i, line in enumerate(lines):
            if pattern.search(line):
                if files_only:
                    matches.append({'file': file_path, 'line_num': i + 1})
                    return matches  # One match is enough for files-only mode

                # Gather context
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = []
                for j in range(start, end):
                    prefix = '>' if j == i else ' '
                    context.append(f"  {prefix} {j + 1:4d} | {lines[j]}")

                matches.append({
                    'file': file_path,
                    'line_num': i + 1,
                    'line': line,
                    'context': '\n'.join(context),
                })

                if max_matches and len(matches) >= max_matches:
                    break

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return matches


def get_note_title(file_path: Path, tracker) -> str:
    """Try to get the original note title from tracking JSON."""
    # Find the matching JSON data file
    folder_name = file_path.parent.name if tracker._uses_subdirs() else None
    filename_stem = file_path.stem

    for json_file in tracker.get_all_data_files():
        if folder_name and json_file.stem != folder_name:
            continue
        data = tracker.load_notebook_data(json_file)
        for note_id, info in data.items():
            if info.get('filename') == filename_stem:
                # Reconstruct a readable title from the filename
                return filename_stem
    return filename_stem


def note_has_images(file_path: Path, tracker) -> bool:
    """Check if a note has associated images.

    Checks for:
    1. An attachments/ directory with files matching the note's filename
    2. Images placed beside the document (--images-beside-docs mode)
    3. Base64-embedded images in raw HTML
    """
    stem = file_path.stem

    # Check attachments/ subdirectory
    attachments_dir = file_path.parent / 'attachments'
    if attachments_dir.exists():
        for f in attachments_dir.iterdir():
            if f.name.startswith(stem + '-attachment-'):
                return True

    # Check images beside document
    img_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff', '.bmp'}
    for f in file_path.parent.iterdir():
        if f.stem.startswith(stem + '-attachment-') and f.suffix.lower() in img_extensions:
            return True

    # For HTML files, also check for embedded base64 images in raw source
    if file_path.suffix == '.html':
        raw_dir = Path(tracker.root_directory) / 'raw'
        if tracker._uses_subdirs():
            raw_file = raw_dir / file_path.parent.name / file_path.name
        else:
            raw_file = raw_dir / file_path.name
        if raw_file.exists():
            try:
                with open(raw_file, 'r', encoding='utf-8') as f:
                    content = f.read(50000)  # Check first 50KB
                if 'data:image' in content:
                    return True
            except Exception:
                pass

    return False


def get_note_dates(file_path: Path, tracker, _cache={}) -> dict:
    """Look up created/modified dates for a note from tracking JSON.

    Returns dict with 'created' and 'modified' as datetime objects (or None).
    """
    # Build lookup cache on first call
    if not _cache:
        for json_file in tracker.get_all_data_files():
            data = tracker.load_notebook_data(json_file)
            folder_name = json_file.stem
            for note_id, info in data.items():
                fn = info.get('filename', '')
                if fn:
                    _cache[(folder_name, fn)] = {
                        'created': parse_apple_date(info.get('created', '')),
                        'modified': parse_apple_date(info.get('modified', '')),
                    }

    stem = file_path.stem
    folder = file_path.parent.name if tracker._uses_subdirs() else ''

    # Try exact match first
    key = (folder, stem)
    if key in _cache:
        return _cache[key]

    # Try any folder
    for (f, fn), dates in _cache.items():
        if fn == stem:
            return dates

    return {'created': None, 'modified': None}


def passes_date_filter(note_dates: dict,
                       created_after=None, created_before=None,
                       modified_after=None, modified_before=None) -> bool:
    """Check if a note's dates pass the filter criteria."""
    created = note_dates.get('created')
    modified = note_dates.get('modified')

    if created_after and (not created or created < created_after):
        return False
    if created_before and (not created or created > created_before):
        return False
    if modified_after and (not modified or modified < modified_after):
        return False
    if modified_before and (not modified or modified > modified_before):
        return False

    return True


def run_query(search_term: str, formats: list, use_regex: bool = False,
              case_insensitive: bool = False, context_lines: int = 0,
              files_only: bool = False, max_matches: int = 0,
              filter_folders: str = None, has_images: bool = None,
              created_after=None, created_before=None,
              modified_after=None, modified_before=None):
    """Search exported notes for a pattern."""
    tracker = get_tracker()
    root = Path(tracker.root_directory)

    # Compile the pattern
    flags = re.IGNORECASE if case_insensitive else 0
    if use_regex:
        try:
            pattern = re.compile(search_term, flags)
        except re.error as e:
            print(f"Error: Invalid regex pattern: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        pattern = re.compile(re.escape(search_term), flags)

    # Map format names to directories and extensions
    format_map = {
        'md': ('md', '.md'),
        'markdown': ('md', '.md'),
        'html': ('html', '.html'),
        'text': ('text', '.txt'),
        'txt': ('text', '.txt'),
        'raw': ('raw', '.html'),
    }

    # Determine which directories to search
    search_dirs = []
    for fmt in formats:
        if fmt in format_map:
            dir_name, ext = format_map[fmt]
            search_dirs.append((root / dir_name, ext))
        else:
            print(f"Warning: Unknown format '{fmt}', skipping", file=sys.stderr)

    if not search_dirs:
        # Default: search markdown first, then text, then html
        for fmt in ['md', 'text', 'html']:
            dir_name, ext = format_map[fmt]
            d = root / dir_name
            if d.exists():
                search_dirs.append((d, ext))
                break
        if not search_dirs:
            print("Error: No exported note files found. Run an export first.", file=sys.stderr)
            sys.exit(1)

    # Parse folder filter
    folder_filter = set()
    if filter_folders:
        folder_filter = {f.strip() for f in filter_folders.split(',')}

    # Search
    total_matches = 0
    matching_files = 0

    for search_dir, ext in search_dirs:
        if not search_dir.exists():
            continue

        # Collect files to search
        files = sorted(search_dir.rglob(f'*{ext}'))

        for file_path in files:
            # Skip conflict files
            if file_path.name.endswith('.conflict.md'):
                continue

            # Apply folder filter
            if folder_filter and tracker._uses_subdirs():
                parent_name = file_path.parent.name
                if parent_name not in folder_filter:
                    # Check if any filter matches part of the folder name
                    if not any(f in parent_name for f in folder_filter):
                        continue

            # Image filter
            if has_images is not None:
                file_has_imgs = note_has_images(file_path, tracker)
                if has_images and not file_has_imgs:
                    continue
                if not has_images and file_has_imgs:
                    continue

            # Date filter
            if any(x is not None for x in [created_after, created_before,
                                           modified_after, modified_before]):
                note_dates = get_note_dates(file_path, tracker)
                if not passes_date_filter(note_dates,
                                          created_after, created_before,
                                          modified_after, modified_before):
                    continue

            matches = search_file(file_path, pattern, context_lines,
                                  files_only, max_matches)

            if matches:
                matching_files += 1
                rel_path = file_path.relative_to(root)

                if files_only:
                    print(str(rel_path))
                    outfmt.emit("match", file=str(rel_path))
                else:
                    for match in matches:
                        total_matches += 1
                        outfmt.emit("match", file=str(rel_path), line_num=match['line_num'],
                                 line=match['line'].strip())
                        print(f"\033[1m{rel_path}\033[0m:{match['line_num']}")
                        if context_lines > 0:
                            print(match['context'])
                        else:
                            print(f"  {match['line'].strip()}")
                        print()

    # Summary
    outfmt.emit("summary", total_matches=total_matches, matching_files=matching_files,
             search_type="text")
    if files_only:
        print(f"\n{matching_files} file(s) matched", file=sys.stderr)
    else:
        print(f"\n{total_matches} match(es) in {matching_files} file(s)", file=sys.stderr)
    outfmt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Search exported Apple Notes for text or regex patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s "meeting notes"              Search for literal text
  %(prog)s -E "TODO|FIXME"             Search with regex
  %(prog)s -i "project"                Case-insensitive search
  %(prog)s -c 3 "deadline"             Show 3 lines of context
  %(prog)s -l "budget"                 List matching files only
  %(prog)s --format md "recipe"        Search only markdown files
  %(prog)s --format html,text "link"   Search HTML and text files
  %(prog)s -F Notes "important"        Search only the Notes folder
  %(prog)s --has-images "photo"        Only notes with images
  %(prog)s --no-images "text only"     Only notes without images
  %(prog)s --modified-within 3d "."    Modified in last 3 days
  %(prog)s --created-within 2w "."     Created in last 2 weeks
  %(prog)s --modified-after 2026-01-15 "."  Modified after date
  %(prog)s --created-before 2025-06-01 "."  Created before date
  %(prog)s --modified-within 5h -l "."      Files modified in last 5 hours
  %(prog)s --ai-search "ideas about cooking" Semantic search via Qdrant
  %(prog)s --ai-search -n 5 "project plan"   Top 5 AI results
""")
    parser.add_argument("pattern", help="Search term or regex pattern")
    parser.add_argument("-E", "--regex", action="store_true",
                        help="Treat pattern as a regular expression")
    parser.add_argument("-i", "--ignore-case", action="store_true",
                        help="Case-insensitive search")
    parser.add_argument("-c", "--context", type=int, default=0,
                        help="Number of context lines to show (default: 0)")
    parser.add_argument("-l", "--files-only", action="store_true",
                        help="Only list matching file paths")
    parser.add_argument("-m", "--max-matches", type=int, default=0,
                        help="Maximum matches per file (0 = unlimited)")
    parser.add_argument("--format", default="",
                        help="Comma-separated formats to search: md, html, text, raw (default: auto-detect)")
    parser.add_argument("-F", "--filter-folders", default=None,
                        help="Only search in these folders (comma-separated)")
    parser.add_argument("--has-images", action="store_true", default=None,
                        help="Only show notes that have images")
    parser.add_argument("--no-images", action="store_true",
                        help="Only show notes that have no images")

    date_group = parser.add_argument_group("date filters",
        "Filter by note created/modified dates. Dates use YYYY-MM-DD format. "
        "Timespans use number+unit: 5h (hours), 3d (days), 2w (weeks), 2m (months), 1y (years).")
    date_group.add_argument("--created-after", default=None,
                        help="Notes created after this date (YYYY-MM-DD)")
    date_group.add_argument("--created-before", default=None,
                        help="Notes created before this date (YYYY-MM-DD)")
    date_group.add_argument("--modified-after", default=None,
                        help="Notes modified after this date (YYYY-MM-DD)")
    date_group.add_argument("--modified-before", default=None,
                        help="Notes modified before this date (YYYY-MM-DD)")
    date_group.add_argument("--created-within", default=None,
                        help="Notes created within timespan (e.g. 5h, 3d, 2w, 2m, 1y)")
    date_group.add_argument("--modified-within", default=None,
                        help="Notes modified within timespan (e.g. 5h, 3d, 2w, 2m, 1y)")

    ai_group = parser.add_argument_group("AI search",
        "Semantic search using Qdrant vector database. Requires Qdrant running "
        "and notes indexed (run: python qdrant_integration.py sync).")
    ai_group.add_argument("--ai-search", action="store_true",
                        help="Use semantic/AI search via Qdrant instead of text matching")
    ai_group.add_argument("-n", "--num-results", type=int, default=10,
                        help="Number of AI search results (default: 10)")
    ai_group.add_argument("--threshold", type=float, default=0.0,
                        help="Minimum similarity score for AI results (0.0-1.0)")

    outfmt.add_json_arg(parser)
    parser.add_argument("-r", "--root-dir", default=None,
                        help="Override the export root directory")

    args = parser.parse_args()
    outfmt.setup_from_args(args)

    if args.root_dir:
        os.environ['NOTES_EXPORT_ROOT_DIR'] = args.root_dir

    formats = [f.strip() for f in args.format.split(',') if f.strip()] if args.format else []

    # Resolve image filter
    image_filter = None
    if args.has_images:
        image_filter = True
    elif args.no_images:
        image_filter = False

    # Resolve date filters
    now = datetime.now()
    created_after = None
    created_before = None
    modified_after = None
    modified_before = None

    try:
        if args.created_after:
            created_after = parse_date_arg(args.created_after)
        if args.created_before:
            created_before = parse_date_arg(args.created_before)
        if args.modified_after:
            modified_after = parse_date_arg(args.modified_after)
        if args.modified_before:
            modified_before = parse_date_arg(args.modified_before)
        if args.created_within:
            created_after = now - parse_timespan(args.created_within)
        if args.modified_within:
            modified_after = now - parse_timespan(args.modified_within)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # AI search mode
    if args.ai_search:
        try:
            from qdrant_integration import QdrantNotesManager
        except ImportError as e:
            print(f"Error: Could not load Qdrant integration: {e}", file=sys.stderr)
            sys.exit(1)

        mgr = QdrantNotesManager()
        results = mgr.search(args.pattern, limit=args.num_results,
                             score_threshold=args.threshold)
        if not results:
            print("No results found.", file=sys.stderr)
            sys.exit(0)

        tracker = get_tracker()
        root = Path(tracker.root_directory)

        for i, r in enumerate(results, 1):
            notebook = r['notebook']
            filename = r['filename']

            # Find the actual file path for display
            file_path = None
            for folder in ['md', 'text', 'html']:
                if tracker._uses_subdirs():
                    candidate = root / folder / notebook / f"{filename}.md"
                else:
                    candidate = root / folder / f"{filename}.md"
                if candidate.exists():
                    file_path = candidate
                    break

            rel = str(file_path.relative_to(root)) if file_path else f"{notebook}/{filename}"
            score_pct = r['score'] * 100

            outfmt.emit("result", file=rel, score=r['score'], note_id=r['note_id'],
                     notebook=notebook, filename=filename,
                     created=r['created'], modified=r['modified'])
            if args.files_only:
                print(rel)
            else:
                print(f"{i}. \033[1m{rel}\033[0m  [{score_pct:.1f}% match]")
                if r['modified']:
                    print(f"   Modified: {r['modified']}")
                print()

        outfmt.emit("summary", total_results=len(results), search_type="ai")
        print(f"\n{len(results)} result(s) from AI search", file=sys.stderr)
        outfmt.close()
        return

    run_query(
        search_term=args.pattern,
        formats=formats,
        use_regex=args.regex,
        case_insensitive=args.ignore_case,
        context_lines=args.context,
        files_only=args.files_only,
        max_matches=args.max_matches,
        filter_folders=args.filter_folders,
        has_images=image_filter,
        created_after=created_after,
        created_before=created_before,
        modified_after=modified_after,
        modified_before=modified_before,
    )


if __name__ == "__main__":
    main()
