"""Measure NumPy representation/copy costs without retaining runtime changes.

Candidate matrices have shape (N, D); queries have shape (D,). Float64 is the
current nearest_index compute dtype: float32 inputs are promoted. Tuple conversion,
dtype promotion, candidate norms and dot products are measured separately. Prebuilt
arrays and cached norms belong to fixture setup, outside the measured call. Memory
sharing and allocation peaks are recorded in separate passes from latency.

Unit-dot controls use the pre-normalized synthetic corpus. Experimental kernels
omit production validation, TTL, ordering and concurrency and are NOT drop-in
replacements for a CacheStore. Small float32 score differences can change threshold
eligibility even when the random corpus selects the same candidate.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import tracemalloc
from collections.abc import Callable, Sequence
from numbers import Real
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np

from semantix_cache._semantics import nearest_index, normalized_vector

from .common import Case, Dataset, environment, now_ns, rss_bytes, summary, write_result


def timing(function: Callable[[], Any], iterations: int) -> dict[str, Any]:
    function()
    samples = []
    began = perf_counter()
    for _ in range(iterations):
        started = now_ns()
        function()
        samples.append(now_ns() - started)
    result = summary(samples, perf_counter() - began)
    # Trace in a separate pass so allocation accounting does not taint timings.
    tracemalloc.start()
    function()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["allocation"] = {"retained_bytes": current, "peak_bytes": peak}
    return result


def experiments(case: Case, iterations: int, output: Path) -> dict[str, Any]:
    data = Dataset(case)
    tuples = data.vectors[: case.cache_size]
    matrix = np.asarray(tuples, dtype=np.float64)
    matrix32 = matrix.astype(np.float32)
    query = matrix[0].copy()
    query32 = query.astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1)
    normalized = matrix / norms[:, None]
    normalized32 = matrix32 / np.linalg.norm(matrix32, axis=1)[:, None]
    reference = nearest_index(query, tuples)

    def scalar() -> tuple[int, float]:
        # Same argmax result and one query norm per call as nearest_index; input
        # is the prebuilt float64 matrix, so tuple conversion is measured apart.
        query_norm = float(np.linalg.norm(query))
        best_index, best_score = 0, float("-inf")
        for index, row in enumerate(matrix):
            score = float(np.dot(row, query) / (np.linalg.norm(row) * query_norm))
            if score > best_score:
                best_index, best_score = index, score
        return best_index, max(-1.0, min(1.0, best_score))

    def selected(scores: Any) -> tuple[int, float]:
        index = int(np.argmax(scores))
        return index, max(-1.0, min(1.0, float(scores[index])))

    kernels: dict[str, Callable[[], Any]] = {
        "nearest_tuple_float64_current": lambda: nearest_index(query, tuples),
        "nearest_prebuilt_float64_matrix": lambda: nearest_index(
            query, cast(Sequence[Sequence[float]], matrix)
        ),
        "nearest_float32_input_promoted_to_float64": lambda: nearest_index(
            query32.astype(np.float64), cast(Sequence[Sequence[float]], matrix32)
        ),
        "prebuilt_dot_float64_cached_norms": lambda: selected(
            (matrix @ query) / (norms * np.linalg.norm(query))
        ),
        "prebuilt_unit_dot_float64": lambda: selected(normalized @ query),
        "prebuilt_unit_dot_float32": lambda: selected(normalized32 @ query32),
        "scalar_row_cosine_float64": scalar,
        "tuple_to_ndarray_float64": lambda: np.asarray(tuples, dtype=np.float64),
        "matrix_float32_to_float64": lambda: matrix32.astype(np.float64),
        "candidate_norms_float64": lambda: np.linalg.norm(matrix, axis=1),
        "matrix_dot_float64": lambda: matrix @ query,
        "normalize_tuple_current": lambda: normalized_vector(
            tuples[0], dimensions=case.dimensions
        ),
        "normalize_ndarray_float64_current": lambda: normalized_vector(
            query, dimensions=case.dimensions
        ),
        "normalize_ndarray_float32_current": lambda: normalized_vector(
            query32, dimensions=case.dimensions
        ),
        "component_type_validation": lambda: all(
            isinstance(value, Real) and not isinstance(value, bool)
            for value in tuples[0]
        ),
    }
    scores64 = normalized @ query
    scores32 = normalized32 @ query32
    if reference[0] != int(np.argmax(scores64)) or not np.allclose(
        scores64, scores32, rtol=1e-5, atol=1e-6
    ):
        raise RuntimeError("Experimental corpus agreement failed")
    boundaries = []
    for score in (0.92 - 1e-8, 0.92, 0.92 + 1e-8):
        vector = np.zeros(case.dimensions, dtype=np.float64)
        vector[:2] = (score, np.sqrt(1 - score * score))
        unit = np.zeros_like(vector)
        unit[0] = 1
        measured64 = float(vector @ unit / np.linalg.norm(vector))
        v32, u32 = vector.astype(np.float32), unit.astype(np.float32)
        measured32 = float(v32 @ u32 / np.linalg.norm(v32))
        boundaries.append(
            {
                "target_score": score,
                "float64_score": measured64,
                "float32_score": measured32,
                "eligible64": measured64 >= 0.92,
                "eligible32": measured32 >= 0.92,
            }
        )
    metrics = {name: timing(function, iterations) for name, function in kernels.items()}
    profile = cProfile.Profile()
    profile.enable()
    for _ in range(3):
        nearest_index(query, tuples)
        normalized_vector(tuples[0], dimensions=case.dimensions)
    profile.disable()
    profile.dump_stats(str(output.with_suffix(".prof")))
    return {
        "schema_version": 1,
        "kind": "numerics",
        "environment": environment(case),
        "dataset_sha256": data.digest,
        "iterations": iterations,
        "metrics": metrics,
        "representation": {
            "shape": list(matrix.shape),
            "float64_bytes": matrix.nbytes,
            "float32_bytes": matrix32.nbytes,
            "candidate_storage": "Python tuples of Python floats",
            "query_float64_asarray_shares_memory": bool(
                np.shares_memory(query, np.asarray(query, dtype=np.float64))
            ),
            "query_float32_asarray_float64_shares_memory": bool(
                np.shares_memory(query32, np.asarray(query32, dtype=np.float64))
            ),
            "normalization_output_shares_memory": bool(
                np.shares_memory(
                    query, normalized_vector(query, dimensions=case.dimensions)
                )
            ),
            "matrix_float64_asarray_shares_memory": bool(
                np.shares_memory(matrix, np.asarray(matrix, dtype=np.float64))
            ),
            "norm_reuse": "experiment only; production nearest_index recomputes candidate/query norms",
            "allocations_note": "separate single-call tracemalloc peak; includes NumPy-tracked buffers, may exclude native BLAS buffers",
        },
        "numerical_agreement": {
            "selected_index": reference[0],
            "max_absolute_score_difference_float32": float(
                np.max(np.abs(scores64 - scores32))
            ),
            "threshold_probes": boundaries,
            "scope": "random corpus agreement does not prove threshold/tie equivalence; experiments omit production semantics",
        },
        "rss": rss_bytes(),
        "correctness_passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    case = Case(**json.loads(args.case_json))
    case.validate()
    if case.dimensions < 2 or case.cache_size < 1 or not 1 <= args.iterations <= 10000:
        parser.error(
            "Numerical experiments need >=2 dimensions, >=1 candidate and bounded positive iterations"
        )
    write_result(args.output, {"status": "running"})
    write_result(args.output, experiments(case, args.iterations, args.output))


if __name__ == "__main__":
    main()
