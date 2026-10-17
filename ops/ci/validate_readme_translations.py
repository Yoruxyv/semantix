"""Root README freshness and conservative Markdown parity; human review is mandatory.

Root translations: docs/translation/*/README.*.md (README.md indexes excluded).
Install CI-only tools:

    python -m pip install --require-hashes --only-binary=:all: -r ops/ci/readme-requirements.txt

After translating/reviewing, refresh metadata:

    python ops/ci/validate_readme_translations.py --update

Hashes use UTF-8 with LF newlines. No heading/backend/version/link inventories or
translation mappings exist. markdown-it-py supplies CommonMark + Markdown tables;
Lychee and the repository-link guard still own link/anchor validation.

Blocking: matching heading-level sequences, ordered table dimensions, code-block
counts, missing version/range tokens in explicit technical contexts, and missing
unambiguous backticked symbols. Sections/cells correspond by document position;
if hierarchy differs, technical matching stops instead of guessing. Same-level
semantic reordering cannot be proven. Translated prose/headings, code contents,
formatting and relative links may differ.

Warnings: ambiguous/unsupported version forms, additional versions, code-language
hint changes and unmapped raw HTML structures. Bare two-part decimals/ranges are not
software versions without a prefix or a clearer version-list context. Dates, URLs,
IPv4 addresses, hashes and measurement forms are excluded conservatively. These
syntactic checks cannot establish software identity or semantic equivalence.

CI supplies --base COMMIT on PRs/pushes, also requiring previous translations to
exist and rejecting hash/whitespace-only acknowledgements of changed source text.
For an English-only correction, an explanatory translation comment is reviewable
evidence, not proof of correctness. Without --base, Git change checks do not run.
Local pre-commit uses --staged: irrelevant commits bypass Markdown validation;
relevant content must match the index and is compared with HEAD. The commit hook
hides unstaged tracked edits; manual runs reject mixed staged/unstaged README edits.
No hook ever runs --update. CI remains authoritative because local hooks are optional.
Review meaning, omissions, code semantics and correctness manually in every case.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it.token import Token

PATTERN = "docs/translation/*/README.*.md"
MARKER = "readme-source-sha256:"
METADATA = re.compile(r"\A<!-- readme-source-sha256: ([0-9a-f]{64}) -->\n")


# Numeric forms are syntax, not evidence of a software product's identity.
VERSION = re.compile(
    r"(?P<operator>>=|<=|==|!=|~=|>|<|=|≥|≤)?\s*(?<![\w./#])(?P<value>v?\d+\.(?:\d+|x|\*)(?:\.(?:\d+|x|\*))?)(?!\w|\.\w)",
    re.I,
)
MEASUREMENTS = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)*(?:\s*[-\u2013→±/]\s*\d+(?:[.,]\d+)*)*\s*(?:%|[num\u00b5kKMGT]?(?:s|i?B|Hz)\b)"
)


@dataclass
class Section:
    title: str
    level: int
    line: int
    tokens: list[Token] = field(default_factory=list)


@dataclass
class Table:
    line: int
    rows: list[list[Token]] = field(default_factory=list)


def read_sections(text: str) -> list[Section]:
    try:
        # Unrelated commits need no parser dependencies.
        from markdown_it import MarkdownIt  # noqa: PLC0415
        from markdown_it.token import Token  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Install README checker tools in the active Python environment: python -m pip install --require-hashes --only-binary=:all: -r ops/ci/readme-requirements.txt"
        ) from exc
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    result = [Section("introduction", 0, 1)]
    in_heading = False
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            result.append(
                Section(
                    tokens[index + 1].content,
                    int(token.tag[1:]),
                    (token.map or [0])[0] + 1,
                )
            )
            in_heading = True
        elif token.type == "heading_close":
            in_heading = False
        elif not in_heading:
            result[-1].tokens.append(token)
        elif token.type == "inline":
            result[-1].tokens.append(
                Token(
                    "inline",
                    "",
                    0,
                    map=token.map,
                    children=[
                        c for c in token.children or [] if c.type == "code_inline"
                    ],
                )
            )
    return result


def read_tables(tokens: list[Token]) -> list[Table]:
    result: list[Table] = []
    in_table = False
    for token in tokens:
        if token.type == "table_open":
            result.append(Table((token.map or [0])[0] + 1))
            in_table = True
        elif token.type == "table_close":
            in_table = False
        elif in_table and token.type == "tr_open":
            result[-1].rows.append([])
        elif in_table and token.type == "inline":
            result[-1].rows[-1].append(token)
    return result


def date_like(value: str) -> bool:
    parts = value.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        if len(parts[-1]) == 4:
            parts = parts[::-1]
        if len(parts[0]) == 4:
            try:
                date(*map(int, parts))
            except ValueError:
                return False
            return True
    return False


def versions(text: str, *, explicit: bool) -> tuple[set[str], set[str]]:
    text = re.sub(r"\b\w[\w+.-]*://\S+", "", text)
    text = MEASUREMENTS.sub("", text)
    matches = [
        m
        for m in VERSION.finditer(text)
        if m["operator"]
        or m["value"].startswith(("v", "V"))
        or not date_like(m["value"])
    ]
    reliable: set[str] = set()
    uncertain: set[str] = set()
    ranged: set[int] = set()
    for index, (left, right) in enumerate(pairwise(matches)):
        if (
            not left["operator"]
            and not right["operator"]
            and re.fullmatch(r"\s*[-\u2013\u2014]\s*", text[left.end() : right.start()])
        ):
            anchored_range = explicit and any(
                m["value"].count(".") == 2
                or m["value"].lower().startswith("v")
                or "x" in m["value"].lower()
                for m in (left, right)
            )
            destination = reliable if anchored_range else uncertain
            destination.update(
                (
                    ">=" + left["value"].lower().removeprefix("v"),
                    "<=" + right["value"].lower().removeprefix("v"),
                )
            )
            ranged.update((index, index + 1))
    grouped = any(m["value"].count(".") == 2 for m in matches) and all(
        re.fullmatch(r"[\s/,;]+", text[a.end() : b.start()])
        for a, b in pairwise(matches)
    )
    for index, match in enumerate(matches):
        if index in ranged or re.match(r"\s*(?:UTC|GMT|Z)\b", text[match.end() :]):
            continue
        suffix = re.match(r"[-+][A-Za-z0-9][A-Za-z0-9.+-]*", text[match.end() :])
        if suffix:
            uncertain.add(
                match["value"].removeprefix("v").removeprefix("V") + suffix[0]
            )
            continue
        value = match["value"].lower().removeprefix("v").replace("*", "x")
        operator = (match["operator"] or "").replace("≥", ">=").replace("≤", "<=")
        if (
            (operator and (value.count(".") == 2 or grouped))
            or match["value"].lower().startswith("v")
            or "x" in value
            or (explicit and (value.count(".") == 2 or grouped))
        ):
            reliable.add(operator + value)
        else:
            # Bare decimals can match an explicit source version but do not establish one.
            uncertain.add(operator + value)
    return reliable, uncertain


def identifier(value: str) -> set[str]:
    value = re.sub(r"\s*([=])\s*", r"\1", value)
    dependency = re.match(r"^([A-Za-z_][\w.-]*)\s*[<>=!~]", value)
    if dependency:
        return {dependency[1]}
    if not re.fullmatch(
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\(\))?", value
    ) or re.fullmatch(r"[0-9a-fA-F]{7,}", value):
        return set()
    # A short lowercase suffix may be a localized filename, not an API symbol.
    if re.search(r"\.[a-z]{1,5}$", value):
        return set()
    if (
        "_" in value
        or value.endswith("()")
        or value.isupper()
        or re.search(r"[a-z][A-Z]", value)
    ):
        return {value}
    return set()


def evidence(tokens: list[Token]) -> tuple[set[str], set[str], set[str]]:
    reliable: set[str] = set()
    uncertain: set[str] = set()
    identifiers: set[str] = set()
    in_table = False
    for token in tokens:
        if token.type == "table_open":
            in_table = True
        elif token.type == "table_close":
            in_table = False
        elif token.type == "inline" and not in_table:
            exact_text, possible_text = versions(
                "".join(
                    c.content
                    for c in token.children or []
                    if c.type in {"text", "code_inline", "softbreak"}
                ),
                explicit=False,
            )
            reliable.update(exact_text)
            uncertain.update(possible_text)
            strong = 0
            for child in token.children or []:
                if child.type == "strong_open":
                    strong += 1
                elif child.type == "strong_close":
                    strong -= 1
                elif child.type in {"text", "code_inline"}:
                    exact, possible = versions(
                        child.content,
                        explicit=bool(strong) or child.type == "code_inline",
                    )
                    reliable.update(exact)
                    uncertain.update(possible)
                    if child.type == "code_inline":
                        identifiers.update(identifier(child.content))
    return reliable, uncertain, identifiers


def compare_tokens(
    source: list[Token], translated: list[Token], location: str
) -> tuple[list[str], list[str]]:
    expected, possible, names = evidence(source)
    actual, local_possible, local_names = evidence(translated)
    errors = []
    warnings = []
    missing_versions = expected - actual - local_possible
    if missing_versions:
        errors.append(
            f"{location} [version tokens]: restore normalized technical version/range tokens {sorted(missing_versions)}"
        )
    if names - local_names:
        errors.append(
            f"{location} [inline identifiers]: restore technical symbols {sorted(names - local_names)}"
        )
    additional = actual - expected - possible
    known_values = {v.lstrip("<>=!~") for v in expected | actual}
    possible -= known_values
    local_possible -= known_values
    possible = {v for v in possible if v.count(".") >= 2 or re.match(r"[<>=!~]", v)}
    local_possible = {
        v for v in local_possible if v.count(".") >= 2 or re.match(r"[<>=!~]", v)
    }
    if (
        additional
        or (possible - actual - local_possible)
        or (local_possible - expected - possible)
    ):
        warnings.append(
            f"{location} [version review]: additional/ambiguous version-shaped literals differ; source={sorted(possible)}, translation={sorted(local_possible)}, additional={sorted(additional)}. Review meaning; these are not enforced as software versions."
        )
    return errors, warnings


def compare_structure(
    source: str, translated: str, path: str
) -> tuple[list[str], list[str]]:
    original, localized = read_sections(source), read_sections(translated)
    errors = []
    warnings = []
    if [s.level for s in original] != [s.level for s in localized]:
        index = next(
            (
                i
                for i, (a, b) in enumerate(zip(original, localized, strict=False))
                if a.level != b.level
            ),
            min(len(original), len(localized)),
        )
        expected = (
            f"h{original[index].level} at README.md:{original[index].line}"
            if index < len(original)
            else "end of source"
        )
        found = (
            f"h{localized[index].level} at line {localized[index].line}"
            if index < len(localized)
            else "end of translation"
        )
        return [
            f"{path} [heading hierarchy]: section position {index}: expected {expected}, found {found}; restore section count/order/levels. Labels may differ. Technical alignment was not attempted."
        ], []
    for a, b in zip(original, localized, strict=True):
        location = f"{path}:{b.line} (source README.md:{a.line}, {a.title!r})"
        failures, notes = compare_tokens(a.tokens, b.tokens, location)
        errors.extend(failures)
        warnings.extend(notes)
        left, right = read_tables(a.tokens), read_tables(b.tokens)
        if [[len(row) for row in t.rows] for t in left] != [
            [len(row) for row in t.rows] for t in right
        ]:
            errors.append(
                f"{location} [table dimensions]: expected row/column shapes {[[len(row) for row in t.rows] for t in left]}, found {[[len(row) for row in t.rows] for t in right]}; restore corresponding tables before technical cell comparison"
            )
        else:
            for source_table, local_table in zip(left, right, strict=True):
                for row_index, (row, local_row) in enumerate(
                    zip(source_table.rows, local_table.rows, strict=True), 1
                ):
                    for column, (cell, local_cell) in enumerate(
                        zip(row, local_row, strict=True), 1
                    ):
                        failures, notes = compare_tokens(
                            [cell],
                            [local_cell],
                            f"{path}:{local_table.line} [table row {row_index}, column {column}; source README.md:{source_table.line}]",
                        )
                        errors.extend(failures)
                        warnings.extend(notes)
        source_code = [t for t in a.tokens if t.type in {"fence", "code_block"}]
        local_code = [t for t in b.tokens if t.type in {"fence", "code_block"}]
        if len(source_code) != len(local_code):
            errors.append(
                f"{location} [code blocks]: expected {len(source_code)}, found {len(local_code)}; restore corresponding examples (localized contents are allowed)"
            )
        elif [t.info.split()[:1] for t in source_code] != [
            t.info.split()[:1] for t in local_code
        ]:
            warnings.append(
                f"{location} [code language]: language hints differ; review intentional alternatives. Code bodies are not compared byte-for-byte."
            )
        if any(
            t.type == "html_block"
            and re.search(r"<(?:h[2-6]|table|pre)\b", t.content, re.I)
            for t in a.tokens + b.tokens
        ):
            warnings.append(
                f"{location} [raw HTML]: section/table/code structure in raw HTML is not mapped; review manually."
            )
    return errors, warnings


def git(root: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise FileNotFoundError("Git is required for README change comparison")
    return (
        subprocess.check_output(  # noqa: S603 -- fixed commands and validated commit SHA; no shell
            [executable, *arguments], cwd=root, timeout=30, stderr=subprocess.PIPE
        )
        .decode("utf-8")
        .replace("\r\n", "\n")
    )


def staged_base(root: Path) -> str | None:
    """Select actual index changes, including deletions pre-commit omits."""

    def relevant(path: str) -> bool:
        return path == "README.md" or PurePosixPath(path).match(PATTERN)

    paths = ("--", "README.md", "docs/translation")
    changed = git(root, "diff", "--cached", "--name-only", "--no-renames", "-z", *paths)
    if not any(relevant(path) for path in changed.split("\0")):
        return None
    unstaged = git(root, "diff", "--name-only", "--no-renames", "-z", *paths)
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", *paths)
    pending = sorted(
        path for path in (unstaged + untracked).split("\0") if relevant(path)
    )
    if pending:
        raise ValueError(
            "README pre-commit requires index/working-tree agreement; stage the reviewed README changes or set unstaged work aside: "
            + ", ".join(pending)
        )
    return git(root, "rev-parse", "--verify", "HEAD").strip()


def content(text: str) -> str:
    """Ignore only the acknowledgement and whitespace; do not infer prose meaning."""
    return " ".join(METADATA.sub("", text, count=1).split())


def discover(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.glob(PATTERN)}


def validate(
    root: Path, base: str | None = None, warnings: list[str] | None = None
) -> list[str]:
    errors = []
    try:
        source = (root / "README.md").read_text(encoding="utf-8")
        if not source.strip():
            raise ValueError("README.md is empty; restore the canonical source")
        paths = discover(root)
        old_paths: set[str] = set()
        changed_source = False
        if base is not None:
            if re.fullmatch(r"[0-9a-f]{40}", base) is None:
                raise ValueError("--base must be an exact 40-character commit SHA")
            changed_source = content(git(root, "show", f"{base}:README.md")) != content(
                source
            )
            old_paths = {
                p
                for p in git(
                    root,
                    "ls-tree",
                    "-r",
                    "-z",
                    "--name-only",
                    base,
                    "--",
                    "docs/translation",
                ).split("\0")
                if PurePosixPath(p).match(PATTERN)
            }
        paths |= old_paths
        if not paths:
            return [
                f"No root README translations found: restore translations matching {PATTERN}"
            ]
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        return [
            f"Cannot validate README freshness/base comparison (fetch the exact --base commit first): {exc}"
        ]
    digest = hashlib.sha256(source.encode()).hexdigest()
    for path in sorted(paths):
        try:
            text = (root / path).read_text(encoding="utf-8")
            failures, notes = compare_structure(source, text, path)
            errors.extend(failures)
            if warnings is not None:
                warnings.extend(notes)
            metadata = METADATA.match(text)
            if metadata is None or text.count(MARKER) != 1:
                errors.append(
                    f"{path}: malformed metadata; keep one first-line <!-- {MARKER} SHA256 --> comment; review then run --update"
                )
                continue
            if not text[metadata.end() :].strip():
                errors.append(
                    f"{path}: translation content is empty; restore the reviewed translation"
                )
            if metadata[1] != digest:
                errors.append(
                    f"{path}: stale source hash; synchronize/review against README.md, then run python ops/ci/validate_readme_translations.py --update"
                )
            if (
                changed_source
                and path in old_paths
                and content(text) == content(git(root, "show", f"{base}:{path}"))
            ):
                errors.append(
                    f"{path}: README.md changed but only hash/whitespace changed here; update the translation or explain an English-only correction in a review comment within the translation"
                )
        except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
            errors.append(
                f"{path}: missing/unreadable translation or base content; restore it: {exc}"
            )
    return errors


def update(root: Path) -> list[str]:
    """Refresh acknowledgements explicitly, without claiming semantic correctness."""
    source = (root / "README.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    paths = sorted(discover(root))
    if not paths:
        raise ValueError(f"No root translations found matching {PATTERN}")
    updates = {}
    for path in paths:
        file = root / path
        text = file.read_text(encoding="utf-8")
        metadata = METADATA.match(text)
        body = text[metadata.end() :] if metadata else "\n" + text
        if MARKER in body:
            raise ValueError(
                f"{path}: repair malformed/duplicate metadata before --update"
            )
        updates[file] = f"<!-- {MARKER} {digest} -->\n" + body
    for file, text in updates.items():
        file.write_text(text, encoding="utf-8", newline="\n")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--base", help="exact PR base / push-before commit SHA already fetched locally"
    )
    modes.add_argument(
        "--staged",
        action="store_true",
        help="validate staged README changes against HEAD without updating acknowledgements",
    )
    modes.add_argument(
        "--update",
        action="store_true",
        help="refresh source hashes after human translation review",
    )
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        if arguments.update:
            paths = update(root)
            sys.stdout.write(
                f"Updated source acknowledgements: {', '.join(paths)}. This does not certify translation accuracy; human review is required.\n"
            )
            return 0
        base = arguments.base
        if arguments.staged:
            base = staged_base(root)
            if base is None:
                sys.stdout.write(
                    "No staged root README changes; translation validation not needed.\n"
                )
                return 0
        warnings: list[str] = []
        errors = validate(root, base, warnings)
        for warning in warnings:
            sys.stderr.write("WARNING: " + warning + "\n")
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        errors = [str(exc)]
    if errors:
        sys.stderr.write(
            "README translation freshness failed:\n" + "\n".join(errors) + "\n"
        )
        return 1
    sys.stdout.write(
        "README freshness and reliable Markdown checks passed. Human semantic review remains required.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
