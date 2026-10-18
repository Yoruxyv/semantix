"""Certify exact asyncpg 0.32.0 from packages/cache, retaining TLS consumers."""

# ruff: noqa: S603, T201
# Commands are fixed CI tools; stdout records certification evidence.

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
from importlib.metadata import version
from pathlib import Path

import asyncpg


def candidate_requirements(exported: str) -> str:
    """Replace only the two expected locked pins, rejecting baseline drift."""
    lines = exported.splitlines()
    for original, candidate in (
        ("asyncpg==0.31.0", "asyncpg==0.32.0"),
        ("asyncpg-stubs==0.31.3", "asyncpg-stubs==0.32.0"),
    ):
        if lines.count(original) != 1:
            raise ValueError(f"Expected exactly one locked requirement: {original}")
        lines[lines.index(original)] = candidate
    return "\n".join(lines) + "\n"


async def verify_target() -> None:
    """Check installed candidate packages and the actual disposable server.

    Raises:
        ValueError: If driver, stubs, PostgreSQL or pgvector differs from its target.
        KeyError: If the workflow did not supply a required environment setting.
    """
    major_target = os.environ["EXPECTED_POSTGRES_MAJOR"]
    vector_target = os.environ["EXPECTED_PGVECTOR_VERSION"]
    if version("asyncpg") != "0.32.0" or version("asyncpg-stubs") != "0.32.0":
        raise ValueError("Expected asyncpg and asyncpg-stubs exactly 0.32.0")
    connection = await asyncpg.connect(
        os.environ["PGVECTOR_TEST_DATABASE_URL"], timeout=10, command_timeout=10
    )
    try:
        major = int(await connection.fetchval("SHOW server_version_num")) // 10000
        vector = await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        )
        if str(major) != major_target:
            raise ValueError(f"Expected PostgreSQL {major_target}, got {major}")
        if vector != vector_target:
            raise ValueError(f"Expected pgvector {vector_target}, got {vector}")
        print(
            f"Verified candidate asyncpg 0.32.0, PostgreSQL {major}, pgvector {vector}"
        )
    finally:
        await connection.close(timeout=10)


def main() -> None:
    """Run the boundary certification; preserve environments for the TLS step.

    The workflow owns RUNNER_TEMP and the four-minute overall deadline. Each
    subprocess is bounded by that same ceiling; failures propagate without retry.
    Partial environments remain as evidence, never reused or recursively removed.

    Raises:
        ValueError: If required settings or package inputs are missing.
        FileExistsError: If this invocation does not own a fresh target directory.
        subprocess.CalledProcessError: If any mandatory command fails.
        subprocess.TimeoutExpired: If a command exceeds the workflow's ceiling.
    """
    for setting in (
        "RUNNER_TEMP",
        "PGVECTOR_TEST_DATABASE_URL",
        "EXPECTED_POSTGRES_MAJOR",
        "EXPECTED_PGVECTOR_VERSION",
    ):
        if not os.environ.get(setting):
            raise ValueError(f"Missing required environment setting: {setting}")
    wheel = "dist/semantix_cache-0.1.0-py3-none-any.whl"
    for required in (
        ".coverage",
        ".venv/bin/python",
        "pyproject.toml",
        "../../ops/ci/required_tests.py",
        "tests/pgvector_wheel_smoke.py",
        wheel,
    ):
        if not Path(required).is_file():
            raise ValueError(f"Run from packages/cache with required input: {required}")
    target = Path(os.environ["RUNNER_TEMP"]) / "asyncpg-032"
    target.mkdir()
    baseline = Path(".coverage").read_bytes()
    (target / "baseline.coverage").write_bytes(baseline)
    exported = subprocess.run(
        [  # noqa: S607 -- uv is provisioned by the workflow
            "uv",
            "export",
            "--locked",
            "--extra",
            "dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-annotate",
        ],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
        timeout=240,
    )
    (target / "requirements.txt").write_text(
        candidate_requirements(exported.stdout), encoding="utf-8"
    )
    driver_python = str(target / "driver/bin/python")
    wheel_python = str(target / "wheel/bin/python")
    for command in (
        ["uv", "venv", "--python", ".venv/bin/python", str(target / "driver")],
        [
            "uv",
            "pip",
            "install",
            "--python",
            driver_python,
            "-r",
            str(target / "requirements.txt"),
            "--editable",
            ".[pgvector]",
        ],
        [driver_python, str(Path(__file__).resolve()), "--verify-target"],
        [driver_python, "-m", "mypy", "src", "examples"],
        [
            driver_python,
            "../../ops/ci/required_tests.py",
            "postgresql",
            str(target / "tests.xml"),
            "--",
            "-m",
            "pgvector",
            "--no-cov",
        ],
        ["uv", "venv", "--python", ".venv/bin/python", str(target / "wheel")],
        [
            "uv",
            "pip",
            "install",
            "--python",
            wheel_python,
            wheel + "[pgvector]",
            "asyncpg==0.32.0",
        ],
        [wheel_python, "-c", "import asyncpg; assert asyncpg.__version__ == '0.32.0'"],
        [wheel_python, "-I", "tests/pgvector_wheel_smoke.py"],
    ):
        subprocess.run(command, check=True, timeout=240)
    if any(
        path.read_bytes() != baseline
        for path in (Path(".coverage"), target / "baseline.coverage")
    ):
        raise ValueError("Candidate certification modified baseline coverage")
    print(
        "Verified candidate typing, required pgvector tests, independent wheel and unchanged coverage",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-target", action="store_true")
    if parser.parse_args().verify_target:
        asyncio.run(verify_target())
    else:
        main()
