"""Keep workload classification and measurement evidence trustworthy."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from benchmarks.analyze import aggregate
from benchmarks.common import Case, Dataset, summary, write_result
from benchmarks.run_matrix import expand
from benchmarks.runtime import trial


def test_deterministic_fixture_and_quantiles() -> None:
    case = Case(dimensions=32, cache_size=4, requests=16)
    a, b = Dataset(case), Dataset(case)
    assert a.digest == b.digest
    assert a.vectors == b.vectors
    assert a.vectors[0] != a.vectors[1]
    result = summary([1_000_000, 2_000_000, 3_000_000, 4_000_000], 2)
    assert result["operations_per_second"] == 2
    assert result["latency_ms"]["p50"] == pytest.approx(2.5)
    assert result["latency_ms"]["p99"] == pytest.approx(3.97)
    assert result["tail_warning"] is not None
    cases = expand(
        {"axes": {"workload": ["hits", "burst"], "concurrency": [1, 8]}},
        {"requests": 16},
    )
    assert len(cases) == 4
    assert cases[-1]["generation_delay"] == pytest.approx(0.02)


@pytest.mark.parametrize(
    "workload",
    [
        "hits",
        "get",
        "search",
        "write",
        "empty",
        "mixed90",
        "mixed50",
        "normal90",
        "cold",
        "burst",
        "read-only",
        "refresh",
        "bypass",
        "private",
        "cancellation",
        "search-cancellation",
        "stability",
    ],
)
async def test_small_runtime_evidence(workload: str, tmp_path: Path) -> None:
    case = Case(
        workload=workload,
        dimensions=32,
        cache_size=8,
        capacity=64,
        requests=20,
        concurrency=4,
        generation_delay=0.01 if workload == "burst" else 0,
        duration=0.1,
    )
    result = await trial(case, tmp_path / "unused.json")
    assert result["correctness_passed"]
    assert result["cleanup_before_close"]["engine_active"] == 0
    assert result["cleanup_before_close"]["store_active"] == 0
    assert result["cleanup_before_close"]["numerical_workers"] == 0
    assert result["cleanup_before_close"]["pending_other_tasks"] == 0
    assert result["errors"] == {}
    if workload in {"mixed90", "mixed50"}:
        expected = 18 if workload == "mixed90" else 10
        assert result["cache_hits"] == expected
        assert result["generation_calls"] == 20 - expected
        assert result["cache_writes"] == 0
    elif workload == "cold":
        assert result["cache_writes"] == result["generation_calls"] == 20
    elif workload == "burst":
        assert 5 <= result["generation_calls"] <= 20
        assert result["duplicate_generation_count"] == result["generation_calls"] - 5
    elif workload in {"bypass", "private"}:
        assert result["embedding_calls"] == result["cache_writes"] == 0
    elif workload == "cancellation":
        assert result["cancellation"]["cancelled"] == 4
        assert result["cancellation"]["partial_writes"] == 0


def test_raw_results_cannot_be_written_to_source() -> None:
    with pytest.raises(ValueError, match="Git-ignored"):
        write_result(Path(__file__).with_name("forbidden_benchmark_result.json"), {})


def test_analysis_preserves_iterations_and_measurement_provenance(
    tmp_path: Path,
) -> None:
    first: dict[str, Any] = {
        "kind": "numerics",
        "iterations": 20,
        "environment": {
            "case": {},
            "source_revision": "a" * 40,
            "runtime_source_sha256": {"engine.py": "b" * 64},
            "benchmark_source_sha256": {
                "packages/cache/benchmarks/common.py": "c" * 64,
                "packages/cache/benchmarks/numerics.py": "d" * 64,
                "packages/cache/benchmarks/analyze.py": "e" * 64,
            },
            "blas_environment": {"OPENBLAS_NUM_THREADS": "1"},
        },
        "dataset_sha256": "f" * 64,
        "correctness_passed": True,
        "metrics": {
            "kernel": {"latency_ms": {"p50": 1.0}, "operations_per_second": 1000}
        },
    }
    second = deepcopy(first)
    second["iterations"] = 30
    paths = [tmp_path / "first.json", tmp_path / "second.json"]
    for path, data in zip(paths, (first, second), strict=True):
        path.write_text(json.dumps(data), encoding="utf-8")
    assert len(aggregate(paths)["rows"]) == 2

    second = deepcopy(first)
    # Analysis-only edits do not change the measurement that produced a trial.
    second["environment"]["benchmark_source_sha256"][
        "packages/cache/benchmarks/analyze.py"
    ] = "0" * 64
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    assert aggregate(paths)["rows"][0]["trials"] == 2
    second["environment"]["benchmark_source_sha256"][
        "packages/cache/benchmarks/numerics.py"
    ] = "1" * 64
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError, match="Measurement code changed"):
        aggregate(paths)

    second = deepcopy(first)
    second["environment"]["python"] = "different interpreter"
    paths[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError, match="Measurement environment changed"):
        aggregate(paths)
