#!/usr/bin/env python3
"""One EPUB per Notes folder (``--epub-books folder``), in epub-books/.

Each note of the folder is a chapter (its HTML output as XHTML, images
packaged once per book by content hash); the table of contents lists the
note titles. Order: ``--epub-book-order modified|created`` (newest first) or
``title`` (A-Z). Subfolders: ``--epub-book-subfolders separate`` (default:
each folder its own book) or ``nested`` (a top-level folder's book holds its
subfolders as parts, with a nested table of contents; subfolders get no book
of their own).

A book is rebuilt only when its fingerprint changes: its notes, their order,
their HTML or images, titles and dates, or the options. A folder whose notes
are all gone (deleted, moved away, or the folder deleted) loses its book:
the file is removed and a tombstone kept. Locked notes are left out and
counted (``skipped_notes``). State: data/.epub_books.json, read by
build_manifest.py for the manifest's ``books`` / ``deleted_books``.

Usage: build_epub_books.py --root DIR
Environment: NOTES_EXPORT_EPUB_BOOK_ORDER, NOTES_EXPORT_EPUB_BOOK_SUBFOLDERS,
NOTES_EXPORT_EPUB_LANGUAGE.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import events
from epub_builder import (BookMeta, Chapter, ImageStore, NavNode, build_epub, html_to_xhtml, identifier_urn,
                          write_if_changed)
from export_layout import iter_trackers, output_paths, rel
from tracker_io import read_json, write_json_atomic

BOOKS_DIR = "epub-books"
STATE_NAME = ".epub_books.json"
BUILDER_VERSION = 1   # bump when the book layout changes, so every book is rebuilt


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_segment(name: str) -> str:
    name = re.sub(r'[/\\:\x00-\x1f]', "-", name or "").strip()
    name = name.lstrip(".") or "untitled"
    return name[:120]


def state_path(root: Path) -> Path:
    return root / "data" / STATE_NAME


def load_state(root: Path) -> dict:
    p = state_path(root)
    data = read_json(p) if p.exists() else {}
    data.setdefault("books", {})
    data.setdefault("deleted", {})
    return data


def active_notes(root: Path) -> Dict[str, Tuple[str, str, dict]]:
    """fullNoteId -> (tracker, note id, record), as build_manifest picks them."""
    active: Dict[str, Tuple[str, str, dict]] = {}
    for json_file, data in iter_trackers(root):
        tracker = json_file.stem
        for note_id, rec in data.items():
            if not isinstance(rec, dict) or "deletedDate" in rec:
                continue
            full_id = rec.get("fullNoteId") or f"legacy:{tracker}/{note_id}"
            current = active.get(full_id)
            if current and current[2].get("lastExported", "") >= rec.get("lastExported", ""):
                continue
            active[full_id] = (tracker, note_id, rec)
    return active


def _timestamp(iso: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() if iso else None
    except ValueError:
        return None


def _sort_key(order: str):
    if order == "title":
        return lambda n: ((n["title"] or "").casefold(), n["id"])
    field = "created" if order == "created" else "modified"

    def key(n):  # newest first; notes without a date last
        ts = _timestamp(n[field])
        return (ts is None, -(ts or 0.0), n["id"])
    return key


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(root: Path):
    """Notes grouped by (account id, folder path)."""
    folders: Dict[Tuple[str, Tuple[str, ...]], dict] = {}
    for full_id, (tracker, note_id, rec) in sorted(active_notes(root).items()):
        path = tuple(rec.get("folderPath") or [])
        if not path:
            continue
        account_id = rec.get("accountId") or rec.get("account") or "unknown"
        f = folders.setdefault((account_id, path), {"account_id": account_id, "account": rec.get("account") or "",
                                                     "folder_path": list(path), "folder_ids": set(),
                                                     "notes": [], "skipped": 0})
        if rec.get("folderId"):
            f["folder_ids"].add(rec["folderId"])
        html = output_paths(root, tracker, rec).get("html")
        if rec.get("locked") in (True, "1", "true") or not html or not html.is_file():
            f["skipped"] += 1
            continue
        f["notes"].append({"id": full_id, "title": rec.get("title") or rec.get("filename", "").replace("-", " "),
                           "modified": rec.get("modifiedAt"), "created": rec.get("createdAt"), "html": html})
    return folders


def folder_id_of(f: dict) -> str:
    ids = sorted(f["folder_ids"])
    return ids[0] if ids else "path:" + "/".join(f["folder_path"])


def plan_books(folders: dict, subfolders: str) -> List[dict]:
    """Each book: {id, account_id, folder_id, folder_path, parts: [(folder, [notes])], nested}."""
    books = []
    if subfolders == "nested":
        tops: Dict[Tuple[str, str], List[dict]] = {}
        for (account_id, path), f in folders.items():
            tops.setdefault((account_id, path[0]), []).append(f)
        for (account_id, top), members in sorted(tops.items()):
            members.sort(key=lambda f: [p.casefold() for p in f["folder_path"]])
            head = next((f for f in members if len(f["folder_path"]) == 1), None)
            folder_id = folder_id_of(head) if head else "path:" + top
            books.append({"account_id": account_id, "account": members[0]["account"], "folder_id": folder_id,
                          "folder_path": [top], "members": members,
                          "nested_folders": sorted(folder_id_of(f) for f in members if len(f["folder_path"]) > 1
                                                   and f["notes"])})
    else:
        for (account_id, path), f in sorted(folders.items()):
            books.append({"account_id": account_id, "account": f["account"], "folder_id": folder_id_of(f),
                          "folder_path": list(path), "members": [f], "nested_folders": []})
    for b in books:
        b["id"] = f"{b['account_id']}/{b['folder_id']}"
        b["skipped_notes"] = sum(f["skipped"] for f in b["members"])
    return [b for b in books if any(f["notes"] for f in b["members"])]


def book_rel_path(book: dict) -> str:
    segs = [safe_segment(book["account"] or "account")] + [safe_segment(p) for p in book["folder_path"]]
    return "/".join([BOOKS_DIR] + segs[:-1] + [segs[-1] + ".epub"])


def ordered(book: dict, order: str) -> List[Tuple[dict, List[dict]]]:
    key = _sort_key(order)
    return [(f, sorted(f["notes"], key=key)) for f in book["members"]]


def fingerprint(book: dict, parts, order: str, subfolders: str, language: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([BUILDER_VERSION, order, subfolders, language, book["folder_path"], book["account"]]).encode())
    for f, notes in parts:
        h.update(json.dumps(f["folder_path"]).encode())
        for n in notes:
            h.update(json.dumps([n["id"], n["title"], n["modified"], n["created"]]).encode())
            h.update(_file_sha(n["html"]).encode())
            for img in _linked(n["html"]):
                h.update(img.name.encode() + _file_sha(img).encode())
    return h.hexdigest()


def _linked(html: Path) -> List[Path]:
    from urllib.parse import unquote, urlparse
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
    out = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:") or urlparse(src).scheme:
            continue
        p = html.parent / unquote(src.split("#")[0].split("?")[0])
        if p.is_file() and p not in out:
            out.append(p)
    return out


def render(book: dict, parts, language: str, subfolders: str) -> bytes:
    images = ImageStore()
    chapters: List[Chapter] = []
    nav: List[NavNode] = []
    top_path = book["folder_path"]
    part_nodes: Dict[Tuple[str, ...], NavNode] = {}

    def warn_for(n):
        def warn(msg):
            print(f"Warning ({n['title']}): {msg}")
            events.emit("message", level="warning", stage="books", note_id=n["id"], message=f"{n['title']}: {msg}")
        return warn

    for f, notes in parts:
        if subfolders == "nested" and len(f["folder_path"]) > len(top_path):
            # find (or make) the part node for this subfolder, under its parent's
            parent_list = nav
            for depth in range(len(top_path) + 1, len(f["folder_path"]) + 1):
                key = tuple(f["folder_path"][:depth])
                if key not in part_nodes:
                    node = NavNode(f["folder_path"][depth - 1])
                    part_nodes[key] = node
                    parent_list.append(node)
                parent_list = part_nodes[key].children
            target = parent_list
        else:
            target = nav
        for n in notes:
            body = html_to_xhtml(n["html"].read_text(encoding="utf-8", errors="replace"), n["html"].parent,
                                 images, warn_for(n))
            c = Chapter(f"ch{len(chapters) + 1:04d}", n["title"], body, f"chapter-{len(chapters) + 1:04d}.xhtml")
            chapters.append(c)
            target.append(NavNode(n["title"], c))
    dates_m = [n["modified"] for _, ns in parts for n in ns if n["modified"]]
    dates_c = [n["created"] for _, ns in parts for n in ns if n["created"]]
    meta = BookMeta(identifier=identifier_urn("folder", book["id"]), title=book["folder_path"][-1],
                    language=language, modified=max(dates_m) if dates_m else None,
                    created=min(dates_c) if dates_c else None,
                    subjects=[s for s in (book["account"], "/".join(book["folder_path"])) if s])
    return build_epub(meta, chapters, images, nav)


def _remove(root: Path, relpath: str) -> bool:
    p = (root / relpath)
    try:
        p.resolve().relative_to((root / BOOKS_DIR).resolve())
    except ValueError:
        return False
    if p.is_file():
        p.unlink()
        parent = p.parent
        while parent != root / BOOKS_DIR and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        return True
    return False


def build(root: Path, order: str, subfolders: str, language: str) -> dict:
    root = root.resolve()
    state = load_state(root)
    books = plan_books(collect(root), subfolders)
    total = len(books)
    events.progress("books", 0, total, force=True, unit="books")
    built = unchanged = failed = 0
    new_books = {}
    for i, book in enumerate(books, 1):
        relpath = book_rel_path(book)
        parts = ordered(book, order)
        try:
            fp = fingerprint(book, parts, order, subfolders, language)
            old = state["books"].get(book["id"])
            if not (old and old.get("fingerprint") == fp and old.get("path") == relpath and (root / relpath).is_file()):
                data = render(book, parts, language, subfolders)
                write_if_changed(root / relpath, data)
                built += 1
                print(f"Built: {relpath}")
            else:
                unchanged += 1
            if old and old.get("path") and old["path"] != relpath:
                _remove(root, old["path"])  # the folder was renamed or moved
        except Exception as e:
            failed += 1
            print(f"Error building {relpath}: {e}")
            events.emit("message", level="error", stage="books", message=f"{relpath}: {e}")
            if book["id"] in state["books"]:
                new_books[book["id"]] = state["books"][book["id"]]
            continue
        new_books[book["id"]] = {
            "account_id": book["account_id"], "folder_id": book["folder_id"], "folder_path": book["folder_path"],
            "title": book["folder_path"][-1], "path": relpath, "fingerprint": fp,
            "notes": [n["id"] for _, ns in parts for n in ns], "nested_folders": book["nested_folders"],
            "skipped_notes": book["skipped_notes"],
        }
        state["deleted"].pop(book["id"], None)
        events.progress("books", i, total, unit="books", failed=failed)
    removed = 0
    for book_id, old in state["books"].items():
        if book_id in new_books:
            continue
        _remove(root, old.get("path", ""))
        removed += 1
        state["deleted"][book_id] = {"id": book_id, "folder_path": old.get("folder_path", []),
                                     "path": old.get("path"), "deleted_at": now_iso()}
        print(f"Removed: {old.get('path')} (the folder has no notes now)")
    state["books"] = new_books
    state["options"] = {"order": order, "subfolders": subfolders, "language": language}
    (root / "data").mkdir(parents=True, exist_ok=True)
    write_json_atomic(state_path(root), state)
    events.progress("books", total, total, force=True, unit="books", failed=failed)
    print(f"Books: {built} built, {unchanged} unchanged, {removed} removed, {failed} failed")
    return {"built": built, "unchanged": unchanged, "removed": removed, "failed": failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.getenv("NOTES_EXPORT_ROOT_DIR"))
    ap.add_argument("--order", default=os.getenv("NOTES_EXPORT_EPUB_BOOK_ORDER", "modified"),
                    choices=["modified", "created", "title"])
    ap.add_argument("--subfolders", default=os.getenv("NOTES_EXPORT_EPUB_BOOK_SUBFOLDERS", "separate"),
                    choices=["separate", "nested"])
    ap.add_argument("--language", default=os.getenv("NOTES_EXPORT_EPUB_LANGUAGE", "") or "und")
    args = ap.parse_args(argv)
    if not args.root:
        ap.error("--root is required")
    result = build(Path(args.root), args.order, args.subfolders, args.language)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
