"""Certify the two pinned SQLite WAL backports from packages/cache.

This CI-only harness builds verified sources, executes real tests, and checks an
independently installed wheel. Mocked unit controls do not certify a runtime.
"""

# ruff: noqa: S101, S603, T201
# Preserve the harness's assertions/stdout and fixed commands on verified sources.

from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.request import urlopen
from xml.etree import ElementTree

TARGETS = (
    (
        "3.44.6",
        "863c171b76cd36e0c71662d4a50d84da531cc7fbead893d02459577febdf6396",
        "c25cd42f803d5fb0af5f1a2863c9f529a8fd35177cb24b0f6e970b1cc96f00f0",
    ),
    (
        "3.50.7",
        "c7facf7ac58d2cdac619a2da838c5fd5c5270f52b3458c7881b5a4fca1ca4791",
        "1cfdfb3758c25cf3c0f7d2eea5223f49ccb71217ddcccf6a9ce9c304fea80bbe",
    ),
)
TEST_FILES = (
    "tests/test_sqlite.py",
    "tests/test_sqlite_faults.py",
    "tests/test_sqlite_processes.py",
    "tests/test_sqlite_conformance.py",
)


def source_tree(work: Path, version: str, source_id: str, archive_sha: str) -> Path:
    """Download and unpack one verified source into an owned temporary directory.

    Args:
        work: Newly created target directory owned by this invocation.
        version: Expected source VERSION.
        source_id: Pinned upstream manifest identity.
        archive_sha: Expected SHA-256 of the compressed source archive.

    Returns:
        The single extracted source root, with version and manifest verified.

    Raises:
        AssertionError: If source integrity or identity does not match.
        OSError: If download or filesystem access fails.
        tarfile.TarError: If extraction fails, including unsafe archive members.
    """
    archive = work / "source.tar.gz"
    with urlopen(
        f"https://sqlite.org/src/tarball/{source_id}/sqlite.tar.gz", timeout=60
    ) as response:
        archive.write_bytes(response.read())
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha, (
        "Source archive mismatch"
    )
    source = work / "source"
    source.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(source, filter="data")
    (tree,) = source.iterdir()
    assert (tree / "VERSION").read_text().strip() == version, "Source VERSION mismatch"
    assert (tree / "manifest.uuid").read_text().strip() == source_id, (
        "Source manifest identity mismatch"
    )
    return tree


def verify_runtime(
    python: str, env: dict[str, str], version: str, source_id: str
) -> None:
    """Probe the actual linked SQLite version, source and threadsafety in Python.

    Raises:
        subprocess.CalledProcessError: If the interpreter or a runtime check fails.
        subprocess.TimeoutExpired: If the existing 20-second probe budget expires.
    """
    probe = (
        "import platform,sqlite3; "
        "c=sqlite3.connect(':memory:'); source=c.execute('SELECT sqlite_source_id()').fetchone()[0]; c.close(); "
        f"assert sqlite3.sqlite_version == {version!r}; "
        f"assert source.endswith({source_id!r}); "
        "assert sqlite3.threadsafety == 3; "
        "print('Verified runtime:',platform.python_version(),sqlite3.sqlite_version,sqlite3.threadsafety,source)"
    )
    subprocess.run([python, "-c", probe], env=env, check=True, timeout=20)


def verify_tests(report: Path) -> int:
    """Require successful JUnit outcomes and presence of every selected module.

    Returns:
        Number of reported passing cases, using the original module-level guard.

    Raises:
        AssertionError: If outcomes are empty/unsuccessful or a module is absent.
        OSError: If the report is missing or unreadable.
        ElementTree.ParseError: If JUnit is malformed.
    """
    cases = ElementTree.parse(report).findall(".//testcase")  # noqa: S314 -- local pytest evidence
    assert cases, "Required SQLite outcomes missing or unsuccessful"
    assert all(
        c.find(outcome) is None
        for c in cases
        for outcome in ("skipped", "failure", "error")
    ), "Required SQLite outcomes missing or unsuccessful"
    for test_file in TEST_FILES:
        module = test_file.removesuffix(".py").replace("/", ".")
        assert any(
            c.get("classname", "") == module
            or c.get("classname", "").startswith(module + ".")
            for c in cases
        ), f"Required module not exercised: {module}"
    return len(cases)


def main() -> None:
    """Run the unchanged backport procedure; propagate failures after temp cleanup.

    Run directly from packages/cache with its development environment. The
    artifact checker is loaded by path because a script's import root is ops/ci,
    unlike the former inline program's packages/cache import root.

    Raises:
        ValueError: If the package working directory is missing required inputs.
    """
    checker = Path("tests/check_artifacts.py")
    if not checker.is_file() or not Path("pyproject.toml").is_file():
        raise ValueError("Run SQLite backport certification from packages/cache")
    check_artifacts = cast(
        "Callable[[Path], None]", runpy.run_path(str(checker))["main"]
    )
    with tempfile.TemporaryDirectory(prefix="semantix-sqlite-backports-") as directory:
        root = Path(directory)
        dist = root / "dist"
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(dist)],
            check=True,
            timeout=180,
        )
        check_artifacts(dist)
        wheel_python = root / "consumer/bin/python"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(root / "consumer")],  # noqa: S607 -- uv is provisioned on PATH by the workflow
            check=True,
            timeout=60,
        )
        subprocess.run(
            [  # noqa: S607 -- uv is provisioned on PATH by the workflow
                "uv",
                "pip",
                "install",
                "--python",
                str(wheel_python),
                str(next(dist.glob("*.whl"))),
            ],
            check=True,
            timeout=180,
        )
        for version, source_id, archive_sha in TARGETS:
            work = root / version
            work.mkdir()
            tree = source_tree(work, version, source_id, archive_sha)
            for command in (
                ["./configure", "--disable-shared"],
                ["make", "-j2", "sqlite3.c"],
                [
                    "cc",
                    "-O2",
                    "-fPIC",
                    "-shared",
                    "-DSQLITE_THREADSAFE=1",
                    str(tree / "sqlite3.c"),
                    "-o",
                    str(work / "libsqlite3.so.0"),
                    "-lpthread",
                    "-ldl",
                    "-lm",
                ],
            ):
                subprocess.run(command, cwd=tree, check=True, timeout=180)
            env = os.environ | {"LD_LIBRARY_PATH": str(work)}
            env.pop("PYTHONPATH", None)
            for python in (sys.executable, str(wheel_python)):
                verify_runtime(python, env, version, source_id)
            print("Verified source archive SHA256:", archive_sha, flush=True)
            print(
                "Built library SHA256:",
                hashlib.sha256((work / "libsqlite3.so.0").read_bytes()).hexdigest(),
                flush=True,
            )
            report = Path(f".cache/sqlite-backport-{version}.xml")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *TEST_FILES,
                    f"--junitxml={report}",
                ],
                env=env,
                check=True,
                timeout=180,
            )
            count = verify_tests(report)
            subprocess.run(
                [str(wheel_python), "-m", "tests.sqlite_wheel_smoke"],
                env=env,
                check=True,
                timeout=60,
            )
            print(
                f"Verified SQLite {version}: {count} passing cases, zero skips; installed-wheel consumer passed",
                flush=True,
            )


if __name__ == "__main__":
    main()
