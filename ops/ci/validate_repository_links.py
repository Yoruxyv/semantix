"""Validate current-main GitHub URLs locally, using Lychee's Markdown/HTML parser."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

LYCHEE = shutil.which("lychee")
if LYCHEE is None:
    raise FileNotFoundError("Install Lychee before running repository link validation")

INPUTS = ("./**/*.md", "./**/*.html")


def local_target(url: str, repository: str, root: Path, files: set[str]) -> str | None:
    parts = urlsplit(url)
    prefix = f"/{repository}/"
    if parts.scheme != "https" or parts.netloc != "github.com":
        return None
    if not parts.path.startswith(prefix):
        return None
    kind, ref, raw_path = [*parts.path[len(prefix) :].split("/", 2), "", ""][:3]
    if kind not in {"blob", "tree"} or ref != "main":
        return None
    # Fail closed on ambiguous encodings instead of validating a different path.
    if re.search(r"%(?![0-9a-fA-F]{2})|%2f|%5c", raw_path, re.IGNORECASE):
        raise ValueError(f"Unsupported path encoding: {url}")
    path = unquote(raw_path, errors="strict")
    segments = path.rstrip("/").split("/")
    if not path or any(s in {"", ".", ".."} for s in segments) or "\\" in path:
        raise ValueError(f"Invalid repository path: {url}")
    directories = {
        str(p) for f in files for p in PurePosixPath(f).parents if str(p) != "."
    }
    expected = files if kind == "blob" else directories
    if path.rstrip("/") not in expected or (kind == "blob" and path.endswith("/")):
        raise ValueError(f"Missing, wrong-case, or wrong-type {kind} target: {url}")
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError(f"Symlink target is not supported: {url}")
    if (kind == "blob" and not target.is_file()) or (
        kind == "tree" and not target.is_dir()
    ):
        raise ValueError(f"Target is absent from checkout: {url}")
    if parts.fragment and (
        kind != "blob" or target.suffix.lower() not in {".md", ".html"}
    ):
        raise ValueError(
            f"Unsupported fragment target (requires Markdown or HTML file): {url}"
        )
    if parts.fragment:
        target.read_text(encoding="utf-8")
    return target.as_uri() + ("#" + parts.fragment if parts.fragment else "")


def check_fragments(targets: list[str], root: Path) -> None:
    if targets:
        subprocess.run(  # noqa: S603 -- fixed argv; URLs go to stdin, never a shell
            [LYCHEE, "--offline", "--include-fragments", "--no-progress", "-"],
            input="\n".join(f"<{target}>" for target in targets),
            text=True,
            cwd=root,
            check=True,
            timeout=120,
        )


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("Git is required to validate tracked paths")
    files = set(
        subprocess.check_output(  # noqa: S603 -- fixed Git arguments, no shell
            [git, "ls-files", "-z"], cwd=root, timeout=30
        )
        .decode()
        .split("\0")
    ) - {""}
    urls = subprocess.check_output(  # noqa: S603 -- fixed Lychee inputs, no shell
        [LYCHEE, "--dump", "--include-fragments", "--root-dir", str(root), *INPUTS],
        cwd=root,
        timeout=60,
        text=True,
    ).splitlines()
    targets = []
    for url in urls:
        target = local_target(url, os.environ["GITHUB_REPOSITORY"], root, files)
        if target is not None:
            targets.append(target)
    check_fragments(targets, root)
    sys.stdout.write(
        f"Validated {len(targets)} current-main repository URLs, including fragments.\n"
    )


if __name__ == "__main__":
    main()
