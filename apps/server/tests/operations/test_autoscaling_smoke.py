"""Convergence retries must preserve routing and cleanup failures."""

import importlib
import subprocess
import sys
import traceback
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from uuid import uuid4

import pytest


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    source = Path(__file__).resolve().parents[4] / "ops" / "ci"
    upstream = tmp_path / "upstream.conf"
    upstream.write_text(
        "server 172.28.0.2:8000;\nserver 172.28.0.3:8000;\n",
        encoding="utf-8",
    )
    for variable in (
        "SEMANTIX_E2E_TOKEN",
        "SEMANTIX_E2E_VIEWER_TOKEN",
        "SEMANTIX_E2E_OPERATOR_TOKEN",
        "SEMANTIX_E2E_SCOPED_ADMIN_TOKEN",
    ):
        monkeypatch.setenv(variable, str(uuid4()))
    monkeypatch.setenv("SEMANTIX_UPSTREAM_FILE", str(upstream))
    monkeypatch.setattr(sys, "path", [str(source), *sys.path])
    for name in ("autoscaling_smoke", "two_replica_smoke"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("autoscaling_smoke")
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(module, "request", Mock(return_value={"status": "ready"}))
    return module


def test_delayed_gateway_logs_are_not_discarded(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []
    reads = 0

    def logs(*_args: object, **_kwargs: object) -> list[str]:
        nonlocal reads
        reads += 1
        # The only observation of peer 3 is delayed until the next read.
        # Re-establishing the cursor before every request loses it.
        if reads == 2:
            return []
        if reads == 3:
            observed.extend(["172.28.0.2", "172.28.0.3"])
        elif reads > 3:
            observed.append("172.28.0.2")
        return observed.copy()

    monkeypatch.setattr(smoke, "gateway_upstreams", logs)
    smoke.wait_routing({"172.28.0.2", "172.28.0.3"}, timeout_seconds=2)
    assert reads == 8


@pytest.mark.parametrize(
    "failure", ["missing", "unexpected", "stale", "config", "ready"]
)
def test_failure_classification(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    expected = {"172.28.0.2", "172.28.0.3"}
    observed: list[str] = []
    emitted = "172.28.0.9" if failure in {"unexpected", "stale"} else "172.28.0.2"

    def logs(*_args: object, **_kwargs: object) -> list[str]:
        observed.append(emitted)
        return observed.copy()

    monkeypatch.setattr(smoke, "gateway_upstreams", logs)
    if failure == "config":
        smoke.UPSTREAM_FILE.write_text("server 172.28.0.2:8000;\n", encoding="utf-8")
    if failure == "ready":

        def request(path: str, **_kwargs: object) -> dict[str, object]:
            if path == "/ready":
                raise AssertionError("Backend is not ready")
            return {}

        monkeypatch.setattr(smoke, "request", request)
    excluded: frozenset[str] = (
        frozenset({"172.28.0.9"}) if failure == "stale" else frozenset()
    )
    with pytest.raises(AssertionError) as caught:
        smoke.wait_routing(expected, excluded=excluded, timeout_seconds=1)
    assert isinstance(caught.value, smoke.RoutingConvergenceError) is (
        failure == "missing"
    )
    if failure == "missing":
        assert "missing=['172.28.0.3']" in str(caught.value)


def test_stale_observation_requires_six_fresh_batches(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []
    reads = 0

    def logs(*_args: object, **_kwargs: object) -> list[str]:
        nonlocal reads
        reads += 1
        if reads == 2:
            observed.append("172.28.0.9")
        elif reads > 2:
            observed.extend(["172.28.0.2", "172.28.0.3"])
        return observed.copy()

    monkeypatch.setattr(smoke, "gateway_upstreams", logs)
    smoke.wait_routing(
        {"172.28.0.2", "172.28.0.3"},
        excluded=frozenset({"172.28.0.9"}),
        timeout_seconds=2,
    )
    assert reads == 8


@pytest.mark.parametrize("outcome", ["convergence", "semantic", "cleanup"])
def test_retry_is_bounded_and_failure_specific(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    failure: Exception
    if outcome == "convergence":
        failure = smoke.RoutingConvergenceError("Healthy peer not observed")
    elif outcome == "semantic":
        failure = AssertionError("Threshold did not propagate")
    else:
        failure = ExceptionGroup("Cleanup failed", [AssertionError("Extra replica")])
    attempts = Mock(side_effect=failure)
    monkeypatch.setattr(smoke, "main", attempts)
    with pytest.raises(type(failure)):
        smoke.run_with_retry()
    assert attempts.call_count == (2 if outcome == "convergence" else 1)


def test_verified_transient_attempt_can_succeed(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = Mock(
        side_effect=[smoke.RoutingConvergenceError("Healthy peer not observed"), None]
    )
    monkeypatch.setattr(smoke, "main", attempts)
    smoke.run_with_retry()
    assert attempts.call_count == 2


@pytest.mark.parametrize("delay", range(1, 51))
def test_delayed_log_stress(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, delay: int
) -> None:
    observed: list[str] = []
    reads = 0

    def logs(*_args: object, **_kwargs: object) -> list[str]:
        nonlocal reads
        reads += 1
        if reads > 1:
            observed.append("172.28.0.2")
        if reads == delay + 1:
            observed.append("172.28.0.3")
        return observed.copy()

    monkeypatch.setattr(smoke, "gateway_upstreams", logs)
    smoke.wait_routing({"172.28.0.2", "172.28.0.3"}, timeout_seconds=10)


def test_gateway_log_helper_forwards_deadline(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = importlib.import_module("two_replica_smoke")
    compose = Mock(
        return_value="upstream=172.28.0.2:8000 upstream_status=200 path=/health"
    )
    monkeypatch.setattr(shared, "compose", compose)
    assert shared.gateway_upstreams("/health", timeout_seconds=1.5) == ["172.28.0.2"]
    compose.assert_called_once_with(
        "logs", "--no-color", "frontend", timeout_seconds=1.5
    )


def test_command_timeout_does_not_expose_argv(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = importlib.import_module("two_replica_smoke")
    private = str(uuid4())
    command = ["curl", "--header", f"Authorization: Bearer {private}"]
    monkeypatch.setattr(
        shared.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired(command, 1)),
    )
    with pytest.raises(TimeoutError) as caught:
        shared.run(*command, timeout_seconds=1)
    assert private not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("owned", [True, False])
def test_cleanup_removes_only_verified_added_replicas(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, owned: bool
) -> None:
    monkeypatch.setattr(
        smoke, "containers", Mock(side_effect=[{"original", "added"}, {"original"}])
    )

    def inspect(container: str, template: str) -> str:
        if "project" in template:
            return "owned" if container == "original" or owned else "foreign"
        return "backend-a"

    commands = Mock()
    monkeypatch.setattr(smoke, "inspect", inspect)
    monkeypatch.setattr(smoke, "run", commands)
    if owned:
        smoke.remove_added_replicas({"original"})
        assert [call.args for call in commands.call_args_list] == [
            ("docker", "stop", "--time", "360", "added"),
            ("docker", "rm", "added"),
        ]
    else:
        with pytest.raises(AssertionError):
            smoke.remove_added_replicas({"original"})
        commands.assert_not_called()


def test_gateway_logs_preserve_all_failover_targets(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = importlib.import_module("two_replica_smoke")
    monkeypatch.setattr(
        shared,
        "compose",
        Mock(
            return_value=(
                "upstream=172.28.0.9:8000, 172.28.0.2:8000 "
                "upstream_status=502, 200 path=/health\n"
                "upstream=172.28.0.3:8000 upstream_status=200 path=/ready"
            )
        ),
    )
    assert shared.gateway_upstreams("/health") == ["172.28.0.9", "172.28.0.2"]
