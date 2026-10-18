"""Controlled failure tests, not evidence of real PostgreSQL compatibility."""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "postgresql_candidate_certification.py"
spec = importlib.util.spec_from_file_location(
    "postgresql_candidate_certification", SCRIPT
)
assert spec is not None
assert spec.loader is not None
certification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certification)
EXPORT = "asyncpg==0.31.0\nasyncpg-stubs==0.31.3\nnumpy==2.4.6\n"
SETTINGS = (
    "RUNNER_TEMP",
    "PGVECTOR_TEST_DATABASE_URL",
    "EXPECTED_POSTGRES_MAJOR",
    "EXPECTED_PGVECTOR_VERSION",
)
INPUTS = (
    ".coverage",
    ".venv/bin/python",
    "pyproject.toml",
    "../../ops/ci/required_tests.py",
    "tests/pgvector_wheel_smoke.py",
    "dist/semantix_cache-0.1.0-py3-none-any.whl",
)


@pytest.fixture
def procedure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[list[str]]]:
    package = tmp_path / "repo/packages/cache"
    package.mkdir(parents=True)
    for name in INPUTS:
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"controlled input\x00\xff")
    runner = tmp_path / "runner"
    runner.mkdir()
    for name, value in zip(
        SETTINGS, (str(runner), "disposable-test-only", "18", "0.8.7"), strict=True
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(package)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 240
        if command[1] == "export":
            assert kwargs["stdout"] == subprocess.PIPE
            assert kwargs["text"] is True
        else:
            assert kwargs == {"check": True, "timeout": 240}
        return subprocess.CompletedProcess(command, 0, stdout=EXPORT)

    monkeypatch.setattr(certification.subprocess, "run", run)
    return package, runner / "asyncpg-032", calls


def test_preserves_complete_procedure_and_tls_handoff(
    procedure: tuple[Path, Path, list[list[str]]],
) -> None:
    package, target, calls = procedure
    baseline = (package / ".coverage").read_bytes()
    certification.main()
    driver = str(target / "driver/bin/python")
    wheel = str(target / "wheel/bin/python")
    assert calls == [
        [
            "uv",
            "export",
            "--locked",
            "--extra",
            "dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-annotate",
        ],
        ["uv", "venv", "--python", ".venv/bin/python", str(target / "driver")],
        [
            "uv",
            "pip",
            "install",
            "--python",
            driver,
            "-r",
            str(target / "requirements.txt"),
            "--editable",
            ".[pgvector]",
        ],
        [driver, str(SCRIPT), "--verify-target"],
        [driver, "-m", "mypy", "src", "examples"],
        [
            driver,
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
            wheel,
            "dist/semantix_cache-0.1.0-py3-none-any.whl[pgvector]",
            "asyncpg==0.32.0",
        ],
        [wheel, "-c", "import asyncpg; assert asyncpg.__version__ == '0.32.0'"],
        [wheel, "-I", "tests/pgvector_wheel_smoke.py"],
    ]
    assert (
        target / "requirements.txt"
    ).read_text() == "asyncpg==0.32.0\nasyncpg-stubs==0.32.0\nnumpy==2.4.6\n"
    assert (target / "baseline.coverage").read_bytes() == baseline
    assert (package / ".coverage").read_bytes() == baseline


@pytest.mark.parametrize("stage", range(10))
@pytest.mark.parametrize(
    "failure", [subprocess.CalledProcessError, subprocess.TimeoutExpired]
)
def test_every_command_failure_or_timeout_stops_certification(
    procedure: tuple[Path, Path, list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    stage: int,
    failure: type[subprocess.CalledProcessError] | type[subprocess.TimeoutExpired],
) -> None:
    package, target, calls = procedure
    run = cast(
        "Callable[..., subprocess.CompletedProcess[str]]", certification.subprocess.run
    )

    def fail(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        result = run(command, **kwargs)
        if len(calls) == stage + 1:
            if failure is subprocess.CalledProcessError:
                raise subprocess.CalledProcessError(1, command)
            raise subprocess.TimeoutExpired(command, 240)
        return result

    monkeypatch.setattr(certification.subprocess, "run", fail)
    with pytest.raises(failure):
        certification.main()
    assert len(calls) == stage + 1
    assert (package / ".coverage").read_bytes() == (
        target / "baseline.coverage"
    ).read_bytes()
    # Failed evidence is retained, with no deletion of unrelated runner resources.
    assert target.is_dir()


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize("value", [None, ""])
def test_missing_settings_fail_before_commands(
    procedure: tuple[Path, Path, list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: str | None,
) -> None:
    _, target, calls = procedure
    if value is None:
        monkeypatch.delenv(setting)
    else:
        monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=setting):
        certification.main()
    assert not calls
    assert not target.exists()


@pytest.mark.parametrize("name", INPUTS)
def test_missing_inputs_fail_before_commands(
    procedure: tuple[Path, Path, list[list[str]]], name: str
) -> None:
    package, target, calls = procedure
    (package / name).unlink()
    with pytest.raises(ValueError, match="required input"):
        certification.main()
    assert not calls
    assert not target.exists()


@pytest.mark.parametrize("existing", ["directory", "file", "missing-parent"])
def test_never_reuses_or_cleans_other_temporary_resources(
    procedure: tuple[Path, Path, list[list[str]]], existing: str
) -> None:
    _, target, calls = procedure
    sentinel = target.parent / "unrelated"
    sentinel.write_bytes(b"preserved")
    if existing == "directory":
        target.mkdir()
        (target / "baseline.coverage").write_bytes(b"prior evidence")
    elif existing == "file":
        target.write_bytes(b"owned elsewhere")
    else:
        sentinel.unlink()
        target.parent.rmdir()
    with pytest.raises(
        FileExistsError if existing != "missing-parent" else FileNotFoundError
    ):
        certification.main()
    assert not calls
    if existing != "missing-parent":
        assert sentinel.read_bytes() == b"preserved"
        assert (
            (target / "baseline.coverage").read_bytes() == b"prior evidence"
            if target.is_dir()
            else target.read_bytes() == b"owned elsewhere"
        )


@pytest.mark.parametrize("name", [".coverage", "baseline.coverage"])
@pytest.mark.parametrize("remove", [False, True])
def test_coverage_change_or_loss_is_blocking(
    procedure: tuple[Path, Path, list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    remove: bool,
) -> None:
    package, target, _ = procedure
    run = cast(
        "Callable[..., subprocess.CompletedProcess[str]]", certification.subprocess.run
    )

    def mutate(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        result = run(command, **kwargs)
        if command[-1] == "tests/pgvector_wheel_smoke.py":
            path = (package if name == ".coverage" else target) / name
            if remove:
                path.unlink()
            else:
                path.write_bytes(b"modified")
        return result

    monkeypatch.setattr(certification.subprocess, "run", mutate)
    with pytest.raises(FileNotFoundError if remove else ValueError):
        certification.main()


def test_substitution_preserves_unrelated_locked_content() -> None:
    extra = "other==1.2.3 ; python_version >= '3.11'\n# asyncpg==0.31.0\nasyncpg-helper==0.31.0\n"
    assert (
        certification.candidate_requirements(EXPORT + extra)
        == EXPORT.replace("asyncpg==0.31.0", "asyncpg==0.32.0").replace(
            "asyncpg-stubs==0.31.3", "asyncpg-stubs==0.32.0"
        )
        + extra
    )


@pytest.mark.parametrize("pin", ["asyncpg==0.31.0", "asyncpg-stubs==0.31.3"])
@pytest.mark.parametrize("replacement", ["", "wrong==0.1", "duplicate"])
def test_missing_changed_or_duplicate_baseline_pins_fail(
    pin: str, replacement: str
) -> None:
    exported = EXPORT.replace(
        pin, pin + "\n" + pin if replacement == "duplicate" else replacement
    )
    with pytest.raises(ValueError, match="exactly one locked requirement"):
        certification.candidate_requirements(exported)


@pytest.mark.parametrize(
    "condition",
    [
        "valid",
        "major",
        "extension",
        "driver",
        "stubs",
        "query",
        "connect",
        "close",
        "cancel",
    ],
)
def test_probe_checks_real_values_and_closes_owned_connection(
    monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    monkeypatch.setenv("EXPECTED_POSTGRES_MAJOR", "18")
    monkeypatch.setenv("EXPECTED_PGVECTOR_VERSION", "0.8.7")
    monkeypatch.setenv("PGVECTOR_TEST_DATABASE_URL", "disposable-test-only")
    monkeypatch.setattr(
        certification,
        "version",
        lambda name: (
            "0.31.0"
            if condition == ("driver" if name == "asyncpg" else "stubs")
            else "0.32.0"
        ),
    )
    values = [
        "170010" if condition == "major" else "180006",
        "0.8.5" if condition == "extension" else "0.8.7",
    ]
    connection = AsyncMock()
    connection.fetchval.side_effect = (
        RuntimeError("controlled query failure")
        if condition == "query"
        else asyncio.CancelledError()
        if condition == "cancel"
        else values
    )
    if condition == "close":
        connection.close.side_effect = RuntimeError("controlled close failure")
    connect = AsyncMock(return_value=connection)
    if condition == "connect":
        connect.side_effect = TimeoutError("controlled connection timeout")
    monkeypatch.setattr(certification.asyncpg, "connect", connect)
    if condition == "valid":
        asyncio.run(certification.verify_target())
    else:
        error = (
            asyncio.CancelledError
            if condition == "cancel"
            else TimeoutError
            if condition == "connect"
            else RuntimeError
            if condition in {"query", "close"}
            else ValueError
        )
        with pytest.raises(error):
            asyncio.run(certification.verify_target())
    if condition in {"driver", "stubs"}:
        connect.assert_not_awaited()
    else:
        connect.assert_awaited_once_with(
            "disposable-test-only", timeout=10, command_timeout=10
        )
    if condition in {"driver", "stubs", "connect"}:
        connection.close.assert_not_awaited()
    else:
        connection.close.assert_awaited_once_with(timeout=10)
