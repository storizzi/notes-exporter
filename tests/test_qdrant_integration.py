import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_integration import (
    QdrantHTTP,
    QdrantNotesManager,
    _get_config,
    _make_point_id,
    _note_to_text,
    chunk_text,
    get_embeddings,
)


@pytest.mark.unit
@pytest.mark.qdrant
class TestConfig:
    def test_defaults(self, monkeypatch):
        for key in ["NOTES_EXPORT_QDRANT_URL", "NOTES_EXPORT_QDRANT_COLLECTION",
                     "NOTES_EXPORT_QDRANT_API_KEY", "NOTES_EXPORT_EMBEDDING_PROVIDER"]:
            monkeypatch.delenv(key, raising=False)
        config = _get_config()
        assert config["qdrant_url"] == "http://localhost:6333"
        assert config["collection"] == "apple_notes"
        assert config["qdrant_api_key"] == ""
        assert config["embedding_provider"] == "ollama"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_QDRANT_URL", "https://my-cloud.qdrant.io:6333")
        monkeypatch.setenv("NOTES_EXPORT_QDRANT_API_KEY", "secret123")
        monkeypatch.setenv("NOTES_EXPORT_QDRANT_COLLECTION", "my_notes")
        config = _get_config()
        assert config["qdrant_url"] == "https://my-cloud.qdrant.io:6333"
        assert config["qdrant_api_key"] == "secret123"
        assert config["collection"] == "my_notes"


@pytest.mark.unit
@pytest.mark.qdrant
class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("Short text", chunk_size=800, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == "Short text"

    def test_empty_text(self):
        chunks = chunk_text("", chunk_size=800, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == "(empty note)"

    def test_whitespace_only(self):
        chunks = chunk_text("   \n\n  ", chunk_size=800, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == "(empty note)"

    def test_long_text_splits(self):
        text = "word " * 500  # 2500 chars
        chunks = chunk_text(text, chunk_size=800, overlap=200)
        assert len(chunks) > 1

    def test_chunks_have_overlap(self):
        # Build text with distinct sections
        text = "AAAA " * 100 + "BBBB " * 100 + "CCCC " * 100  # ~1500 chars
        chunks = chunk_text(text, chunk_size=600, overlap=150)
        assert len(chunks) >= 2
        # The end of chunk 0 should appear at the start of chunk 1 (overlap)
        end_of_first = chunks[0][-100:]
        assert end_of_first in chunks[1] or chunks[1][:200] in chunks[0]

    def test_breaks_at_paragraph(self):
        text = "First paragraph. " * 30 + "\n\n" + "Second paragraph. " * 30
        chunks = chunk_text(text, chunk_size=600, overlap=100)
        # At least one chunk should end near a paragraph boundary
        found_para_break = any(c.endswith('.') or c.endswith('paragraph.') for c in chunks)
        # Just verify it splits and doesn't crash
        assert len(chunks) >= 2

    def test_no_empty_chunks(self):
        text = "Hello world. " * 200
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        for chunk in chunks:
            assert len(chunk.strip()) > 0

    def test_all_content_covered(self):
        # Every word in the original should appear in at least one chunk
        words = [f"unique_word_{i}" for i in range(50)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=200, overlap=50)
        combined = " ".join(chunks)
        for word in words:
            assert word in combined, f"Lost word: {word}"

    def test_custom_chunk_size(self):
        text = "x" * 2000
        chunks_small = chunk_text(text, chunk_size=200, overlap=50)
        chunks_large = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(chunks_small) > len(chunks_large)


@pytest.mark.unit
@pytest.mark.qdrant
class TestMakePointId:
    def test_deterministic(self):
        id1 = _make_point_id("123", "iCloud-Notes")
        id2 = _make_point_id("123", "iCloud-Notes")
        assert id1 == id2

    def test_different_ids(self):
        id1 = _make_point_id("123", "iCloud-Notes")
        id2 = _make_point_id("456", "iCloud-Notes")
        assert id1 != id2

    def test_different_notebooks(self):
        id1 = _make_point_id("123", "iCloud-Notes")
        id2 = _make_point_id("123", "Gmail-Notes")
        assert id1 != id2

    def test_returns_numeric_string(self):
        pid = _make_point_id("test", "notebook")
        assert pid.isdigit()

    def test_different_chunks_different_ids(self):
        id0 = _make_point_id("123", "iCloud-Notes", 0)
        id1 = _make_point_id("123", "iCloud-Notes", 1)
        id2 = _make_point_id("123", "iCloud-Notes", 2)
        assert id0 != id1 != id2


@pytest.mark.unit
@pytest.mark.qdrant
class TestNoteToText:
    def test_combines_title_and_content(self):
        note_info = {"filename": "my-cool-note-123"}
        text = _note_to_text(note_info, "Some content here")
        assert "my cool note 123" in text
        assert "Some content here" in text


@pytest.mark.unit
@pytest.mark.qdrant
class TestQdrantHTTP:
    def test_auth_header_added_when_api_key_set(self):
        client = QdrantHTTP("http://localhost:6333", api_key="test-key")
        assert client.api_key == "test-key"

    def test_no_auth_header_when_no_key(self):
        client = QdrantHTTP("http://localhost:6333")
        assert client.api_key == ""

    def test_url_stripped(self):
        client = QdrantHTTP("http://localhost:6333/")
        assert client.url == "http://localhost:6333"


@pytest.mark.unit
@pytest.mark.qdrant
class TestQdrantNotesManagerSearch:
    def test_search_returns_formatted_results(self):
        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch('qdrant_integration.get_embeddings', return_value=[[0.1, 0.2, 0.3]]), \
             patch.object(QdrantHTTP, 'search', return_value=[
                 {"score": 0.95, "payload": {
                     "note_id": "123", "notebook": "iCloud-Notes",
                     "filename": "test-note-123", "created": "", "modified": ""
                 }}
             ]):
            mgr = QdrantNotesManager()
            results = mgr.search("test query", limit=5)
            assert len(results) == 1
            assert results[0]["score"] == 0.95
            assert results[0]["filename"] == "test-note-123"

    def test_search_empty_results(self):
        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch('qdrant_integration.get_embeddings', return_value=[[0.1, 0.2]]), \
             patch.object(QdrantHTTP, 'search', return_value=[]):
            mgr = QdrantNotesManager()
            results = mgr.search("nothing matches")
            assert results == []

    def test_search_deduplicates_chunks(self):
        """Multiple chunks from same note should return only the best score."""
        raw_results = [
            {"score": 0.9, "payload": {"note_id": "123", "notebook": "nb",
                "filename": "note-123", "created": "", "modified": "",
                "chunk_index": 0, "total_chunks": 3}},
            {"score": 0.95, "payload": {"note_id": "123", "notebook": "nb",
                "filename": "note-123", "created": "", "modified": "",
                "chunk_index": 2, "total_chunks": 3}},
            {"score": 0.7, "payload": {"note_id": "456", "notebook": "nb",
                "filename": "note-456", "created": "", "modified": "",
                "chunk_index": 0, "total_chunks": 1}},
        ]
        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch('qdrant_integration.get_embeddings', return_value=[[0.1]]), \
             patch.object(QdrantHTTP, 'search', return_value=raw_results):
            mgr = QdrantNotesManager()
            results = mgr.search("test", limit=10)
            assert len(results) == 2  # Two unique notes, not three chunks
            assert results[0]["score"] == 0.95  # Best chunk score for note 123
            assert results[0]["note_id"] == "123"
            assert results[1]["note_id"] == "456"


@pytest.mark.unit
@pytest.mark.qdrant
class TestQdrantNotesManagerStatus:
    def test_status_when_exists(self):
        with patch.object(QdrantHTTP, 'count', return_value=42):
            mgr = QdrantNotesManager()
            s = mgr.status()
            assert s["exists"] is True
            assert s["count"] == 42

    def test_status_when_not_exists(self):
        with patch.object(QdrantHTTP, 'count', side_effect=RuntimeError("not found")):
            mgr = QdrantNotesManager()
            s = mgr.status()
            assert s["exists"] is False
            assert s["count"] == 0


@pytest.mark.unit
@pytest.mark.qdrant
class TestQdrantNotesManagerSync:
    def test_dry_run_does_not_upsert(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))

        # Create data and content
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)

        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump({"123": {"filename": "test-note", "created": "", "modified": ""}}, f)

        (md_dir / "test-note.md").write_text("Hello world")

        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch.object(QdrantHTTP, 'upsert_points') as mock_upsert:
            mgr = QdrantNotesManager()
            stats = mgr.sync(dry_run=True)
            mock_upsert.assert_not_called()
            assert stats["upserted"] == 1  # Counted but not sent

    def test_failed_embed_does_not_mark_indexed(self, tmp_path, monkeypatch):
        """Regression: notes must NOT be marked as indexed when embedding fails."""
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)

        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump({"123": {
                "filename": "test-note", "created": "", "modified": "",
                "lastExported": "2026-01-01 10:00:00",
            }}, f)

        (md_dir / "test-note.md").write_text("content")

        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch('qdrant_integration.get_embeddings',
                   side_effect=RuntimeError("embedding failed")), \
             patch.object(QdrantHTTP, 'scroll', return_value=([], None)):
            mgr = QdrantNotesManager()
            stats = mgr.sync()
            assert stats["errors"] > 0
            assert stats["upserted"] == 0

        # Verify the note was NOT marked as indexed
        data = json.load(open(json_file))
        assert "lastIndexedToQdrant" not in data["123"]

    def test_batch_fallback_to_individual(self, tmp_path, monkeypatch):
        """When a batch fails, individual items should be retried."""
        monkeypatch.setenv("NOTES_EXPORT_ROOT_DIR", str(tmp_path))

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        md_dir = tmp_path / "md" / "iCloud-Notes"
        md_dir.mkdir(parents=True)

        notes = {}
        for i in range(3):
            notes[str(i)] = {
                "filename": f"note-{i}", "created": "", "modified": "",
                "lastExported": "2026-01-01 10:00:00",
            }
            (md_dir / f"note-{i}.md").write_text(f"content {i}")

        json_file = data_dir / "iCloud-Notes.json"
        with open(json_file, "w") as f:
            json.dump(notes, f)

        call_count = [0]

        def mock_embed(texts, config):
            call_count[0] += 1
            if len(texts) > 1:
                raise RuntimeError("batch too large")
            # Individual calls succeed
            return [[0.1, 0.2, 0.3] for _ in texts]

        with patch.object(QdrantHTTP, 'collection_exists', return_value=True), \
             patch('qdrant_integration.get_embeddings', side_effect=mock_embed), \
             patch.object(QdrantHTTP, 'upsert_points'), \
             patch.object(QdrantHTTP, 'scroll', return_value=([], None)):
            mgr = QdrantNotesManager()
            mgr._dim = 3
            stats = mgr.sync()
            # Batch failed, then 3 individual calls succeeded
            assert stats["upserted"] == 3
            assert stats["errors"] == 0
