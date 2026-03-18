"""Qdrant vector database integration for Apple Notes.

Manages note vectors in Qdrant: upsert on export/sync, delete on note removal,
and semantic search via embeddings.

Supports Ollama (local, default) or sentence-transformers for embeddings.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from notes_export_utils import NotesExportTracker, get_tracker
import output_format as fmt


# ── Configuration ──────────────────────────────────────────────────────────

DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "apple_notes"
DEFAULT_EMBEDDING_PROVIDER = "ollama"       # "ollama" or "sentence-transformers"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "mxbai-embed-large"  # 1024 dims
DEFAULT_ST_MODEL = "all-MiniLM-L6-v2"       # 384 dims


def _get_config() -> Dict[str, str]:
    return {
        "qdrant_url": os.getenv("NOTES_EXPORT_QDRANT_URL", DEFAULT_QDRANT_URL),
        "qdrant_api_key": os.getenv("NOTES_EXPORT_QDRANT_API_KEY", ""),  # For Qdrant Cloud
        "collection": os.getenv("NOTES_EXPORT_QDRANT_COLLECTION", DEFAULT_COLLECTION),
        "embedding_provider": os.getenv("NOTES_EXPORT_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER),
        "ollama_url": os.getenv("NOTES_EXPORT_OLLAMA_URL", DEFAULT_OLLAMA_URL),
        "ollama_model": os.getenv("NOTES_EXPORT_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        "st_model": os.getenv("NOTES_EXPORT_EMBEDDING_MODEL", DEFAULT_ST_MODEL),
    }


# ── Embedding Providers ───────────────────────────────────────────────────

def _embed_ollama(texts: List[str], config: Dict) -> List[List[float]]:
    """Get embeddings from a local Ollama server."""
    url = f"{config['ollama_url']}/api/embed"
    vectors = []
    for text in texts:
        # Chunks should already be right-sized, but guard against edge cases
        text = text.strip()
        if not text:
            text = "(empty note)"

        payload = json.dumps({"model": config["ollama_model"], "input": text}).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            vectors.append(result["embeddings"][0])
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise RuntimeError(f"Ollama embedding failed ({e.code}): {error_body}") from e
        except (urllib.error.URLError, KeyError, IndexError) as e:
            raise RuntimeError(f"Ollama embedding failed: {e}") from e
    return vectors


def _embed_sentence_transformers(texts: List[str], config: Dict) -> List[List[float]]:
    """Get embeddings using sentence-transformers (local)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. "
            "Install with: pip install sentence-transformers"
        )
    model = SentenceTransformer(config["st_model"])
    embeddings = model.encode(texts, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


def get_embeddings(texts: List[str], config: Optional[Dict] = None) -> List[List[float]]:
    """Get embeddings for a list of texts using the configured provider."""
    if config is None:
        config = _get_config()
    provider = config["embedding_provider"]
    if provider == "ollama":
        return _embed_ollama(texts, config)
    elif provider in ("sentence-transformers", "st"):
        return _embed_sentence_transformers(texts, config)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


def get_embedding_dimension(config: Optional[Dict] = None) -> int:
    """Determine the embedding dimension by encoding a test string."""
    if config is None:
        config = _get_config()
    vecs = get_embeddings(["test"], config)
    return len(vecs[0])


# ── Qdrant HTTP Client (no external dependency) ──────────────────────────

class QdrantHTTP:
    """Minimal Qdrant REST client using only stdlib.

    Supports both local Qdrant (Docker) and Qdrant Cloud (with API key).
    For Qdrant Cloud, set NOTES_EXPORT_QDRANT_API_KEY and use your cluster URL
    (e.g. https://your-cluster.cloud.qdrant.io:6333).
    """

    def __init__(self, url: str = DEFAULT_QDRANT_URL, api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, path: str, body: Any = None) -> Dict:
        data = json.dumps(body).encode() if body else None
        headers = {}
        if data:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["api-key"] = self.api_key
        req = urllib.request.Request(
            f"{self.url}{path}", data=data, method=method, headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise RuntimeError(f"Qdrant {method} {path} → {e.code}: {error_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot connect to Qdrant at {self.url}: {e.reason}\n"
                "Is Qdrant running? Start with: docker-compose up -d (in your qdrant directory)"
            ) from e

    def collection_exists(self, name: str) -> bool:
        try:
            self._request("GET", f"/collections/{name}")
            return True
        except RuntimeError:
            return False

    def create_collection(self, name: str, vector_size: int):
        self._request("PUT", f"/collections/{name}", {
            "vectors": {"size": vector_size, "distance": "Cosine"}
        })

    def delete_collection(self, name: str):
        self._request("DELETE", f"/collections/{name}")

    def upsert_points(self, collection: str, points: List[Dict]):
        if not points:
            return
        # Batch in chunks of 100
        for i in range(0, len(points), 100):
            batch = points[i:i + 100]
            self._request("PUT", f"/collections/{collection}/points", {"points": batch})

    def delete_points(self, collection: str, ids: List[str]):
        if not ids:
            return
        self._request("POST", f"/collections/{collection}/points/delete", {
            "points": ids,
        })

    def search(self, collection: str, vector: List[float], limit: int = 10,
               score_threshold: float = 0.0) -> List[Dict]:
        body = {"vector": vector, "limit": limit, "with_payload": True}
        if score_threshold > 0:
            body["score_threshold"] = score_threshold
        result = self._request("POST", f"/collections/{collection}/points/search", body)
        return result.get("result", [])

    def count(self, collection: str) -> int:
        result = self._request("POST", f"/collections/{collection}/points/count", {
            "exact": True
        })
        return result.get("result", {}).get("count", 0)

    def scroll(self, collection: str, limit: int = 100, offset: Optional[str] = None) -> Tuple:
        body = {"limit": limit, "with_payload": True}
        if offset:
            body["offset"] = offset
        result = self._request("POST", f"/collections/{collection}/points/scroll", body)
        points = result.get("result", {}).get("points", [])
        next_offset = result.get("result", {}).get("next_page_offset")
        return points, next_offset


# ── Notes Manager ─────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 800       # chars per chunk (~200-300 tokens for mxbai-embed-large)
DEFAULT_CHUNK_OVERLAP = 200    # overlap between chunks to preserve context at boundaries


def _get_chunk_config() -> Tuple[int, int]:
    """Get chunk size and overlap from env vars or defaults."""
    chunk_size = int(os.getenv("NOTES_EXPORT_CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE)))
    chunk_overlap = int(os.getenv("NOTES_EXPORT_CHUNK_OVERLAP", str(DEFAULT_CHUNK_OVERLAP)))
    return chunk_size, chunk_overlap


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks for embedding.

    Short texts (under chunk_size) return a single chunk.
    Long texts are split with overlap so context at boundaries isn't lost.
    """
    text = text.strip()
    if not text:
        return ["(empty note)"]
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break in last 20% of chunk
            search_from = int(chunk_size * 0.8)
            para_break = chunk.rfind('\n\n', search_from)
            if para_break > 0:
                chunk = chunk[:para_break]
                end = start + para_break
            else:
                # Try sentence boundary
                for sep in ['. ', '.\n', '! ', '? ']:
                    sent_break = chunk.rfind(sep, search_from)
                    if sent_break > 0:
                        chunk = chunk[:sent_break + 1]
                        end = start + sent_break + 1
                        break

        chunks.append(chunk.strip())
        start = end - overlap
        if start <= (end - chunk_size):  # prevent infinite loop
            start = end

    return [c for c in chunks if c]


def _note_to_text(note_info: Dict, content: str) -> str:
    """Build searchable text from note metadata and content."""
    filename = note_info.get("filename", "")
    title = filename.replace("-", " ")
    return f"{title}\n\n{content}"


def _make_point_id(note_id: str, notebook: str, chunk_index: int = 0) -> str:
    """Create a deterministic string ID for a Qdrant point.

    Each chunk of a note gets a unique ID based on the note ID and chunk index.
    """
    raw = f"{notebook}:{note_id}:chunk{chunk_index}"
    return str(int(hashlib.sha256(raw.encode()).hexdigest()[:15], 16))


class QdrantNotesManager:
    """Manages Apple Notes vectors in Qdrant."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or _get_config()
        self.client = QdrantHTTP(self.config["qdrant_url"],
                                 api_key=self.config.get("qdrant_api_key", ""))
        self.collection = self.config["collection"]
        self.tracker = get_tracker()
        self._dim = None

    def _ensure_collection(self):
        if not self.client.collection_exists(self.collection):
            dim = self._get_dim()
            print(f"Creating Qdrant collection '{self.collection}' (dim={dim})")
            self.client.create_collection(self.collection, dim)

    def _get_dim(self) -> int:
        if self._dim is None:
            self._dim = get_embedding_dimension(self.config)
        return self._dim

    def _read_note_content(self, note_info: Dict, notebook: str) -> Optional[str]:
        """Read the best available content for a note (md > text > html)."""
        filename = note_info.get("filename", "")
        if not filename:
            return None
        root = Path(self.tracker.root_directory)
        uses_subdirs = self.tracker._uses_subdirs()

        for folder, ext in [("md", ".md"), ("text", ".txt"), ("html", ".html")]:
            if uses_subdirs:
                path = root / folder / notebook / f"{filename}{ext}"
            else:
                path = root / folder / f"{filename}{ext}"
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:
                    try:
                        return path.read_text(encoding="latin-1")
                    except Exception:
                        continue
        return None

    def _needs_indexing(self, note_info: Dict, force: bool = False) -> bool:
        """Check if a note needs re-indexing based on lastExported vs lastIndexedToQdrant."""
        if force:
            return True
        last_exported = note_info.get("lastExported", "")
        last_indexed = note_info.get("lastIndexedToQdrant", "")
        if not last_indexed:
            return True  # Never indexed
        return last_exported != last_indexed

    def _mark_indexed(self, json_file: Path, note_id: str, notebook_data: Dict):
        """Mark a note as indexed in the tracking JSON."""
        if note_id in notebook_data:
            notebook_data[note_id]["lastIndexedToQdrant"] = notebook_data[note_id].get("lastExported", "")

    def sync(self, dry_run: bool = False, force: bool = False) -> Dict[str, int]:
        """Incremental sync: only embed changed notes, delete removed ones.

        Args:
            dry_run: Preview what would happen without making changes.
            force: Re-embed all notes regardless of change status.
        """
        self._ensure_collection()
        stats = {"upserted": 0, "deleted": 0, "skipped": 0, "unchanged": 0, "errors": 0}

        # Collect all current note IDs and identify which need updating
        current_ids = set()       # All chunk IDs for current notes
        texts_to_embed = []
        point_metas = []
        notes_needing_update = []  # Track (json_file, note_id) for marking indexed

        for json_file in self.tracker.get_all_data_files():
            notebook_data = self.tracker.load_notebook_data(json_file)
            notebook = json_file.stem

            for note_id, note_info in notebook_data.items():
                if "deletedDate" in note_info:
                    continue

                # Register all possible chunk IDs for this note (for deletion tracking)
                # We use a generous upper bound; actual chunks may be fewer
                last_chunk_count = note_info.get("qdrantChunkCount", 1)
                for ci in range(max(last_chunk_count, 50)):
                    current_ids.add(_make_point_id(note_id, notebook, ci))

                # Check if this note needs re-indexing
                if not self._needs_indexing(note_info, force):
                    stats["unchanged"] += 1
                    continue

                content = self._read_note_content(note_info, notebook)
                if not content:
                    stats["skipped"] += 1
                    continue

                text = _note_to_text(note_info, content)
                c_size, c_overlap = _get_chunk_config()
                chunks = chunk_text(text, chunk_size=c_size, overlap=c_overlap)

                for ci, chunk in enumerate(chunks):
                    point_id = _make_point_id(note_id, notebook, ci)
                    texts_to_embed.append(chunk)
                    point_metas.append({
                        "point_id": point_id,
                        "note_id": note_id,
                        "notebook": notebook,
                        "filename": note_info.get("filename", ""),
                        "created": note_info.get("created", ""),
                        "modified": note_info.get("modified", ""),
                        "chunk_index": ci,
                        "total_chunks": len(chunks),
                        "json_file": json_file,
                    })

                notes_needing_update.append((json_file, note_id, len(chunks)))

        if dry_run:
            note_count = len(notes_needing_update)
            chunk_count = len(texts_to_embed)
            print(f"[DRY RUN] Would upsert {note_count} notes ({chunk_count} chunks) "
                  f"({stats['unchanged']} unchanged, {stats['skipped']} skipped)")
            stats["upserted"] = note_count
            return stats

        # Embed and upsert only changed notes
        points_to_upsert = []
        if texts_to_embed:
            print(f"Embedding {len(texts_to_embed)} changed notes "
                  f"({stats['unchanged']} unchanged, skipping those)...")
            batch_size = 32
            all_vectors = []
            for i in range(0, len(texts_to_embed), batch_size):
                batch = texts_to_embed[i:i + batch_size]
                try:
                    vectors = get_embeddings(batch, self.config)
                    all_vectors.extend(vectors)
                except Exception:
                    # Batch failed — fall back to one-at-a-time
                    for j, single_text in enumerate(batch):
                        try:
                            vec = get_embeddings([single_text], self.config)
                            all_vectors.append(vec[0])
                        except Exception as e2:
                            fn = point_metas[i + j].get("filename", "?")
                            print(f"  Skipping {fn}: {e2}")
                            stats["errors"] += 1
                            all_vectors.append(None)

            # Build points
            for meta, vector in zip(point_metas, all_vectors):
                if vector is None:
                    continue
                points_to_upsert.append({
                    "id": int(meta["point_id"]),
                    "vector": vector,
                    "payload": {
                        "note_id": meta["note_id"],
                        "notebook": meta["notebook"],
                        "filename": meta["filename"],
                        "created": meta["created"],
                        "modified": meta["modified"],
                        "chunk_index": meta["chunk_index"],
                        "total_chunks": meta["total_chunks"],
                    },
                })

            # Upsert
            print(f"Upserting {len(points_to_upsert)} points to Qdrant...")
            self.client.upsert_points(self.collection, points_to_upsert)
            stats["upserted"] = len(points_to_upsert)

            # Only mark as indexed AFTER successful upsert
            upserted_note_ids = {p["payload"]["note_id"] for p in points_to_upsert}
            json_updates = {}
            for json_file, note_id, chunk_count in notes_needing_update:
                if note_id in upserted_note_ids:
                    jf = str(json_file)
                    if jf not in json_updates:
                        json_updates[jf] = self.tracker.load_notebook_data(jf)
                    self._mark_indexed(json_file, note_id, json_updates[jf])
                    json_updates[jf][note_id]["qdrantChunkCount"] = chunk_count
            for json_path_str, notebook_data in json_updates.items():
                self.tracker.save_notebook_data(json_path_str, notebook_data)

        # Delete points that are no longer in the export
        existing_ids = set()
        offset = None
        while True:
            points, next_offset = self.client.scroll(self.collection, limit=100, offset=offset)
            for p in points:
                existing_ids.add(str(p["id"]))
            if next_offset is None:
                break
            offset = next_offset

        to_delete = existing_ids - {str(int(pid)) for pid in current_ids}
        if to_delete:
            print(f"Deleting {len(to_delete)} removed notes from Qdrant...")
            self.client.delete_points(self.collection, [int(pid) for pid in to_delete])
            stats["deleted"] = len(to_delete)

        fmt.emit("summary", command="sync", **stats)
        print(f"Qdrant sync: {stats['upserted']} upserted, {stats['unchanged']} unchanged, "
              f"{stats['deleted']} deleted, {stats['skipped']} skipped, "
              f"{stats['errors']} errors")
        return stats

    def search(self, query: str, limit: int = 10,
               score_threshold: float = 0.0) -> List[Dict]:
        """Semantic search for notes matching a query.

        Returns deduplicated results — if multiple chunks of the same note match,
        only the highest-scoring chunk is returned.
        """
        self._ensure_collection()
        vectors = get_embeddings([query], self.config)
        # Fetch more results than requested to account for deduplication
        raw_results = self.client.search(self.collection, vectors[0],
                                         limit=limit * 3, score_threshold=score_threshold)

        # Deduplicate by note_id, keeping the best score
        seen = {}
        for r in raw_results:
            payload = r.get("payload", {})
            key = (payload.get("note_id", ""), payload.get("notebook", ""))
            score = r.get("score", 0)
            if key not in seen or score > seen[key]["score"]:
                seen[key] = {
                    "score": score,
                    "note_id": payload.get("note_id", ""),
                    "notebook": payload.get("notebook", ""),
                    "filename": payload.get("filename", ""),
                    "created": payload.get("created", ""),
                    "modified": payload.get("modified", ""),
                    "chunk_index": payload.get("chunk_index", 0),
                    "total_chunks": payload.get("total_chunks", 1),
                }

        formatted = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
        results = formatted[:limit]
        for r in results:
            fmt.emit("result", **r)
        fmt.emit("summary", command="search", total_results=len(results))
        return results

    def status(self) -> Dict:
        """Get collection status."""
        try:
            count = self.client.count(self.collection)
            return {"exists": True, "count": count, "collection": self.collection}
        except RuntimeError:
            return {"exists": False, "count": 0, "collection": self.collection}


# ── CLI ───────────────────────────────────────────────────────────────────

def check_prerequisites(config: Optional[Dict] = None) -> Dict[str, Any]:
    """Check if Docker, Qdrant, and embedding provider are available."""
    import subprocess
    if config is None:
        config = _get_config()

    status = {"docker": False, "qdrant": False, "embeddings": False, "details": []}

    # Check Docker
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        status["docker"] = result.returncode == 0
        if status["docker"]:
            status["details"].append("Docker: running")
        else:
            status["details"].append("Docker: not running (start Docker Desktop)")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        status["details"].append("Docker: not installed")

    # Check Qdrant
    try:
        req = urllib.request.Request(f"{config['qdrant_url']}/collections")
        if config.get("qdrant_api_key"):
            req.add_header("api-key", config["qdrant_api_key"])
        with urllib.request.urlopen(req, timeout=5) as resp:
            status["qdrant"] = True
            status["details"].append(f"Qdrant: responding at {config['qdrant_url']}")
    except Exception:
        status["details"].append(f"Qdrant: not responding at {config['qdrant_url']}")
        if "cloud.qdrant.io" in config["qdrant_url"] or config.get("qdrant_api_key"):
            status["details"].append("  (check your Qdrant Cloud URL and API key)")
        else:
            status["details"].append("  Start with: docker-compose up -d (in your qdrant directory)")

    # Check embedding provider
    provider = config["embedding_provider"]
    if provider == "ollama":
        try:
            req = urllib.request.Request(f"{config['ollama_url']}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                target = config["ollama_model"]
                if any(target in m for m in models):
                    status["embeddings"] = True
                    status["details"].append(f"Ollama: running, model '{target}' available")
                else:
                    status["details"].append(f"Ollama: running, but model '{target}' not found")
                    status["details"].append(f"  Pull with: ollama pull {target}")
                    status["details"].append(f"  Available: {', '.join(models[:5])}")
        except Exception:
            status["details"].append(f"Ollama: not responding at {config['ollama_url']}")
            status["details"].append("  Start with: ollama serve")
    elif provider in ("sentence-transformers", "st"):
        try:
            import sentence_transformers
            status["embeddings"] = True
            status["details"].append(f"sentence-transformers: installed (model: {config['st_model']})")
        except ImportError:
            status["details"].append("sentence-transformers: not installed")
            status["details"].append("  Install with: pip install sentence-transformers")

    return status


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Manage Apple Notes vectors in Qdrant")
    fmt.add_json_arg(parser)
    sub = parser.add_subparsers(dest="command")

    sync_p = sub.add_parser("sync", help="Sync changed notes to Qdrant")
    sync_p.add_argument("--force", action="store_true",
                        help="Re-embed all notes, not just changed ones")
    sync_p.add_argument("--chunk-size", type=int, default=None,
                        help=f"Characters per chunk (default: {DEFAULT_CHUNK_SIZE})")
    sync_p.add_argument("--chunk-overlap", type=int, default=None,
                        help=f"Overlap between chunks (default: {DEFAULT_CHUNK_OVERLAP})")
    sub.add_parser("status", help="Show Qdrant collection status")
    sub.add_parser("check", help="Check prerequisites (Docker, Qdrant, embeddings)")

    search_p = sub.add_parser("search", help="Semantic search")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("-n", "--limit", type=int, default=10)
    search_p.add_argument("--threshold", type=float, default=0.0)

    sub.add_parser("reset", help="Delete and recreate the collection")
    sub.add_parser("dry-run", help="Show what sync would do")

    args = parser.parse_args()
    fmt.setup_from_args(args)

    if not args.command:
        parser.print_help()
        return

    if args.command == "check":
        config = _get_config()
        print("=== Qdrant Integration Prerequisites ===\n")
        result = check_prerequisites(config)
        for detail in result["details"]:
            print(f"  {detail}")
        print()
        all_ok = result["docker"] and result["qdrant"] and result["embeddings"]
        fmt.emit("status", command="check", docker=result["docker"],
                 qdrant=result["qdrant"], embeddings=result["embeddings"],
                 all_ok=all_ok)
        if all_ok:
            print("All prerequisites met. Ready to sync.")
        else:
            print("Some prerequisites missing. See above for details.")
            if not result["qdrant"] and result["docker"]:
                print("\nQuick start Qdrant with Docker:")
                print("  docker run -d -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant")
        fmt.close()
        return

    mgr = QdrantNotesManager()

    if args.command == "sync":
        if args.chunk_size is not None:
            os.environ["NOTES_EXPORT_CHUNK_SIZE"] = str(args.chunk_size)
        if args.chunk_overlap is not None:
            os.environ["NOTES_EXPORT_CHUNK_OVERLAP"] = str(args.chunk_overlap)
        mgr.sync(force=args.force)
    elif args.command == "dry-run":
        mgr.sync(dry_run=True)
    elif args.command == "status":
        s = mgr.status()
        fmt.emit("status", command="status", **s)
        print(f"Collection: {s['collection']}")
        print(f"Exists: {s['exists']}")
        print(f"Points: {s['count']}")
    elif args.command == "search":
        results = mgr.search(args.query, limit=args.limit,
                             score_threshold=args.threshold)
        if not results:
            print("No results found.")
            fmt.close()
            return
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r['score']:.3f}] {r['filename']} ({r['notebook']})")
            if r['modified']:
                print(f"   Modified: {r['modified']}")
    elif args.command == "reset":
        print(f"Deleting collection '{mgr.collection}'...")
        try:
            mgr.client.delete_collection(mgr.collection)
            fmt.emit("status", command="reset", collection=mgr.collection, deleted=True)
            print("Deleted. Run 'sync' to rebuild.")
        except RuntimeError as e:
            fmt.emit("error", command="reset", message=str(e))
            print(f"Error: {e}")

    fmt.close()


if __name__ == "__main__":
    main()
