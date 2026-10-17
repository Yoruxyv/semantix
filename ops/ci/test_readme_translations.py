"""Generic freshness and real Git-diff controls; no README content inventories."""

# ruff: noqa: PT009 -- stdlib unittest runner needs no third-party installation

import contextlib
import hashlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import validate_readme_translations as checker

SOURCE = "# Example\n\nRead the [guide](docs/guide.md#usage).\n"
TRANSLATED = "# Contoh\n\nBaca [panduan](../../guide.md#penggunaan).\n"
TRANSLATION = "docs/translation/id/README.ID.md"


def acknowledged(source: str, body: str = TRANSLATED) -> str:
    return (
        "<!-- readme-source-sha256: "
        + hashlib.sha256(source.encode()).hexdigest()
        + " -->\n\n"
        + body
    )


class ReadmeTranslationsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "README.md"
        self.translation = self.root / TRANSLATION
        self.translation.parent.mkdir(parents=True)
        self.source.write_text(SOURCE, encoding="utf-8")
        self.translation.write_text(acknowledged(SOURCE), encoding="utf-8")

    def snapshot(self) -> str:
        executable = shutil.which("git")
        if executable is None:
            self.fail("Git is required for real base-comparison regression tests")
        commands = (
            ("init", "--quiet"),
            ("add", "."),
            (
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            ),
            ("rev-parse", "HEAD"),
        )
        for arguments in commands:
            output = subprocess.check_output(  # noqa: S603 -- fixed test-owned Git commands; no shell
                [executable, "-c", "core.hooksPath=", *arguments],
                cwd=self.root,
                timeout=30,
                stderr=subprocess.PIPE,
            )
        return output.decode().strip()

    def test_valid_translation_and_independent_prose_and_anchors(self) -> None:
        self.assertEqual(checker.validate(self.root), [])
        self.translation.write_text(
            acknowledged(
                SOURCE,
                "# Panduan lokal baru\n\nBahasa Indonesia yang wajar: café. [Tautan](#panduan-lokal-baru).\n",
            ),
            encoding="utf-8",
        )
        self.assertEqual(checker.validate(self.root), [])

    def test_canonical_change_invalidates_stale_metadata(self) -> None:
        self.source.write_text(SOURCE + "\nAdditional explanation.\n", encoding="utf-8")
        errors = "\n".join(checker.validate(self.root))
        self.assertIn(TRANSLATION + ": stale source hash", errors)
        self.assertIn("--update", errors)

    def test_updated_translation_and_fingerprint_pass_with_real_base(self) -> None:
        base = self.snapshot()
        changed = (
            SOURCE + "\n## A new responsibility\n\n[Another link](docs/another.md).\n"
        )
        self.source.write_text(changed, encoding="utf-8")
        self.translation.write_text(
            acknowledged(
                changed,
                TRANSLATED
                + "\n## Tanggung jawab baru\n\n[Tautan lain](../../another.md).\n",
            ),
            encoding="utf-8",
        )
        self.assertEqual(checker.validate(self.root, base), [])

    def test_hash_only_and_whitespace_only_changes_fail_with_real_base(self) -> None:
        base = self.snapshot()
        changed = SOURCE + "\nNew content.\n"
        self.source.write_text(changed, encoding="utf-8")
        for body in (TRANSLATED, "\n\n" + TRANSLATED.replace("Baca ", "Baca    ")):
            with self.subTest(body=body):
                self.translation.write_text(
                    acknowledged(changed, body), encoding="utf-8"
                )
                errors = "\n".join(checker.validate(self.root, base))
                self.assertIn("only hash/whitespace changed", errors)
                self.assertNotIn("stale source hash", errors)

    def test_english_only_correction_can_record_review_explanation(self) -> None:
        base = self.snapshot()
        changed = SOURCE.replace("Read", "Consult")
        self.source.write_text(changed, encoding="utf-8")
        self.translation.write_text(
            acknowledged(
                changed,
                TRANSLATED
                + "\n<!-- Reviewed: the Indonesian wording already conveys this English correction. -->\n",
            ),
            encoding="utf-8",
        )
        self.assertEqual(checker.validate(self.root, base), [])

    def test_translation_only_improvement_passes_with_real_base(self) -> None:
        base = self.snapshot()
        self.translation.write_text(
            acknowledged(SOURCE, TRANSLATED.replace("Baca", "Silakan baca")),
            encoding="utf-8",
        )
        self.assertEqual(checker.validate(self.root, base), [])

    def test_source_rewrapping_can_acknowledge_without_forced_prose_edit(self) -> None:
        base = self.snapshot()
        changed = SOURCE.replace("Read the", "Read\nthe")
        self.source.write_text(changed, encoding="utf-8")
        self.translation.write_text(acknowledged(changed), encoding="utf-8")
        self.assertEqual(checker.validate(self.root, base), [])

    def test_missing_all_translations_fails(self) -> None:
        self.translation.unlink()
        self.assertIn(
            "No root README translations found", "\n".join(checker.validate(self.root))
        )

    def test_missing_previously_present_translation_fails_even_with_new_language(
        self,
    ) -> None:
        base = self.snapshot()
        self.translation.unlink()
        other = self.root / "docs/translation/fr/README.FR.md"
        other.parent.mkdir()
        other.write_text(acknowledged(SOURCE, "# Exemple\n"), encoding="utf-8")
        self.assertIn(
            TRANSLATION + ": missing/unreadable translation",
            "\n".join(checker.validate(self.root, base)),
        )

    def test_new_translation_is_discovered_without_registration(self) -> None:
        other = self.root / "docs/translation/fr/README.FR.md"
        other.parent.mkdir()
        other.write_text(acknowledged(SOURCE, "# Exemple\n"), encoding="utf-8")
        self.assertEqual(len(checker.discover(self.root)), 2)
        self.assertEqual(checker.validate(self.root), [])
        other.write_text("# Sans métadonnées\n", encoding="utf-8")
        self.assertIn(
            "docs/translation/fr/README.FR.md: malformed metadata",
            "\n".join(checker.validate(self.root)),
        )

    def test_documentation_index_and_component_readmes_are_not_root_translations(
        self,
    ) -> None:
        (self.translation.parent / "README.md").write_text(
            "# Indeks\n", encoding="utf-8"
        )
        component = self.root / "packages/example/README.md"
        component.parent.mkdir(parents=True)
        component.write_text("# Component\n", encoding="utf-8")
        self.assertEqual(checker.discover(self.root), {TRANSLATION})
        self.assertEqual(checker.validate(self.root), [])

    def test_malformed_metadata_and_empty_translation_fail(self) -> None:
        valid = acknowledged(SOURCE)
        for text in (
            TRANSLATED,
            valid.replace("readme-source-sha256:", "source:"),
            valid.replace(hashlib.sha256(SOURCE.encode()).hexdigest(), "not-a-hash"),
            valid + valid.splitlines()[0],
            acknowledged(SOURCE, ""),
        ):
            with self.subTest(text=text):
                self.translation.write_text(text, encoding="utf-8")
                self.assertTrue(checker.validate(self.root))

    def test_missing_canonical_and_unavailable_or_invalid_base_fail_closed(
        self,
    ) -> None:
        self.assertTrue(checker.validate(self.root, "main"))
        base = self.snapshot()
        self.assertTrue(checker.validate(self.root, "0" * 40))
        self.source.unlink()
        self.assertTrue(checker.validate(self.root, base))

    def test_adopting_legacy_translation_without_metadata_uses_real_body_diff(
        self,
    ) -> None:
        self.translation.write_text(TRANSLATED, encoding="utf-8")
        base = self.snapshot()
        changed = SOURCE + "\nAn addition.\n"
        self.source.write_text(changed, encoding="utf-8")
        self.translation.write_text(acknowledged(changed), encoding="utf-8")
        self.assertIn(
            "only hash/whitespace changed", "\n".join(checker.validate(self.root, base))
        )
        self.translation.write_text(
            acknowledged(changed, TRANSLATED + "\nSebuah tambahan.\n"), encoding="utf-8"
        )
        self.assertEqual(checker.validate(self.root, base), [])

    def test_update_command_is_deterministic_and_preserves_translation_content(
        self,
    ) -> None:
        self.translation.write_text(TRANSLATED, encoding="utf-8")
        with (
            patch.object(checker, "__file__", str(self.root / "ops/ci/checker.py")),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(checker.main(["--update"]), 0)
        once = self.translation.read_bytes()
        self.assertIn(TRANSLATED, once.decode())
        self.assertIn("does not certify translation accuracy", stdout.getvalue())
        checker.update(self.root)
        self.assertEqual(self.translation.read_bytes(), once)
        self.assertEqual(checker.validate(self.root), [])

    def test_update_rejects_bad_metadata_before_writing_any_translation(self) -> None:
        before = self.translation.read_bytes()
        self.source.write_text(SOURCE + "\nNew content.\n", encoding="utf-8")
        other = self.root / "docs/translation/zz/README.ZZ.md"
        other.parent.mkdir()
        other.write_text("<!-- readme-source-sha256: broken -->\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "repair malformed"):  # noqa: PT027 -- stdlib runner
            checker.update(self.root)
        self.assertEqual(self.translation.read_bytes(), before)

    def test_empty_canonical_source_fails(self) -> None:
        self.source.write_text("", encoding="utf-8")
        self.translation.write_text(acknowledged(""), encoding="utf-8")
        self.assertIn("README.md is empty", "\n".join(checker.validate(self.root)))

    def test_lf_and_crlf_freshness_are_equivalent(self) -> None:
        base = self.snapshot()
        for path in (self.source, self.translation):
            path.write_bytes(
                path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            )
        self.assertEqual(checker.validate(self.root, base), [])

    def test_cli_fails_with_actionable_path_and_does_not_claim_semantic_accuracy(
        self,
    ) -> None:
        with patch.object(checker, "__file__", str(self.root / "ops/ci/checker.py")):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(checker.main([]), 0)
            self.assertIn("Human semantic review remains required", stdout.getvalue())
            self.translation.write_text(TRANSLATED, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(checker.main([]), 1)
            self.assertIn(TRANSLATION, stderr.getvalue())

    def parity(self, source: str, translated: str) -> tuple[str, str]:
        self.source.write_text(source, encoding="utf-8")
        self.translation.write_text(acknowledged(source, translated), encoding="utf-8")
        warnings: list[str] = []
        return "\n".join(checker.validate(self.root, warnings=warnings)), "\n".join(
            warnings
        )

    def test_new_heading_missing_counterpart_and_changed_hierarchy_fail(self) -> None:
        for source, translated in (
            ("# First\n\n## New\n", "# Pertama\n"),
            ("# First\n\n## Second\n", "# Pertama\n\n### Kedua\n"),
        ):
            with self.subTest(source=source):
                errors, _ = self.parity(source, translated)
                self.assertIn("[heading hierarchy]", errors)
                self.assertIn("Technical alignment was not attempted", errors)

    def test_setext_headings_and_heading_like_fenced_text_use_real_parser(self) -> None:
        errors, _ = self.parity(
            "Title\n=====\n\n```text\n# not a section\n```\n",
            "Judul lain\n=====\n\n```text\n# bukan bagian\n```\n",
        )
        self.assertEqual(errors, "")

    def test_removed_table_row_and_changed_columns_fail(self) -> None:
        source = "# Backends\n\n| Backend | Release |\n| --- | --- |\n| `FirstEngine` | **v1.2.3** |\n| `NewEngine` | **v4.5.6** |\n"
        for translated in (
            "# Penyimpanan\n\n| Backend | Rilis |\n| --- | --- |\n| `FirstEngine` | **v1.2.3** |\n",
            "# Penyimpanan\n\n| Backend |\n| --- |\n| `FirstEngine` |\n| `NewEngine` |\n",
        ):
            with self.subTest(translated=translated):
                errors, _ = self.parity(source, translated)
                self.assertIn("[table dimensions]", errors)

    def test_new_backend_and_version_need_no_checker_modification(self) -> None:
        source = "# New feature\n\nUse `NovelEngine` with **v12.4.5** and `driver>=3.4,<4.0`.\n"
        translated = "# Fitur terbaru\n\nGunakan `NovelEngine` dengan **12.4.5** dan `driver >= 3.4, < 4.0`.\n"
        self.assertEqual(self.parity(source, translated), ("", ""))
        errors, _ = self.parity(
            source,
            translated.replace("12.4.5", "12.4.4").replace("NovelEngine", "OldEngine"),
        )
        self.assertIn("[version tokens]", errors)
        self.assertIn("[inline identifiers]", errors)

    def test_new_source_version_and_stale_counterpart_fail_despite_fresh_hash(
        self,
    ) -> None:
        for source, translated in (
            ("# Release\n\n**v1.2.3**, **v2.3.4**\n", "# Rilis\n\n**v1.2.3**\n"),
            (
                "# Release\n\n`client>=1.3.0,<2.0.0`\n",
                "# Rilis\n\n`client>=1.2.0,<2.0.0`\n",
            ),
        ):
            with self.subTest(source=source):
                errors, _ = self.parity(source, translated)
                self.assertIn("[version tokens]", errors)
                self.assertNotIn("stale source hash", errors)
                self.assertIn("README.md:", errors)

    def test_ranges_wildcards_prefixes_and_spacing_normalize_generically(self) -> None:
        source = "# Versions\n\n**3.11\u20133.14**; **v7.8**, **7.8.x**, **7.8.9**; `pkg>=1.2,<=1.9`\n"
        translated = "# Versi\n\n**>= 3.11, <= 3.14**; **7.8**, **7.8.X**, **v7.8.9**; `pkg >= 1.2, <= 1.9`\n"
        self.assertEqual(self.parity(source, translated), ("", ""))

    def test_technical_versions_match_despite_emphasis_differences(self) -> None:
        source = "# Releases\n\n| Pair |\n| --- |\n| **16.15 / 0.8.7** |\n"
        translated = "# Rilis\n\n| Pasangan |\n| --- |\n| 16.15 / 0.8.7 |\n"
        self.assertEqual(self.parity(source, translated), ("", ""))

    def test_versions_are_compared_per_cell_and_section(self) -> None:
        source = "# One\n\n| Server | Driver |\n| --- | --- |\n| **v1.2.3** | **v4.5.6** |\n\n# Two\n\n**v7.8.9**\n"
        translated = "# Satu\n\n| Server | Driver |\n| --- | --- |\n| **v4.5.6** | **v1.2.3** |\n\n# Dua\n\n**v7.8.9**\n"
        errors, _ = self.parity(source, translated)
        self.assertIn("table row 2, column 1", errors)
        self.assertIn("[version tokens]", errors)
        errors, _ = self.parity(
            source,
            source.replace("v1.2.3", "TEMP")
            .replace("v7.8.9", "v1.2.3")
            .replace("TEMP", "v7.8.9"),
        )
        self.assertIn("[version tokens]", errors)

    def test_missing_code_block_fails_but_localized_code_and_hints_can_pass(
        self,
    ) -> None:
        source = '# Example\n\n```python\nprint("Completed")\n```\n'
        errors, _ = self.parity(source, "# Contoh\n\nTanpa contoh.\n")
        self.assertIn("[code blocks]", errors)
        self.assertEqual(
            self.parity(source, '# Contoh\n\n```python\nprint("Selesai")\n```\n'),
            ("", ""),
        )
        errors, warnings = self.parity(
            source, '# Contoh\n\n```py\nprint("Selesai")\n```\n'
        )
        self.assertEqual(errors, "")
        self.assertIn("[code language]", warnings)

    def test_benchmark_figures_dates_addresses_hashes_and_fragments_are_not_versions(
        self,
    ) -> None:
        source = "# Measurements\n\n**330.3 ms**, **4.86 s**, threshold `0.92`, **1.0 / 1.0 / 1.0**, 2026.10.17, 12.34.56 UTC, `127.0.0.1`, `ee915140`, `#v1.2.3`, <https://example.invalid/v9.8.7>.\n"
        translated = "# Pengukuran\n\n**330,3 ms**, **4,86 s**, threshold `0,92`, **1,0 / 1,0 / 1,0**, 17.10.2026, 12:34:56 UTC, `127.0.0.2`, `abc12345`, `#v7.6.5`, <https://example.invalid/v1.2.3>.\n"
        self.assertEqual(self.parity(source, translated), ("", ""))

    def test_ambiguous_version_and_raw_html_mismatches_only_warn(self) -> None:
        errors, warnings = self.parity(
            "# Release\n\nUnadorned 1.2.3.\n", "# Rilis\n\nTanpa penanda 1.2.4.\n"
        )
        self.assertEqual(errors, "")
        self.assertIn("[version review]", warnings)
        errors, warnings = self.parity(
            "# Page\n\n<h2>Raw</h2>\n", "# Halaman\n\n<h2>Mentah</h2>\n"
        )
        self.assertEqual(errors, "")
        self.assertIn("[raw HTML]", warnings)

    def test_backticked_symbols_in_localized_headings_are_still_checked(self) -> None:
        source = "# Using `FutureEngine`\n\nExample.\n"
        self.assertEqual(
            self.parity(source, "# Menggunakan `FutureEngine`\n\nContoh.\n"), ("", "")
        )
        errors, _ = self.parity(source, "# Menggunakan `AnotherEngine`\n\nContoh.\n")
        self.assertIn("[inline identifiers]", errors)

    def test_unsupported_version_suffixes_warn_instead_of_validating_partial_versions(
        self,
    ) -> None:
        errors, warnings = self.parity(
            "# Release\n\n**v1.2.3-rc.1**\n", "# Rilis\n\n**v1.2.3-rc.2**\n"
        )
        self.assertEqual(errors, "")
        self.assertIn("[version review]", warnings)
        self.assertIn("rc.1", warnings)
        self.assertIn("rc.2", warnings)

    def test_cli_warnings_are_nonblocking_and_clearly_labeled(self) -> None:
        self.parity(
            "# Release\n\nUnadorned 1.2.3.\n", "# Rilis\n\nTanpa penanda 1.2.4.\n"
        )
        with (
            patch.object(checker, "__file__", str(self.root / "ops/ci/checker.py")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(checker.main([]), 0)
        self.assertIn("WARNING:", stderr.getvalue())

    def test_two_part_only_numeric_bounds_are_advisory_not_assumed_versions(
        self,
    ) -> None:
        errors, warnings = self.parity(
            "# Numbers\n\nscore >=0.92\n", "# Angka\n\nskor >=0,92\n"
        )
        self.assertEqual(errors, "")
        self.assertIn("[version review]", warnings)

    def test_formatting_cannot_split_a_reliable_version_constraint(self) -> None:
        source = "# Constraints\n\n**>=1.2.3, <2.0.0**\n"
        translated = "# Batas\n\n**>=** 1.2.3, **<** 2.0.0\n"
        self.assertEqual(self.parity(source, translated), ("", ""))

    def test_current_repository_pair(self) -> None:
        self.assertEqual(checker.validate(Path(__file__).resolve().parents[2]), [])


if __name__ == "__main__":
    unittest.main()
