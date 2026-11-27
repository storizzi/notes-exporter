"""The documentation: every relative link in a Markdown file reaches a file the repository
tracks (what GitHub shows), every #anchor a heading, and the README names the current version."""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    files = {f for f in out.splitlines() if f}
    return files, {str(Path(f).parent) for f in files} | {"."}


def _slug(heading, seen):
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens, -1, -2 for repeats."""
    h = re.sub(r"<!--.*?-->", "", heading).strip()
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    s = "".join(c for c in h.lower() if c.isalnum() or c in " -_").replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def _without_code(text):
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


def _anchors(path):
    seen, out = {}, set()
    text = path.read_text()
    for line in _without_code(text).splitlines():
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            out.add(_slug(m.group(1), seen))
    out.update(re.findall(r'(?:id|name)="([^"]+)"', text))
    return out


def test_relative_links_and_anchors_resolve():
    files, dirs = _tracked()
    broken = []
    for doc in sorted(f for f in files if f.endswith(".md")):
        text = _without_code((REPO / doc).read_text())
        for m in re.finditer(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|(?:href|src)=\"([^\"]+)\"", text):
            target = m.group(1) or m.group(2)
            if re.match(r"[a-z]+:", target):
                continue  # https:, mailto:
            path, _, anchor = target.partition("#")
            rel = doc if not path else \
                str((REPO / doc).parent.joinpath(path).resolve().relative_to(REPO))
            if path and rel not in files and rel not in dirs:
                broken.append(f"{doc}: {target} (no such file in git)")
            elif anchor and rel.endswith(".md") and anchor not in _anchors(REPO / rel):
                broken.append(f"{doc}: {target} (no such heading)")
    assert not broken, "\n".join(broken)


def test_readme_names_the_current_version():
    version = (REPO / "VERSION").read_text().strip()
    readme = (REPO / "README.md").read_text()
    assert f"**Version {version}**" in readme
    assert f"[{version}](./RELEASES.md#" in readme
