"""Regression checks for the boundary between local repository and remote links."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from validate_repository_links import check_fragments, local_target

REPOSITORY = "Yoruxyv/semantix"
PREFIX = f"https://github.com/{REPOSITORY}/"


class RepositoryLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs/Guide.md").write_text(
            '# Repeated heading\n\n# Repeated heading\n\n<a id="explicit-id"></a>\n'
            "\n# Résumé `code` & punctuation!\n",
            encoding="utf-8",
        )
        (self.root / "docs/space name.md").write_text("# Heading\n", encoding="utf-8")
        (self.root / "docs/page.html").write_text(
            '<h1 id="custom">Page</h1>', encoding="utf-8"
        )
        (self.root / "config.json").write_text("{}", encoding="utf-8")
        self.files = {
            "docs/Guide.md",
            "docs/space name.md",
            "docs/page.html",
            "config.json",
        }

    def target(self, suffix: str) -> str | None:
        return local_target(PREFIX + suffix, REPOSITORY, self.root, self.files)

    def test_real_paths_and_parser_anchors(self) -> None:
        targets = [
            self.target(suffix)
            for suffix in (
                "blob/main/docs/Guide.md#repeated-heading",
                "blob/main/docs/Guide.md#repeated-heading-1",
                "blob/main/docs/Guide.md#explicit-id",
                "blob/main/docs/Guide.md#r%C3%A9sum%C3%A9-code--punctuation",
                "blob/main/docs/space%20name.md#heading",
                "blob/main/docs/%47uide.md#repeated-heading",
                "blob/main/docs/page.html#custom",
                "blob/main/config.json?plain=1",
                "tree/main/docs/",
            )
        ]
        self.assertNotIn(None, targets)  # noqa: PT009 -- stdlib runner needs no pytest installation
        check_fragments(targets, self.root)

    def test_missing_anchor_fails(self) -> None:
        for fragment in ("absent", "repeated-heading-2", "wrong-id"):
            with (
                self.subTest(fragment=fragment),
                self.assertRaises(subprocess.CalledProcessError),  # noqa: PT027 -- stdlib unittest runner
            ):
                check_fragments(
                    [self.target("blob/main/docs/Guide.md#" + fragment)], self.root
                )

    def test_paths_fail_closed(self) -> None:
        for suffix in (
            "blob/main/missing.md",
            "blob/main/docs/guide.md",
            "blob/main/Docs/Guide.md",
            "blob/main/docs",
            "tree/main/docs/Guide.md",
            "tree/main/missing",
            "blob/main/docs/Guide.md/",
            "blob/main/docs/../config.json",
            "blob/main/docs/%2e%2e/config.json",
            "blob/main/docs%2fGuide.md",
            "blob/main/docs%5cGuide.md",
            "blob/main/docs/%ZZ.md",
            "blob/main/docs/%FF.md",
            "blob/main/docs//Guide.md",
            "blob/main/config.json#L1",
            "tree/main/docs#absent",
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):  # noqa: PT027 -- stdlib unittest runner
                self.target(suffix)

    def test_other_refs_and_repositories_stay_remote(self) -> None:
        for url in (
            PREFIX + "blob/develop/docs/Guide.md",
            PREFIX + "blob/123abc/docs/Guide.md",
            PREFIX + "blob/main-extra/docs/Guide.md",
            PREFIX + "issues",
            "https://github.com/Yoruxyv/semantix-other/blob/main/docs/Guide.md",
            "https://github.com/other/semantix/blob/main/docs/Guide.md",
            "https://github.com.evil.test/Yoruxyv/semantix/blob/main/docs/Guide.md",
            "https://user@github.com/Yoruxyv/semantix/blob/main/docs/Guide.md",
        ):
            with self.subTest(url=url):
                self.assertIsNone(local_target(url, REPOSITORY, self.root, self.files))  # noqa: PT009 -- stdlib unittest runner


if __name__ == "__main__":
    unittest.main()
