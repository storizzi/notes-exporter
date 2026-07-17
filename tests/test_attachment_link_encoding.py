import sys
from pathlib import Path

import pytest
from markdownify import markdownify as md

sys.path.insert(0, str(Path(__file__).parent.parent))

from extract_images import _encode_src


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
