"""One fresh-process coalescing-metrics trial using the existing runtime harness.

Use PYTHONPATH pointing to an archived complete source package for baseline mode.
All raw runs, including failures, must use ignored output paths.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Any, cast
from unittest.mock import patch

import semantix_cache
from semantix_cache import AsyncSemanticCache, CacheResult

from . import runtime
from .common import Case, write_result


async def experiment(
    case: Case, output: Path, *, collection: str, key: bool, snapshots: bool
) -> dict[str, Any]:
    if collection not in {"baseline", "disabled", "enabled"}:
        raise ValueError("Invalid collection mode")
    base = AsyncSemanticCache
    final: dict[str, Any] = {}
    stop, ready = Event(), Event()
    reads = 0
    current: Any = None

    class ExperimentCache:
        def __init__(self, **kwargs: Any) -> None:
            if collection != "baseline":
                kwargs["collect_coalescing_metrics"] = collection == "enabled"
            self._cache = base(**kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._cache, name)

        async def __aenter__(self) -> ExperimentCache:
            nonlocal current
            await self._cache.__aenter__()
            current = self._cache
            return self

        async def __aexit__(self, *args: Any) -> None:
            if collection != "baseline":
                value = self._cache.coalescing_snapshot()
                final["snapshot"] = None if value is None else asdict(value)
            final["flight_counts"] = self._cache._flights.counts()
            await self._cache.aclose()

        async def resolve(self, prompt: str, **kwargs: Any) -> CacheResult:
            if key:
                kwargs["coalescing_key"] = "synthetic-v1:immutable-generator"
            return await self._cache.resolve(prompt, **kwargs)

    def observe() -> None:
        nonlocal reads
        ready.set()
        while not stop.wait(0.001):
            if collection != "baseline":
                current.coalescing_snapshot()
            reads += 1

    original = runtime.run_workload

    async def workload(*args: Any, **kwargs: Any) -> Any:
        if not snapshots:
            return await original(*args, **kwargs)
        reader = asyncio.create_task(asyncio.to_thread(observe))
        try:
            await asyncio.to_thread(ready.wait)
            return await original(*args, **kwargs)
        finally:
            stop.set()
            await reader

    with (
        patch.object(
            runtime,
            "AsyncSemanticCache",
            cast(type[AsyncSemanticCache], ExperimentCache),
        ),
        patch.object(runtime, "run_workload", workload),
    ):
        result = await runtime.trial(case, output)
    source = Path(semantix_cache.__file__).parent
    result["environment"]["runtime_source_sha256"] = {
        "packages/cache/src/semantix_cache/"
        + p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }
    result["observability_experiment"] = {
        "driver_version": 1,
        "collection": collection,
        "key_supplied": key,
        "concurrent_snapshots": snapshots,
        "snapshot_reads": reads,
        "reader_interval_seconds": 0.001 if snapshots else None,
        "baseline_reader": "same scheduling; no observation API in accepted source",
        "loaded_source": str(source),
        **final,
    }
    result["correctness_passed"] = result["correctness_passed"] and final[
        "flight_counts"
    ] == (0, 0, 0, 0)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--collection", choices=["baseline", "disabled", "enabled"], required=True
    )
    parser.add_argument("--key", action="store_true")
    parser.add_argument("--snapshots", action="store_true")
    parser.add_argument("--disposable-database", action="store_true")
    args = parser.parse_args()
    case = Case(**json.loads(args.case_json))
    case.validate()
    if case.store == "pgvector" and not args.disposable_database:
        parser.error("Database workloads require --disposable-database")
    write_result(args.output, {"status": "running", "case": asdict(case)})
    try:
        result = asyncio.run(
            experiment(
                case,
                args.output,
                collection=args.collection,
                key=args.key,
                snapshots=args.snapshots,
            )
        )
    except Exception as error:
        write_result(
            args.output,
            {
                "status": "failed",
                "error_type": type(error).__name__,
                "case": asdict(case),
            },
        )
        raise
    write_result(args.output, result)
    if not result["correctness_passed"]:
        raise SystemExit("Correctness/resource check failed; evidence retained")


if __name__ == "__main__":
    main()
