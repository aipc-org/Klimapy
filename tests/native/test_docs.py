"""Validate the local documentation tree and local Markdown file links."""

from pathlib import Path
import re
import unittest
from urllib.parse import unquote


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "docs").is_dir():
            self.skipTest("Documentation is not included in installed wheel")
        files = [
            root / name
            for name in (
                "README.md",
                "CONTRIBUTING.md",
                "CHANGELOG.md",
            )
        ] + list((root / "docs").rglob("*.md"))
        files += list((root / "benchmarks").rglob("*.md"))
        files += list((root / "experiments").rglob("*.md"))
        broken = []
        for path in files:
            for target in re.findall(
                r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")
            ):
                target = target.strip("<>").split("#", 1)[0]
                if (
                    not target
                    or "://" in target
                    or target.startswith(("mailto:", "data:"))
                ):
                    continue
                if not (path.parent / unquote(target)).exists():
                    broken.append(str(path.relative_to(root)) + ": " + target)
        self.assertEqual(broken, [])

    def test_feature_subdirectories(self):
        root = Path(__file__).resolve().parents[2] / "docs"
        if not root.exists():
            self.skipTest("Documentation not present")
        expected = [
            "getting-started",
            "etccdi",
            "downscaling",
            "precipitation",
            "statistics",
            "tools",
            "development",
        ]
        for folder in expected:
            self.assertTrue((root / folder).is_dir(), folder)
        self.assertEqual({p.name for p in root.glob("*.md")}, {"index.md"})
