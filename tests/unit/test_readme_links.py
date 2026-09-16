"""
Guard ``README.md`` against links that only work on GitHub.

The README is the wheel's ``long_description``, so PyPI renders it verbatim and resolves
relative URLs against ``pypi.org`` — where they 404, and images simply do not appear. For a
``pip install`` that page is the only entry point to the documentation, so a relative link
added here is a dead end for exactly the users who have no local copy of the repo.
"""

import re

# ``](target)`` — every inline markdown link and image.
MARKDOWN_TARGET = re.compile(r"\]\(([^)]+)\)")
# ``href="target"`` / ``src="target"`` — the README's centred badge block is raw HTML.
HTML_TARGET = re.compile(r'(?:href|src)="([^"]+)"')

# Anchors stay relative: they resolve within the rendered page itself, on either site.
ALLOWED_PREFIXES = ("http://", "https://", "#", "mailto:")


def _targets(text: str) -> list[str]:
    return MARKDOWN_TARGET.findall(text) + HTML_TARGET.findall(text)


class TestReadmeIsSelfContained:
    """Nothing in the README may assume the reader has the repository on disk."""

    def test_no_relative_links(self, project_root):
        readme = (project_root / "README.md").read_text(encoding="utf-8")

        relative = [t for t in _targets(readme) if not t.startswith(ALLOWED_PREFIXES)]

        assert not relative, (
            f"README.md has repo-relative link(s): {sorted(set(relative))}. "
            "PyPI resolves these against pypi.org and they 404. Use the absolute "
            "https://github.com/larib-data/clinical-scope/blob/main/<path> form instead "
            "(raw.githubusercontent.com for images)."
        )
