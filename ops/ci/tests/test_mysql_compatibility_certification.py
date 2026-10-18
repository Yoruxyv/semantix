"""Control the real MySQL Bash procedure without creating database resources."""

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

SCRIPT = Path(__file__).resolve().parents[1] / "mysql_compatibility_certification.sh"
EXPORT = (
    "numpy==2.4.6\npymysql==1.2.3\n# pymysql==1.2.3\ntypes-pymysql==1.2.0.20260923\n"
)
INPUTS = (
    ".venv/bin/python",
    "pyproject.toml",
    ".cache/mysql-coverage/.coverage.mysql",
    "dist/semantix_cache-0.1.0-py3-none-any.whl",
    "../../ops/ci/mysql_fixture.py",
    "tests/mysql_wheel_smoke.py",
)
STUB = r"""
import json, os, subprocess, sys
from pathlib import Path
from xml.etree import ElementTree as ET
kind, *args = sys.argv[1:]
command = ['uv', *args] if kind == 'uv' else args
log = Path(os.environ['CONTROL_LOG'])
records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
def record(value):
    with log.open('a') as out:
        out.write(json.dumps(value) + '\n')
record({'command': command, 'cwd':Path.cwd().as_posix(), 'fixture':os.environ.get('MYSQL_TEST_CONFIG') == 'controlled-fixture', 'coverage':os.environ.get('COVERAGE_FILE')})
if sum('command' in r for r in records) == int(os.environ.get('CONTROL_FAIL','-1')):
    if kind == 'uv' and args[0] == 'export':
        print(os.environ['CONTROL_EXPORT'], end='')
    sys.exit(int(os.environ.get('CONTROL_EXIT','47')))
if kind == 'uv':
    if args[0] == 'export':
        print(os.environ['CONTROL_EXPORT'], end='')
    elif args[0] == 'venv':
        python = Path(args[-1]) / 'bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexec "$CONTROL_PYTHON" "$CONTROL_STUB" python "$0" "$@"\n')
        python.chmod(0o755)
    elif args[0] == 'run':
        assert args[:4] == ['run','--no-sync','python','../../ops/ci/mysql_fixture.py']
        assert args[4] == '--server-version'
        if args[-1] != '--pull-image':
            child = args[args.index('--')+1:]
            record({'event':'fixture-enter','server':args[5]})
            try:
                result = subprocess.run([os.environ['CONTROL_BASH'], *child[1:]], env=os.environ | {'MYSQL_TEST_CONFIG':'controlled-fixture','MYSQL_TEST_PASSWORD':'controlled-private-value'}, check=False, timeout=30)
            finally:
                record({'event':'fixture-cleanup','server':args[5]})
            sys.exit(64 if os.environ.get('CONTROL_CLEANUP_FAIL') else result.returncode)
    sys.exit(0)
python, *args = args
if args[0] == '-c':
    if 'importlib.metadata' in args[1]:
        from importlib import metadata
        role = 'wheel' if '/wheel/' in python.replace('\\','/') else 'source'
        metadata.version = lambda name: '0.0.0' if os.environ.get('CONTROL_WRONG_DRIVER') == role else args[2]
    sys.argv = ['-c', *args[2:]]
    exec(compile(args[1], '<actual certification assertion>', 'exec'))
elif args[:2] == ['-m','pytest']:
    outcome = os.environ.get('CONTROL_JUNIT','valid')
    report = Path(next(a.split('=',1)[1] for a in args if a.startswith('--junitxml=')))
    if outcome != 'missing':
        if outcome == 'malformed':
            report.write_text('<broken')
        else:
            suite = ET.Element('testsuite')
            for index in range(212 if outcome == 'insufficient' else 0 if outcome == 'empty' else 214 if outcome == 'extra' else 213):
                case = ET.SubElement(suite,'testcase',name=str(index))
                if index == 0 and outcome in {'skipped','failure','error'}:
                    ET.SubElement(case,outcome)
            ET.ElementTree(suite).write(report)
else:
    assert args[0] == '-I' and args[1].endswith('/tests/mysql_wheel_smoke.py')
    change = os.environ.get('CONTROL_COVERAGE_CHANGE')
    if change:
        path = Path(os.environ['CONTROL_COVERAGE'] if change.startswith('baseline') else os.environ['RUNNER_TEMP'] + '/mysql-baseline.coverage')
        if change.endswith('missing'):
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(b'modified')
"""

Harness = tuple[
    Path,
    Path,
    Callable[
        [str | None], tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]
    ],
]


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    """Build private command shims; real fixtures, Docker and SQL never execute.

    Returns:
        Package directory, runner directory and callable returning status and trace.
    """
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        assert git is not None
        bash = str(Path(git).parents[1] / "bin/bash.exe")
    assert bash is not None
    package = tmp_path / "repo/packages/cache"
    package.mkdir(parents=True)
    for name in (*INPUTS, "tests/test_mysql_a.py", "tests/test_mysql_z.py"):
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("controlled input")
    coverage = package / INPUTS[2]
    coverage.write_bytes(b"original coverage\x00\xff")
    runner = tmp_path / "runner"
    runner.mkdir()
    shims = tmp_path / "bin"
    shims.mkdir()
    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    wrapper = '#!/bin/sh\nexec "$CONTROL_PYTHON" "$CONTROL_STUB" '
    uv = shims / "uv"
    uv.write_text(wrapper + 'uv "$@"\n')
    uv.chmod(0o755)
    python = package / ".venv/bin/python"
    python.write_text(wrapper + 'python "$0" "$@"\n')
    python.chmod(0o755)
    docker = shims / "docker"
    docker.write_text(
        '#!/bin/sh\necho "Unexpected direct Docker access" >&2\nexit 99\n'
    )
    docker.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    for name, value in {
        "RUNNER_TEMP": runner.as_posix(),
        "GITHUB_WORKSPACE": package.parents[1].as_posix(),
        "COVERAGE_FILE": INPUTS[2],
        "CONTROL_COVERAGE": coverage.as_posix(),
        "CONTROL_PYTHON": Path(sys.executable).as_posix(),
        "CONTROL_STUB": stub.as_posix(),
        "CONTROL_BASH": Path(bash).as_posix(),
        "CONTROL_EXPORT": EXPORT,
        "CONTROL_LOG": log.as_posix(),
    }.items():
        monkeypatch.setenv(name, value)
    tools = str(Path(bash).parents[1] / "usr/bin") if os.name == "nt" else "/usr/bin"
    monkeypatch.setenv("PATH", os.pathsep.join((str(shims), tools, os.environ["PATH"])))

    def run(
        boundary: str | None = "3.11",
    ) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
        result = subprocess.run(  # noqa: S603 -- fixed Bash procedure and task-owned command stubs
            [bash, SCRIPT.as_posix(), *([boundary] if boundary is not None else [])],
            cwd=package,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        records = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, records

    return package, runner, run


@pytest.mark.parametrize(
    ("boundary", "pairs"),
    [
        ("3.11", [("8.4.12", "1.2.1")]),
        ("3.14", [("8.4.11", "1.2.3"), ("8.4.12", "1.2.2")]),
    ],
)
def test_exact_mapping_fixture_delegation_and_coverage(
    harness: Harness, boundary: str, pairs: list[tuple[str, str]]
) -> None:
    package, runner, run = harness
    result, records = run(boundary)
    assert result.returncode == 0, result.stderr
    commands = [r for r in records if "command" in r]
    fixtures = [r["command"] for r in commands if r["command"][:2] == ["uv", "run"]]
    assert [(c[6], c[-1] == "--pull-image") for c in fixtures] == [
        (server, pull) for server, _ in pairs for pull in (True, False)
    ]
    assert [r["server"] for r in records if r.get("event") == "fixture-cleanup"] == [
        server for server, _ in pairs
    ]
    assert len(commands) == (12 if boundary == "3.11" else 21)
    assert all(r["coverage"] == INPUTS[2] for r in commands)
    for server, driver in pairs:
        target = runner / f"mysql-{server}-{driver}"
        assert (target / "tests.xml").is_file()
        wheel = (target / "wheel/bin/python").as_posix()
        assert [
            "uv",
            "venv",
            "--python",
            ".venv/bin/python",
            (target / "wheel").as_posix(),
        ] in [r["command"] for r in commands]
        assert [
            "uv",
            "pip",
            "install",
            "--python",
            wheel,
            "dist/semantix_cache-0.1.0-py3-none-any.whl[mysql]",
            "PyMySQL==" + driver,
        ] in [r["command"] for r in commands]
        if driver == "1.2.3":
            assert not (target / "tests").exists()
        else:
            assert [
                "uv",
                "export",
                "--locked",
                "--extra",
                "dev",
                "--no-emit-project",
                "--no-hashes",
                "--no-annotate",
            ] in [r["command"] for r in commands]
            assert [
                "uv",
                "pip",
                "install",
                "--python",
                (target / "tests/bin/python").as_posix(),
                "-r",
                (target / "requirements.txt").as_posix(),
                "--editable",
                ".[mysql]",
            ] in [r["command"] for r in commands]
            assert (target / "requirements.txt").read_text() == EXPORT.replace(
                "\npymysql==1.2.3\n", f"\npymysql=={driver}\n"
            )
        start = next(
            i
            for i, r in enumerate(records)
            if r.get("event") == "fixture-enter" and r["server"] == server
        )
        end = next(
            i
            for i, r in enumerate(records[start + 1 :], start + 1)
            if r.get("event") == "fixture-cleanup"
        )
        child = [r for r in records[start + 1 : end] if "command" in r]
        python = (
            package / ".venv/bin/python"
            if driver == "1.2.3"
            else target / "tests/bin/python"
        ).as_posix()
        wheel = (target / "wheel/bin/python").as_posix()
        assert child[0]["command"][0:2] == [python, "-c"]
        assert child[0]["command"][-1] == driver
        assert child[1]["command"] == [
            python,
            "-m",
            "pytest",
            "tests/test_mysql_a.py",
            "tests/test_mysql_z.py",
            "--no-cov",
            "--junitxml=" + (target / "tests.xml").as_posix(),
        ]
        assert child[2]["command"][-1] == (target / "tests.xml").as_posix()
        assert child[3]["command"][0:2] == [wheel, "-c"]
        assert child[3]["command"][-1] == driver
        assert child[4]["command"] == [
            wheel,
            "-I",
            (package / "tests/mysql_wheel_smoke.py").as_posix(),
        ]
        assert child[4]["cwd"] == runner.as_posix()
        assert all(r["fixture"] for r in child)
        assert all(r["cwd"] == package.as_posix() for r in child[:4])
    assert (
        (package / INPUTS[2]).read_bytes()
        == (runner / "mysql-baseline.coverage").read_bytes()
        == b"original coverage\x00\xff"
    )


@pytest.mark.parametrize(
    ("boundary", "stage"),
    [("3.11", i) for i in range(12)] + [("3.14", i) for i in range(21)],
)
def test_every_command_failure_propagates_and_fixture_cleans(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, boundary: str, stage: int
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_FAIL", str(stage))
    result, records = run(boundary)
    assert result.returncode == 47
    assert sum("command" in r for r in records) == stage + 1
    assert [r["server"] for r in records if r.get("event") == "fixture-enter"] == [
        r["server"] for r in records if r.get("event") == "fixture-cleanup"
    ]


def test_more_than_the_minimum_junit_cases_are_valid(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_JUNIT", "extra")
    result, _ = run("3.11")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "outcome",
    ["missing", "insufficient", "empty", "skipped", "failure", "error", "malformed"],
)
def test_actual_junit_assertion_rejects_bad_evidence(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_JUNIT", outcome)
    result, records = run("3.11")
    assert result.returncode != 0
    assert sum("command" in r for r in records) == 10
    assert records[-1]["event"] == "fixture-cleanup"


@pytest.mark.parametrize(
    "exported",
    [
        "",
        "pymysql==1.2.2\n",
        "pymysql==1.2.3\npymysql==1.2.3\n",
        "pymysql==1.2.3 ; python_version >= '3.11'\n",
    ],
)
def test_missing_duplicate_or_drifted_locked_pin(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, exported: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_EXPORT", exported)
    result, records = run("3.11")
    assert result.returncode != 0
    assert "exactly one locked pymysql==1.2.3" in result.stderr
    assert len(records) == 2


@pytest.mark.parametrize("role", ["source", "wheel"])
def test_actual_package_assertions_reject_wrong_driver(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_WRONG_DRIVER", role)
    result, records = run("3.11")
    assert result.returncode != 0
    assert "AssertionError" in result.stderr
    assert records[-1]["event"] == "fixture-cleanup"


@pytest.mark.parametrize(
    "change",
    ["baseline-modified", "baseline-missing", "snapshot-modified", "snapshot-missing"],
)
def test_coverage_mutation_or_loss_is_blocking(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _, _, run = harness
    monkeypatch.setenv("CONTROL_COVERAGE_CHANGE", change)
    result, _ = run("3.11")
    assert result.returncode != 0


@pytest.mark.parametrize("boundary", [None, "3.12", "3.13", "3.15", ""])
def test_unapproved_boundary_fails_before_commands(
    harness: Harness, boundary: str | None
) -> None:
    _, _, run = harness
    result, records = run(boundary)
    assert result.returncode != 0
    assert records == []


@pytest.mark.parametrize("setting", ["RUNNER_TEMP", "GITHUB_WORKSPACE"])
@pytest.mark.parametrize("value", [None, ""])
def test_missing_environment_fails_before_commands(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, setting: str, value: str | None
) -> None:
    _, _, run = harness
    if value is None:
        monkeypatch.delenv(setting)
    else:
        monkeypatch.setenv(setting, value)
    result, records = run("3.11")
    assert result.returncode != 0
    assert setting in result.stderr
    assert records == []


@pytest.mark.parametrize("name", INPUTS)
def test_missing_input_fails_before_commands(harness: Harness, name: str) -> None:
    package, _, run = harness
    (package / name).unlink()
    result, records = run("3.11")
    assert result.returncode != 0
    assert records == []


@pytest.mark.parametrize("name", ["mysql-baseline.coverage", "mysql-8.4.12-1.2.1"])
def test_unowned_snapshot_or_candidate_is_preserved(
    harness: Harness, name: str
) -> None:
    package, runner, run = harness
    path = runner / name
    if name.endswith(".coverage"):
        path.write_bytes(b"unowned")
        sentinel = path
    else:
        path.mkdir()
        sentinel = path / "unowned"
        sentinel.write_bytes(b"unowned")
    result, records = run("3.11")
    assert result.returncode != 0
    assert records == []
    assert sentinel.read_bytes() == b"unowned"
    assert (package / INPUTS[2]).read_bytes() == b"original coverage\x00\xff"


@pytest.mark.parametrize("condition", ["cleanup", "timeout"])
def test_fixture_cleanup_failure_and_timeout_are_not_hidden(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    _, _, run = harness
    if condition == "cleanup":
        monkeypatch.setenv("CONTROL_CLEANUP_FAIL", "1")
    else:
        monkeypatch.setenv("CONTROL_FAIL", "8")
        monkeypatch.setenv("CONTROL_EXIT", "124")
    result, records = run("3.11")
    assert result.returncode == (64 if condition == "cleanup" else 124)
    assert records[-1]["event"] == "fixture-cleanup"
