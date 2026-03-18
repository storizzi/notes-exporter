import base64
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_to_notes import embed_images_as_base64
from extract_images import _should_skip_existing, _wrap_html


@pytest.mark.unit
@pytest.mark.export
class TestEmbedImagesAsBase64:
    def test_leaves_data_uris_unchanged(self):
        html = '<img src="data:image/png;base64,abc123"/>'
        result = embed_images_as_base64(html, Path("/tmp"))
        assert 'data:image/png;base64,abc123' in result

    def test_embeds_local_image(self, tmp_path):
        # Create a test image file
        img_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        img_path = tmp_path / "test.png"
        img_path.write_bytes(img_data)

        html = '<img src="test.png"/>'
        result = embed_images_as_base64(html, tmp_path)

        assert 'data:image/png;base64,' in result
        assert 'test.png' not in result.split('base64,')[0]  # src no longer points to file

    def test_handles_relative_path_with_dot_slash(self, tmp_path):
        attachments = tmp_path / "attachments"
        attachments.mkdir()
        img_path = attachments / "note-001.png"
        img_path.write_bytes(b'\x89PNG' + b'\x00' * 50)

        html = '<img src="./attachments/note-001.png"/>'
        result = embed_images_as_base64(html, tmp_path)
        assert 'data:image/png;base64,' in result

    def test_handles_missing_image_gracefully(self, tmp_path):
        html = '<img src="nonexistent.png"/>'
        result = embed_images_as_base64(html, tmp_path)
        # Should keep original src since file not found
        assert 'nonexistent.png' in result

    def test_handles_attachments_subdirectory(self, tmp_path):
        attachments = tmp_path / "attachments"
        attachments.mkdir()
        img_path = attachments / "photo.jpg"
        img_path.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 50)

        html = '<img src="photo.jpg"/>'
        result = embed_images_as_base64(html, tmp_path)
        assert 'data:image/jpeg;base64,' in result

    def test_preserves_non_img_html(self, tmp_path):
        html = '<p>Hello <strong>world</strong></p>'
        result = embed_images_as_base64(html, tmp_path)
        assert 'Hello' in result
        assert 'world' in result

    def test_multiple_images(self, tmp_path):
        for name in ["a.png", "b.png"]:
            (tmp_path / name).write_bytes(b'\x89PNG' + b'\x00' * 50)

        html = '<img src="a.png"/><img src="b.png"/>'
        result = embed_images_as_base64(html, tmp_path)
        assert result.count('data:image/png;base64,') == 2


@pytest.mark.unit
@pytest.mark.export
class TestShouldSkipExisting:
    def test_skips_when_enabled_and_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_NO_OVERWRITE", "true")
        f = tmp_path / "test.html"
        f.write_text("existing")
        assert _should_skip_existing(f) is True

    def test_does_not_skip_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_NO_OVERWRITE", "false")
        f = tmp_path / "test.html"
        f.write_text("existing")
        assert _should_skip_existing(f) is False

    def test_does_not_skip_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_EXPORT_NO_OVERWRITE", "true")
        f = tmp_path / "nonexistent.html"
        assert _should_skip_existing(f) is False


@pytest.mark.unit
@pytest.mark.export
class TestWrapHtml:
    def test_wraps_with_doctype_and_title(self):
        result = _wrap_html("<p>Hello</p>", "My Note")
        assert "<!DOCTYPE html>" in result
        assert "<title>My Note</title>" in result
        assert "<body>" in result
        assert "<p>Hello</p>" in result
        assert "</html>" in result

    def test_title_escaping(self):
        result = _wrap_html("<p>Hi</p>", "Note & Title")
        assert "Note & Title" in result
