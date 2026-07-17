import sys
from pathlib import Path

import pytest
from markdownify import markdownify as md

sys.path.insert(0, str(Path(__file__).parent.parent))

from extract_images import _encode_src
from sync_to_notes import embed_images_as_base64


@pytest.mark.unit
@pytest.mark.export
class TestEncodeSrc:
    def test_plain_name_unchanged(self):
        assert _encode_src("./attachments/note-001.png") == "./attachments/note-001.png"

    def test_preserves_path_separators(self):
        assert _encode_src("./attachments/a.png").startswith("./attachments/")

    def test_encodes_spaces(self):
        assert _encode_src("./attachments/my note.png") == "./attachments/my%20note.png"

    def test_encodes_parentheses(self):
        # Parentheses break Markdown link destinations if left bare.
        out = _encode_src("./attachments/Lagarde-(IMF)-001.png")
        assert "(" not in out and ")" not in out
        assert out == "./attachments/Lagarde-%28IMF%29-001.png"

    def test_encodes_unbalanced_paren(self):
        out = _encode_src("./attachments/STUDIEMATERIAAL-)-004.png")
        assert ")" not in out


@pytest.mark.unit
@pytest.mark.export
class TestEncodedSrcSurvivesMarkdown:
    """The whole point: once converted to Markdown, the image link must be
    intact (no stray character terminating the destination early)."""

    def test_paren_image_renders_as_valid_markdown_link(self):
        src = _encode_src("./attachments/note-(x)-attachment-001.png")
        html = f'<img src="{src}"/>'
        markdown = md(html).strip()
        # A valid, single, self-contained image link.
        assert markdown.startswith("![](")
        assert markdown.endswith(")")
        # No bare paren/space inside the destination.
        dest = markdown[markdown.index("(") + 1: markdown.rindex(")")]
        assert " " not in dest
        assert "(" not in dest and ")" not in dest

    def test_space_image_renders_as_valid_markdown_link(self):
        src = _encode_src("./attachments/my photo.png")
        markdown = md(f'<img src="{src}"/>').strip()
        dest = markdown[markdown.index("(") + 1: markdown.rindex(")")]
        assert " " not in dest


@pytest.mark.unit
@pytest.mark.export
class TestEncodedSrcRoundTripsThroughSync:
    """Encoding on export must not break the sync path back into Notes:
    embed_images_as_base64 (the inverse of extract_images) has to resolve
    the percent-encoded src back to the file on disk."""

    PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50

    def test_encoded_src_resolves_to_file(self, tmp_path):
        attachments = tmp_path / "attachments"
        attachments.mkdir()
        (attachments / "my note (2)-001.png").write_bytes(self.PNG)

        src = _encode_src("./attachments/my note (2)-001.png")
        assert "%20" in src  # sanity: it really is encoded
        result = embed_images_as_base64(f'<img src="{src}"/>', tmp_path)
        assert "data:image/png;base64," in result

    def test_verbatim_src_still_resolves(self, tmp_path):
        # Exports produced before encoding was introduced have verbatim
        # src values; those must keep working.
        attachments = tmp_path / "attachments"
        attachments.mkdir()
        (attachments / "my note (2)-001.png").write_bytes(self.PNG)

        result = embed_images_as_base64(
            '<img src="./attachments/my note (2)-001.png"/>', tmp_path)
        assert "data:image/png;base64," in result

    def test_literal_percent_filename_not_mangled(self, tmp_path):
        # A filename can legitimately contain % (e.g. a note titled with a
        # URL-encoded link). Verbatim resolution must win over decoding,
        # otherwise unquote() would rewrite %2F and miss the file.
        attachments = tmp_path / "attachments"
        attachments.mkdir()
        (attachments / "https%3A%2F%2Fexample-001.png").write_bytes(self.PNG)

        result = embed_images_as_base64(
            '<img src="./attachments/https%3A%2F%2Fexample-001.png"/>', tmp_path)
        assert "data:image/png;base64," in result
