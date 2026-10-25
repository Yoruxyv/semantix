"""Controlled negative evidence; real backport certification remains an integration."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from xml.etree import ElementTree

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "sqlite_backport_certification.py"
spec = importlib.util.spec_from_file_location("sqlite_backport_certification", SCRIPT)
assert spec is not None
assert spec.loader is not None
certification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certification)

MODULES = (
    "tests.test_sqlite",
    "tests.test_sqlite_faults",
    "tests.test_sqlite_processes",
    "tests.test_sqlite_conformance",
    "tests.test_sqlite_inspection",
    "tests.test_sqlite_cleanup",
    "tests.test_sqlite_search_snapshots",
)


def source_archive(
    version: str = "3.44.6", source_id: str = "a" * 64, *, unsafe: bool = False
) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in (
            ("sqlite/VERSION", version),
            ("sqlite/manifest.uuid", source_id),
            ("sqlite/sqlite3.c", "/* controlled source fixture */"),
        ):
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        if unsafe:
            member = tarfile.TarInfo("../../user-owned")
            member.size = 9
            archive.addfile(member, io.BytesIO(b"overwrite"))
    return stream.getvalue()


@pytest.mark.parametrize(
    "condition",
    ["valid", "checksum", "corrupt", "version", "manifest", "unsafe"],
)
def test_source_integrity_and_safe_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    work = tmp_path / "owned"
    work.mkdir()
    sentinel = tmp_path / "user-owned"
    sentinel.write_text("preserved")
    content = (
        b"not a tar archive"
        if condition == "corrupt"
        else source_archive(
            version="3.50.7" if condition == "version" else "3.44.6",
            source_id="b" * 64 if condition == "manifest" else "a" * 64,
            unsafe=condition == "unsafe",
        )
    )
    digest = (
        "0" * 64 if condition == "checksum" else hashlib.sha256(content).hexdigest()
    )

    def download(url: str, *, timeout: int) -> io.BytesIO:
        assert url == f"https://sqlite.org/src/tarball/{'a' * 64}/sqlite.tar.gz"
        assert timeout == 60
        return io.BytesIO(content)

    monkeypatch.setattr(certification, "urlopen", download)
    if condition == "valid":
        tree = certification.source_tree(work, "3.44.6", "a" * 64, digest)
        assert tree.joinpath("VERSION").read_text() == "3.44.6"
        assert tree.joinpath("manifest.uuid").read_text() == "a" * 64
    else:
        error = (
            tarfile.TarError if condition in {"corrupt", "unsafe"} else AssertionError
        )
        with pytest.raises(error):
            certification.source_tree(work, "3.44.6", "a" * 64, digest)
    assert sentinel.read_text() == "preserved"
    if condition == "checksum":
        assert not (work / "source").exists()


@pytest.mark.parametrize(
    ("version", "source_id", "threadsafety", "valid"),
    [
        ("3.44.6", "a" * 64, 3, True),
        ("3.50.7", "a" * 64, 3, False),
        ("3.44.6", "b" * 64, 3, False),
        ("3.44.6", "a" * 64, 0, False),
        ("3.44.6", "a" * 64, 1, False),
    ],
)
def test_actual_runtime_probe_rejects_incompatible_builds(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    source_id: str,
    threadsafety: int,
    valid: bool,
) -> None:
    closed: list[bool] = []
    database = SimpleNamespace(
        execute=lambda sql: SimpleNamespace(
            fetchone=lambda: ("timestamp " + source_id,)
        ),
        close=lambda: closed.append(True),
    )
    sqlite = ModuleType("sqlite3")
    sqlite.__dict__.update(
        sqlite_version=version, threadsafety=threadsafety, connect=lambda path: database
    )
    monkeypatch.setitem(sys.modules, "sqlite3", sqlite)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert args[:2] == ["consumer-python", "-c"]
        assert kwargs == {
            "env": {"LD_LIBRARY_PATH": "/owned"},
            "check": True,
            "timeout": 20,
        }
        exec(args[2], {})  # noqa: S102 -- execute the real fixed probe against a controlled sqlite3 module
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(certification.subprocess, "run", run)
    if valid:
        certification.verify_runtime(
            "consumer-python", {"LD_LIBRARY_PATH": "/owned"}, "3.44.6", "a" * 64
        )
    else:
        with pytest.raises(AssertionError):
            certification.verify_runtime(
                "consumer-python", {"LD_LIBRARY_PATH": "/owned"}, "3.44.6", "a" * 64
            )
    assert closed == [True]


def report(path: Path, *, outcome: str = "", omit: str = "") -> None:
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite")
    for module in MODULES:
        if module != omit:
            case = ElementTree.SubElement(
                suite, "testcase", classname=module, name="test_required"
            )
            if outcome and module == MODULES[0]:
                ElementTree.SubElement(case, outcome)
    ElementTree.ElementTree(root).write(path)


def test_valid_junit_and_nested_conformance_class(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    report(path)
    assert certification.verify_tests(path) == len(MODULES)
    tree = ElementTree.parse(path)  # noqa: S314 -- generated local fixture
    case = tree.findall(".//testcase")[-1]
    case.set("classname", MODULES[-1] + ".TestSQLiteStore")
    tree.write(path)
    assert certification.verify_tests(path) == len(MODULES)


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
def test_unsuccessful_junit_is_rejected(tmp_path: Path, outcome: str) -> None:
    path = tmp_path / "report.xml"
    report(path, outcome=outcome)
    with pytest.raises(AssertionError, match="outcomes missing or unsuccessful"):
        certification.verify_tests(path)


@pytest.mark.parametrize("module", MODULES)
def test_missing_selected_module_is_rejected(tmp_path: Path, module: str) -> None:
    path = tmp_path / "report.xml"
    report(path, omit=module)
    with pytest.raises(AssertionError, match="Required module not exercised"):
        certification.verify_tests(path)


@pytest.mark.parametrize(
    "content",
    [None, "<testsuites>", "<testsuites/>", "<testsuites><testcase/></testsuites>"],
)
def test_missing_malformed_or_empty_evidence_is_rejected(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "report.xml"
    if content is not None:
        path.write_text(content)
    with pytest.raises((OSError, ElementTree.ParseError, AssertionError)):
        certification.verify_tests(path)


@pytest.fixture
def procedure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]]:
    package = tmp_path / "package"
    package.joinpath("tests").mkdir(parents=True)
    package.joinpath(".cache").mkdir()
    package.joinpath("pyproject.toml").touch()
    package.joinpath("tests/check_artifacts.py").write_text(
        "def main(dist):\n"
        "    assert (dist / 'consumer.whl').is_file()\n"
        "    (dist / 'artifact-check-ran').touch()\n"
    )
    monkeypatch.chdir(package)
    monkeypatch.setenv("PYTHONPATH", "must-not-leak-to-runtime")
    roots: list[Path] = []
    commands: list[tuple[list[str], dict[str, Any]]] = []
    temporary_directory = certification.tempfile.TemporaryDirectory

    def temporary(**kwargs: Any) -> Any:
        owner = temporary_directory(dir=tmp_path, **kwargs)
        roots.append(Path(owner.name))
        return owner

    targets = []
    archives = {}
    for version, source_id, _ in certification.TARGETS:
        archive = source_archive(version, source_id)
        archives[source_id] = archive
        targets.append((version, source_id, hashlib.sha256(archive).hexdigest()))

    def download(url: str, **kwargs: Any) -> io.BytesIO:
        return io.BytesIO(archives[url.split("/")[-2]])

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["check"] is True
        commands.append((args, kwargs))
        if args[1:3] == ["-m", "build"]:
            dist = Path(args[-1])
            dist.mkdir()
            (dist / "consumer.whl").touch()
        elif args[0] == "cc":
            Path(args[args.index("-o") + 1]).write_bytes(b"controlled library")
        elif args[1:3] == ["-m", "pytest"]:
            report(Path(args[-1].removeprefix("--junitxml=")))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(certification.tempfile, "TemporaryDirectory", temporary)
    monkeypatch.setattr(certification, "TARGETS", tuple(targets))
    monkeypatch.setattr(certification, "urlopen", download)
    monkeypatch.setattr(certification.subprocess, "run", run)
    return package, roots, commands


def test_complete_procedure_preserves_commands_and_cleanup(
    procedure: tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]],
) -> None:
    package, roots, commands = procedure
    certification.main()
    pytest_calls = [(args, kwargs) for args, kwargs in commands if "pytest" in args]
    assert len(pytest_calls) == 2
    for args, kwargs in pytest_calls:
        assert args[3:-1] == [module.replace(".", "/") + ".py" for module in MODULES]
        assert kwargs["timeout"] == 180
        assert "PYTHONPATH" not in kwargs["env"]
    probes = [(args, kwargs) for args, kwargs in commands if "-c" in args]
    assert len(probes) == 4
    assert all(kwargs["timeout"] == 20 for _, kwargs in probes)
    wheels = [
        (args, kwargs)
        for args, kwargs in commands
        if args[-1] == "tests.sqlite_wheel_smoke"
    ]
    assert len(wheels) == 2
    assert all(kwargs["timeout"] == 60 for _, kwargs in wheels)
    assert len(roots) == 1
    assert not roots[0].exists()
    assert all(
        package.joinpath(f".cache/sqlite-backport-{version}.xml").is_file()
        for version in ("3.44.6", "3.50.7")
    )


@pytest.mark.parametrize(
    "stage", ["build", "install", "compile", "runtime", "tests", "wheel"]
)
@pytest.mark.parametrize("timeout", [False, True])
def test_subprocess_failures_propagate_and_release_only_owned_temporary_files(
    procedure: tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    timeout: bool,
) -> None:
    package, roots, _ = procedure
    sentinel = package / "user-owned.db"
    sentinel.write_text("must remain untouched")
    execute: Callable[..., subprocess.CompletedProcess[bytes]] = (
        certification.subprocess.run
    )

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        matches = {
            "build": args[1:3] == ["-m", "build"],
            "install": args[:3] == ["uv", "pip", "install"],
            "compile": args[0] == "cc",
            "runtime": "-c" in args,
            "tests": "pytest" in args,
            "wheel": args[-1] == "tests.sqlite_wheel_smoke",
        }
        if matches[stage]:
            if timeout:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            raise subprocess.CalledProcessError(19, args)
        return execute(args, **kwargs)

    monkeypatch.setattr(certification.subprocess, "run", run)
    error = subprocess.TimeoutExpired if timeout else subprocess.CalledProcessError
    with pytest.raises(error):
        certification.main()
    assert roots
    assert all(not root.exists() for root in roots)
    assert sentinel.read_text() == "must remain untouched"


def test_direct_cli_rejects_wrong_working_directory_without_external_work(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(  # noqa: S603 -- fixed checked-in script and interpreter
        [sys.executable, "-I", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode != 0
    assert "from packages/cache" in completed.stderr
    assert not list(tmp_path.iterdir())


def test_artifact_helper_failure_is_not_bypassed(
    procedure: tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]],
) -> None:
    package, roots, commands = procedure
    package.joinpath("tests/check_artifacts.py").write_text(
        "def main(dist):\n    raise AssertionError('artifact evidence rejected')\n"
    )
    with pytest.raises(AssertionError, match="artifact evidence rejected"):
        certification.main()
    assert len(commands) == 1
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize(
    "outcome",
    ["missing", "malformed", "empty", "module", "skipped", "failure", "error"],
)
def test_bad_junit_stops_procedure_before_wheel_and_cleans_temporary_files(
    procedure: tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    _, roots, commands = procedure
    execute: Callable[..., subprocess.CompletedProcess[bytes]] = (
        certification.subprocess.run
    )

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        result = execute(args, **kwargs)
        if "pytest" in args:
            path = Path(args[-1].removeprefix("--junitxml="))
            if outcome == "missing":
                path.unlink()
            elif outcome == "malformed":
                path.write_text("<testsuites>")
            elif outcome == "empty":
                path.write_text("<testsuites/>")
            elif outcome == "module":
                report(path, omit=MODULES[-1])
            else:
                report(path, outcome=outcome)
        return result

    monkeypatch.setattr(certification.subprocess, "run", run)
    with pytest.raises((OSError, ElementTree.ParseError, AssertionError)):
        certification.main()
    assert not any(args[-1] == "tests.sqlite_wheel_smoke" for args, _ in commands)
    assert roots
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize("error", [OSError, TimeoutError])
def test_download_failure_propagates_and_cleans_temporary_files(
    procedure: tuple[Path, list[Path], list[tuple[list[str], dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
    error: type[OSError],
) -> None:
    _, roots, commands = procedure

    def download(url: str, **kwargs: Any) -> io.BytesIO:
        raise error("controlled download failure")

    monkeypatch.setattr(certification, "urlopen", download)
    with pytest.raises(error, match="controlled download failure"):
        certification.main()
    assert not any(args[0] == "cc" for args, _ in commands)
    assert roots
    assert all(not root.exists() for root in roots)
