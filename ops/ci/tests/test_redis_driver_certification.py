"""Exercise the real Bash procedure using owned, non-network command stubs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "redis_driver_certification.sh"
GUARD = SCRIPT.with_name("required_tests.py")
EXPORT = "numpy==2.4.6\nredis==8.1.0\n# redis==8.1.0\nredis-helper==1.2.3\n"
INPUTS = (
    ".venv/bin/python",
    "pyproject.toml",
    "dist/semantix_cache-0.1.0-py3-none-any.whl",
    "tests/redis_infrastructure_smoke.py",
    "tests/redis_wheel_smoke.py",
    "../../ops/ci/required_tests.py",
)
SETTINGS = (
    "RUNNER_TEMP",
    "REDIS_TEST_URL",
    "REDIS_TEST_VERSION",
    "REDIS_TEST_CONTAINER",
)
STUB = r"""
import importlib.util, json, os, sys
from pathlib import Path
from xml.etree import ElementTree as ET
kind, *args = sys.argv[1:]
command = ['uv', *args] if kind == 'uv' else args
log = Path(os.environ['CONTROL_LOG'])
records = log.read_text().splitlines() if log.exists() else []
with log.open('a') as out:
    out.write(json.dumps({'command': command, 'settings': {k:os.environ.get(k) for k in ('REDIS_TEST_URL','REDIS_TEST_VERSION','REDIS_TEST_CONTAINER')}}) + '\n')
if len(records) == int(os.environ.get('CONTROL_FAIL', '-1')):
    if kind == 'uv' and args[0] == 'export':
        print(os.environ['CONTROL_EXPORT'], end='')
    sys.exit(int(os.environ.get('CONTROL_EXIT', '47')))
if kind == 'uv':
    if args[0] == 'export':
        print(os.environ['CONTROL_EXPORT'], end='')
    elif args[0] == 'venv':
        python = Path(args[-1]) / 'bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexec "$CONTROL_PYTHON" "$CONTROL_STUB" python "$0" "$@"\n')
        python.chmod(0o755)
    sys.exit(0)
python, *args = args
if args[0] == '-c':
    from importlib import metadata
    role = 'wheel' if '/wheel/' in python.replace('\\','/') else 'tests'
    metadata.version = lambda name: '0.0.0' if os.environ.get('CONTROL_WRONG_DRIVER') == role else args[2]
    sys.argv = ['-c', *args[2:]]
    exec(compile(args[1], '<actual package assertion>', 'exec'))
elif args[0].endswith('required_tests.py'):
    spec = importlib.util.spec_from_file_location('required_tests', os.environ['CONTROL_GUARD'])
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    expected = sorted(guard.REDIS_REQUIRED)
    outcome = os.environ.get('CONTROL_JUNIT', 'valid')
    suite = ET.Element('testsuite')
    for index, node in enumerate(expected):
        if outcome == 'missing' and index == 0:
            continue
        case = ET.SubElement(suite, 'testcase')
        ET.SubElement(ET.SubElement(case, 'properties'), 'property', name=guard.NODE_ID, value=node)
        if index == 0 and outcome in {'skipped', 'failure', 'error'}:
            ET.SubElement(case, outcome)
    if outcome == 'empty':
        suite.clear()
        expected = []
    report = Path(args[2])
    ET.ElementTree(suite).write(report)
    guard.validate('redis', expected, report)
"""


Harness = tuple[
    Path,
    Path,
    Callable[[], tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]],
]


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    """Build task-owned shims that prevent real Docker and network access.

    Returns:
        Package path, runner path, and a callable returning Bash status and trace.
    """
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        assert git is not None
        bash = str(Path(git).parents[1] / "bin/bash.exe")
    assert bash is not None, "Bash is required to validate the CI script"
    package = tmp_path / "repo/packages/cache"
    package.mkdir(parents=True)
    for name in (
        *INPUTS,
        "tests/test_redis_z.py",
        "tests/test_redis_a.py",
        "tests/test_inspection.py",
    ):
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("controlled input")
    runner = tmp_path / "runner"
    runner.mkdir()
    shims = tmp_path / "bin"
    shims.mkdir()
    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    uv = shims / "uv"
    uv.write_text('#!/bin/sh\nexec "$CONTROL_PYTHON" "$CONTROL_STUB" uv "$@"\n')
    uv.chmod(0o755)
    docker = shims / "docker"
    docker.write_text(
        '#!/bin/sh\necho "Unexpected direct Docker access" >&2\nexit 99\n'
    )
    docker.chmod(0o755)
    settings = (
        runner.as_posix(),
        "redis://disposable.invalid:16379/0",
        "8.10.2",
        "semantix-redis-ci-test-1",
    )
    for name, value in zip(SETTINGS, settings, strict=True):
        monkeypatch.setenv(name, value)
    log = tmp_path / "commands.jsonl"
    for name, value in {
        "CONTROL_PYTHON": Path(sys.executable).as_posix(),
        "CONTROL_STUB": stub.as_posix(),
        "CONTROL_LOG": log.as_posix(),
        "CONTROL_EXPORT": EXPORT,
        "CONTROL_GUARD": GUARD.as_posix(),
    }.items():
        monkeypatch.setenv(name, value)
    git_tools = (
        str(Path(bash).parents[1] / "usr/bin") if os.name == "nt" else "/usr/bin"
    )
    monkeypatch.setenv(
        "PATH", os.pathsep.join((str(shims), git_tools, os.environ["PATH"]))
    )

    def run() -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
        result = subprocess.run(  # noqa: S603 -- fixed Bash script and owned command stubs
            [bash, SCRIPT.as_posix()],
            cwd=package,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        records = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, records

    return package, runner, run


def test_complete_procedure_preserves_targets_commands_and_environment(
    harness: Harness,
) -> None:
    package, runner, run = harness
    result, records = run()
    assert result.returncode == 0, result.stderr
    assert len(records) == 24
    for index, driver in enumerate(("7.4.1", "8.0.1")):
        target = (runner / f"redis-driver-{driver}").as_posix()
        python = target + "/tests/bin/python"
        wheel = target + "/wheel/bin/python"
        commands = [r["command"] for r in records[index * 12 : (index + 1) * 12]]
        assert commands[0] == [
            "uv",
            "venv",
            "--python",
            ".venv/bin/python",
            target + "/tests",
        ]
        assert commands[1] == [
            "uv",
            "export",
            "--locked",
            "--extra",
            "dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-annotate",
        ]
        assert commands[2] == [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "-r",
            target + "/requirements.txt",
            "--editable",
            ".[redis]",
        ]
        assert commands[3][0:2] == [python, "-c"]
        assert commands[3][-1] == driver
        assert commands[4] == [
            python,
            "tests/redis_infrastructure_smoke.py",
            "--verify-version",
        ]
        assert commands[5] == [python, "-m", "mypy", "src", "examples"]
        assert commands[6] == [
            python,
            "../../ops/ci/required_tests.py",
            "redis",
            target + "/tests.xml",
            "--",
            "tests/test_redis_a.py",
            "tests/test_redis_z.py",
            "tests/test_inspection.py",
            "-k",
            "redis",
        ]
        assert commands[7] == [python, "tests/redis_infrastructure_smoke.py"]
        assert commands[8] == [
            "uv",
            "venv",
            "--python",
            ".venv/bin/python",
            target + "/wheel",
        ]
        assert commands[9] == [
            "uv",
            "pip",
            "install",
            "--python",
            wheel,
            "dist/semantix_cache-0.1.0-py3-none-any.whl[redis]",
            "redis==" + driver,
        ]
        assert commands[10][0:2] == [wheel, "-c"]
        assert commands[10][-1] == driver
        assert commands[11] == [wheel, "-I", "tests/redis_wheel_smoke.py"]
        assert (Path(target) / "requirements.txt").read_text() == EXPORT.replace(
            "\nredis==8.1.0\n", f"\nredis=={driver}\n"
        )
    assert all(
        r["settings"]
        == {
            "REDIS_TEST_URL": "redis://disposable.invalid:16379/0",
            "REDIS_TEST_VERSION": "8.10.2",
            "REDIS_TEST_CONTAINER": "semantix-redis-ci-test-1",
        }
        for r in records
    )
    assert (package / "pyproject.toml").read_text() == "controlled input"


@pytest.mark.parametrize("stage", range(24))
def test_every_mandatory_command_failure_stops_without_fallback(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_FAIL", str(stage))
    result, records = run()
    assert result.returncode == 47
    assert len(records) == stage + 1


@pytest.mark.parametrize("stage", [2, 7, 11, 19])
def test_child_timeout_remains_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_FAIL", str(stage))
    monkeypatch.setenv("CONTROL_EXIT", "124")
    result, records = run()
    assert result.returncode == 124
    assert len(records) == stage + 1


@pytest.mark.parametrize(
    "exported",
    [
        "",
        "redis==8.0.1\n",
        "redis==8.1.0\nredis==8.1.0\n",
        "redis==8.1.0 ; python_version >= '3.11'\n",
    ],
)
def test_locked_baseline_drift_is_rejected(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, exported: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_EXPORT", exported)
    result, records = run()
    assert result.returncode != 0
    assert "exactly one locked redis==8.1.0" in result.stderr
    assert len(records) == 2


@pytest.mark.parametrize("role", ["tests", "wheel"])
def test_actual_package_assertion_rejects_wrong_installed_version(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_WRONG_DRIVER", role)
    result, records = run()
    assert result.returncode != 0
    assert "AssertionError" in result.stderr
    assert len(records) == (4 if role == "tests" else 11)


@pytest.mark.parametrize("outcome", ["missing", "skipped", "failure", "error", "empty"])
def test_real_required_guard_rejections_stop_the_procedure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_JUNIT", outcome)
    result, records = run()
    assert result.returncode != 0
    assert "ValueError" in result.stderr
    assert len(records) == 7


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize("value", [None, ""])
def test_missing_settings_fail_before_any_command(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, setting: str, value: str | None
) -> None:
    _, _, run = harness
    if value is None:
        monkeypatch.delenv(setting)
    else:
        monkeypatch.setenv(setting, value)
    result, records = run()
    assert result.returncode != 0
    assert setting in result.stderr
    assert records == []


@pytest.mark.parametrize("name", INPUTS)
def test_missing_inputs_fail_before_any_command(harness: Harness, name: str) -> None:
    package, _, run = harness
    (package / name).unlink()
    result, records = run()
    assert result.returncode != 0
    assert name in result.stderr
    assert records == []


@pytest.mark.parametrize("driver", ["7.4.1", "8.0.1"])
def test_existing_environment_and_unowned_files_are_preserved(
    harness: Harness, driver: str
) -> None:
    _, runner, run = harness
    target = runner / f"redis-driver-{driver}"
    target.mkdir()
    sentinel = target / "unowned"
    sentinel.write_text("preserved")
    unrelated = runner / "other-job"
    unrelated.write_text("preserved")
    result, records = run()
    assert result.returncode != 0
    assert len(records) == (0 if driver == "7.4.1" else 12)
    assert sentinel.read_text() == unrelated.read_text() == "preserved"
