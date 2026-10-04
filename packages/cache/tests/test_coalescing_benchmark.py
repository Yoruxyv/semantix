"""Check experiment controls and diagnostic receipts without altering the baseline."""

from pathlib import Path

import pytest

from benchmarks.coalescing import experiment
from benchmarks.common import Case


@pytest.mark.parametrize(
    ("mode", "calls", "joins"), [("control", 16, 0), ("treatment", 2, 14)]
)
async def test_coalescing_experiment_reports_real_work_and_drained_state(
    mode: str, calls: int, joins: int
) -> None:
    case = Case(
        workload="burst",
        dimensions=128,
        cache_size=4,
        concurrency=8,
        requests=16,
        generation_delay=0.01,
        diagnostics=True,
    )
    result = await experiment(case, Path(".cache/coalescing-test.json"), mode=mode)
    assert result["correctness_passed"]
    assert result["generation_calls"] == calls
    assert result["embedding_calls"] == 16
    assert result["cache_writes"] == calls
    diagnostics = result["coalescing_experiment"]["diagnostics"]
    assert diagnostics["counts"].get("follower", 0) == joins
    assert diagnostics["counts"].get("fallback", 0) == 0
    assert diagnostics["counts"]["put"] == calls
    assert diagnostics["counts"].get("record_hit", 0) == joins
    assert diagnostics["final"] == (0, 0, 0, 0)


async def test_experiment_rejects_unknown_or_unrecorded_legacy_mode() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        await experiment(Case(), Path(".cache/unwritten.json"), mode="unknown")
    with pytest.raises(ValueError, match="archive"):
        await experiment(Case(), Path(".cache/unwritten.json"), mode="legacy")
