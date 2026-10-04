"""Summarize independent trials; never pool quantiles or hide failed evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Any

from .common import write_result


def aggregate(paths: list[Path]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failed = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("kind") not in {"runtime", "numerics", "failures", "postgresql"}:
            if data.get("status") == "running":
                failed.append(str(path))
            continue
        if not data.get("correctness_passed"):
            failed.append(str(path))
        key = json.dumps(
            {
                "kind": data["kind"],
                "case": data["environment"]["case"],
                "blas": data["environment"]["blas_environment"],
                "iterations": data.get("iterations"),
            },
            sort_keys=True,
        )
        groups[key].append(data)
    rows = []
    for key, trials in sorted(groups.items()):
        metadata = json.loads(key)
        if (
            len(
                {
                    json.dumps(
                        t["environment"]["runtime_source_sha256"], sort_keys=True
                    )
                    for t in trials
                }
            )
            != 1
        ):
            raise ValueError("Runtime source changed between comparable trials")
        environment_fields = (
            "cpu",
            "logical_cpus",
            "ram_bytes",
            "os",
            "python",
            "versions",
            "numpy_build",
            "process_topology",
            "gc_enabled",
            "measurement",
        )
        if (
            len(
                {
                    json.dumps(
                        {
                            **{
                                name: t["environment"].get(name)
                                for name in environment_fields
                            },
                            "database": t.get("database"),
                        },
                        sort_keys=True,
                    )
                    for t in trials
                }
            )
            != 1
        ):
            raise ValueError(
                "Measurement environment changed between comparable trials"
            )
        measurement_modules: tuple[str, ...] = ("common.py", metadata["kind"] + ".py")
        if metadata["kind"] == "postgresql":
            measurement_modules += ("runtime.py",)
        if (
            len(
                {
                    tuple(
                        t["environment"]["benchmark_source_sha256"][
                            "packages/cache/benchmarks/" + module
                        ]
                        for module in measurement_modules
                    )
                    for t in trials
                }
            )
            != 1
        ):
            raise ValueError("Measurement code changed between comparable trials")
        if len({t["dataset_sha256"] for t in trials}) != 1:
            raise ValueError("Dataset changed between comparable trials")
        row: dict[str, Any] = {
            **metadata,
            "trials": len(trials),
            "source_revision": trials[0]["environment"]["source_revision"],
            "dataset_sha256": trials[0]["dataset_sha256"],
            "all_correct": all(t["correctness_passed"] for t in trials),
        }
        if metadata["kind"] == "runtime":
            values = [t["operations_per_second"] for t in trials]
            row["median_ops_per_second"] = median(values)
            row["ops_per_second_range"] = [min(values), max(values)]
            row["rps_cv"] = pstdev(values) / fmean(values) if fmean(values) else 0.0
            row["median_trial_latency_ms"] = {
                name: median(t["latency_ms"][name] for t in trials)
                for name in ("p50", "p95", "p99", "max")
            }
            row["hit_ratio"] = [t["hit_ratio"] for t in trials]
            row["embedding_calls"] = [t["embedding_calls"] for t in trials]
            row["generation_calls"] = [t["generation_calls"] for t in trials]
            row["duplicate_generation_count"] = [
                t["duplicate_generation_count"] for t in trials
            ]
            row["error_counts"] = [sum(t["errors"].values()) for t in trials]
        else:
            row["metrics"] = {
                name: {
                    "median_p50_ms": median(
                        t["metrics"][name]["latency_ms"]["p50"] for t in trials
                    ),
                    "median_ops_per_second": median(
                        t["metrics"][name]["operations_per_second"] for t in trials
                    ),
                }
                for name in trials[0]["metrics"]
            }
        rows.append(row)
    return {
        "schema_version": 1,
        "kind": "analysis",
        "rows": rows,
        "failed_or_incomplete": failed,
        "method": "median of trial quantiles/rates, not pooled latency; retained ranges/CV; instrumented trials separate; descriptive tails are not regression budgets",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(sorted(args.results.rglob("*.json")))
    write_result(args.output, result)
    print(  # noqa: T201 -- CLI reporting
        f"Summarized {len(result['rows'])} configurations; failures/incomplete: {len(result['failed_or_incomplete'])}"
    )


if __name__ == "__main__":
    main()
