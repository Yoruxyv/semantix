"""Disposable JUnit and pytest controls for required CI evidence."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "ops/ci/required_tests.py"
spec = importlib.util.spec_from_file_location("required_tests", RUNNER)
assert spec is not None
assert spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
REQUIRED = "tests/test_shared_integration.py::test_required"


def junit(path: Path, cases: list[tuple[str, str, str]]) -> Path:
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite")
    for node_id, outcome, reason in cases:
        case = ElementTree.SubElement(suite, "testcase")
        properties = ElementTree.SubElement(case, "properties")
        ElementTree.SubElement(
            properties, "property", name="semantix_ci_nodeid", value=node_id
        )
        if outcome:
            ElementTree.SubElement(case, outcome, message=reason)
    ElementTree.ElementTree(root).write(path, encoding="utf-8")
    return path


@pytest.mark.parametrize("scope", ["embedded", "postgresql", "redis"])
def test_required_shared_case_passes(tmp_path: Path, scope: str) -> None:
    report = junit(tmp_path / "report.xml", [(REQUIRED, "", "")])
    guard.validate(scope, [REQUIRED], report)


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
@pytest.mark.parametrize("scope", ["embedded", "postgresql", "redis"])
def test_required_outcomes_rejected(tmp_path: Path, outcome: str, scope: str) -> None:
    report = junit(tmp_path / "report.xml", [(REQUIRED, outcome, "unavailable")])
    with pytest.raises(ValueError, match="Required test"):
        guard.validate(scope, [REQUIRED], report)


@pytest.mark.parametrize("expected", [[], [REQUIRED, REQUIRED]])
def test_empty_or_duplicate_collection_rejected(
    tmp_path: Path, expected: list[str]
) -> None:
    report = junit(tmp_path / "report.xml", [(REQUIRED, "", "")])
    with pytest.raises(ValueError, match="Empty or duplicate"):
        guard.validate("embedded", expected, report)


def test_required_case_missing_from_junit(tmp_path: Path) -> None:
    report = junit(tmp_path / "report.xml", [(REQUIRED, "", "")])
    with pytest.raises(ValueError, match="missing from JUnit"):
        guard.validate(
            "embedded", [REQUIRED, "tests/test_other.py::test_other"], report
        )


def test_empty_report_rejected(tmp_path: Path) -> None:
    report = junit(tmp_path / "report.xml", [])
    with pytest.raises(ValueError, match="missing from JUnit"):
        guard.validate("embedded", [REQUIRED], report)


@pytest.mark.parametrize("unexpected", [REQUIRED, "tests/test_other.py::test_other"])
def test_duplicate_or_uncollected_report_case_rejected(
    tmp_path: Path, unexpected: str
) -> None:
    report = junit(tmp_path / "report.xml", [(REQUIRED, "", ""), (unexpected, "", "")])
    with pytest.raises(ValueError, match="Duplicate or unexpected"):
        guard.validate("embedded", [REQUIRED], report)


def test_missing_case_identity_rejected(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text("<testsuite><testcase/></testsuite>", encoding="utf-8")
    with pytest.raises(ValueError, match="unique collected node ID"):
        guard.validate("embedded", [REQUIRED], report)


@pytest.mark.parametrize(("node_id", "reason"), list(guard.OPTIONAL_SKIPS.items()))
def test_documented_optional_skip_passes(
    tmp_path: Path, node_id: str, reason: str
) -> None:
    report = junit(
        tmp_path / "report.xml", [(REQUIRED, "", ""), (node_id, "skipped", reason)]
    )
    guard.validate("embedded", [REQUIRED, node_id], report)


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
def test_optional_identity_does_not_excuse_other_outcomes(
    tmp_path: Path, outcome: str
) -> None:
    node_id = "tests/test_store_conformance.py::TestBuiltInStores::test_optional_hit_metadata[memory]"
    report = junit(tmp_path / "report.xml", [(node_id, outcome, "database missing")])
    with pytest.raises(ValueError, match="Required test"):
        guard.validate("embedded", [node_id], report)


def test_sdk_case_ownership_matches_existing_suite() -> None:
    source = ROOT / "packages/client/tests/test_integration.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    expected = {
        f"tests/test_integration.py::{node.name}"
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    assert len(expected) == 4
    assert expected == guard.SDK_REQUIRED


@pytest.mark.parametrize("outcome", ["", "skipped", "failure", "error"])
def test_sdk_expected_cases_and_outcomes(tmp_path: Path, outcome: str) -> None:
    expected = sorted(guard.SDK_REQUIRED)
    cases = [(node_id, "", "") for node_id in expected]
    cases[0] = (expected[0], outcome, "integration not configured")
    report = junit(tmp_path / "report.xml", cases)
    if outcome:
        with pytest.raises(ValueError, match="Required test"):
            guard.validate("sdk", expected, report)
    else:
        guard.validate("sdk", expected, report)
    with pytest.raises(ValueError, match="not collected"):
        guard.validate("sdk", expected[1:], report)


def run_pytest(
    tmp_path: Path, scope: str, *, configured: bool = True
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("SEMANTIX_INTEGRATION_URL", None)
    env.pop("SEMANTIX_INTEGRATION_TOKEN", None)
    if configured:
        env["SEMANTIX_INTEGRATION_URL"] = "http://127.0.0.1:1"
        env["SEMANTIX_INTEGRATION_TOKEN"] = tmp_path.name
    return subprocess.run(  # noqa: S603 -- fixed runner, disposable pytest files, no service calls
        [sys.executable, str(RUNNER), scope, "report.xml", "--", "-q", "--rootdir=."],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("configured", [True, False])
def test_sdk_runner_rejects_missing_configuration(
    tmp_path: Path, configured: bool
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    names = [
        "test_sync_client_crosses_real_http_query_boundary",
        "test_async_client_crosses_real_http_query_boundary",
        "test_real_http_rate_limit_without_retry_after",
        "test_real_http_error_headers_and_server_failure",
    ]
    source = "import os\nimport pytest\n"
    for name in names:
        source += f"\ndef {name}():\n"
        if name != names[-1]:
            source += (
                "    if not os.getenv('SEMANTIX_INTEGRATION_URL') or not os.getenv('SEMANTIX_INTEGRATION_TOKEN'):\n"
                "        pytest.skip('live Semantix integration environment is not configured')\n"
            )
        source += "    assert True\n"
    (tests / "test_integration.py").write_text(source, encoding="utf-8")
    result = run_pytest(tmp_path, "sdk", configured=configured)
    assert result.returncode == (0 if configured else 1), result.stdout + result.stderr
    assert ("Verified JUnit" if configured else "Required test skipped") in (
        result.stdout + result.stderr
    )


def test_sdk_runner_rejects_uncollected_expected_cases(tmp_path: Path) -> None:
    (tmp_path / "test_other.py").write_text(
        "def test_other(): pass\n", encoding="utf-8"
    )
    result = run_pytest(tmp_path, "sdk")
    assert result.returncode == 1
    assert "SDK integration cases not collected" in result.stderr


@pytest.mark.parametrize("scope", ["embedded", "postgresql", "redis"])
def test_runner_rejects_missing_owned_paths(tmp_path: Path, scope: str) -> None:
    (tmp_path / "test_other.py").write_text(
        "def test_other(): pass\n", encoding="utf-8"
    )
    result = run_pytest(tmp_path, scope)
    assert result.returncode == 1
    assert f"{scope.title()} integration cases not collected" in result.stderr


def test_runner_rejects_collection_skip(tmp_path: Path) -> None:
    (tmp_path / "test_other.py").write_text(
        "def test_other(): pass\n", encoding="utf-8"
    )
    (tmp_path / "test_skipped.py").write_text(
        "import pytest\npytest.skip('unavailable', allow_module_level=True)\n",
        encoding="utf-8",
    )
    result = run_pytest(tmp_path, "embedded")
    assert result.returncode == 1
    assert "Test collection skipped" in result.stderr


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("def test_failed(): assert False\n", 1),
        ("raise RuntimeError('collection failed')\n", 2),
        ("", 5),
    ],
)
def test_runner_preserves_pytest_failures(
    tmp_path: Path, source: str, expected_code: int
) -> None:
    (tmp_path / "test_failed.py").write_text(source, encoding="utf-8")
    result = run_pytest(tmp_path, "embedded")
    assert result.returncode == expected_code


@pytest.mark.parametrize(
    ("event", "result", "accepted"),
    [
        ("pull_request", "success", True),
        ("pull_request", "skipped", False),
        ("pull_request", "failure", False),
        ("pull_request", "cancelled", False),
        ("pull_request", "", False),
        ("push", "skipped", True),
        ("push", "success", True),
        ("workflow_dispatch", "skipped", True),
        ("workflow_dispatch", "success", True),
        ("push", "failure", False),
        ("workflow_dispatch", "cancelled", False),
        ("unknown", "skipped", False),
    ],
)
def test_actual_dependency_review_gate(event: str, result: str, accepted: bool) -> None:
    section = (
        (ROOT / ".github/workflows/quality.yml")
        .read_text(encoding="utf-8")
        .split("  quality-gate:\n", 1)[1]
    )
    script = dedent(section.split("        run: |\n", 1)[1])
    env = os.environ.copy()
    env.update(dict.fromkeys(re.findall(r"\$(\w+_RESULT)", script), "success"))
    env["GITHUB_EVENT_NAME"] = event
    env["DEPENDENCY_REVIEW_RESULT"] = result
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required to verify the actual CI gate"
    completed = subprocess.run(  # noqa: S603 -- actual checked-in gate uses only test/case builtins
        [bash, "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (completed.returncode == 0) is accepted, completed.stderr


@pytest.mark.parametrize(("node_id", "reason"), list(guard.OPTIONAL_SKIPS.items()))
@pytest.mark.parametrize("scope", ["postgresql", "redis"])
def test_non_embedded_scopes_reject_optional_skips(
    tmp_path: Path, node_id: str, reason: str, scope: str
) -> None:
    report = junit(tmp_path / "report.xml", [(node_id, "skipped", reason)])
    with pytest.raises(ValueError, match="Required test skipped"):
        guard.validate(scope, [node_id], report)
