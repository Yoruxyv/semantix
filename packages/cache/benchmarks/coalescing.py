"""Versioned opt-in experiment around the frozen Phase 23 runtime harness.

Control and treatment share fixtures, scheduling, verification, warmup and clocks.
Only the resolve keyword differs. Diagnostic hooks are never enabled for ordinary
timing trials. An optional archived base engine measures default-path regressions;
loading it does not replace any checkout source file or either optimized store.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter_ns
from typing import Any, cast
from unittest.mock import patch

from semantix_cache import AsyncSemanticCache, CacheResult
from semantix_cache._coalescing import Flights, Identity, Participation
from semantix_cache.protocols import GenerationCallable

from . import runtime
from .common import Case, summary, write_result

DRIVER_VERSION = 1


class Probe:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.peaks = [0, 0, 0, 0]
        self.roles: dict[asyncio.Task[Any], str] = {}
        self.samples: dict[str, list[int]] = defaultdict(list)
        self.lookup_ns: dict[asyncio.Task[Any], int] = {}
        self.final: tuple[int, int, int, int] | None = None

    def result(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "peaks": dict(
                zip(
                    (
                        "active_map",
                        "retained_records",
                        "participants",
                        "charged_key_bytes",
                    ),
                    self.peaks,
                    strict=True,
                )
            ),
            "final": self.final,
            "latencies": {
                name: summary(values, 0)["latency_ms"]
                for name, values in self.samples.items()
            },
            "note": "Separate instrumented diagnostics; role, wait/recheck and timing hooks add overhead",
        }


class ObservedFlights(Flights):
    def __init__(self, probe: Probe) -> None:
        super().__init__()
        self.probe = probe

    def admit(
        self, identity: Identity, generate: GenerationCallable
    ) -> Participation | None:
        participation = super().admit(identity, generate)
        role = (
            "overflow"
            if participation is None
            else "leader"
            if participation.leader
            else "follower"
        )
        self.probe.counts[role] += 1
        task = asyncio.current_task()
        if task is not None:
            self.probe.roles[task] = role
        self.probe.peaks = [
            max(old, new)
            for old, new in zip(self.probe.peaks, self.counts(), strict=True)
        ]
        return participation


class ObservedCache(AsyncSemanticCache):
    probe: Probe

    async def _lookup(self, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter_ns()
        result = await super()._lookup(*args, **kwargs)
        task = asyncio.current_task()
        if task is not None and len(args) == 3:
            self.probe.lookup_ns[task] = perf_counter_ns() - started
        return result

    async def _flight_lookup(self, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter_ns()
        result = await super()._flight_lookup(*args, **kwargs)
        task = asyncio.current_task()
        if task is not None:
            role = self.probe.roles[task]
            recheck = self.probe.lookup_ns.get(task, 0)
            self.probe.samples[role + "_recheck"].append(recheck)
            if role == "follower":
                self.probe.samples["follower_wait"].append(
                    max(0, perf_counter_ns() - started - recheck)
                )
        return result


def counted(probe: Probe, method: Any, category: str) -> Any:
    async def call(*args: Any, **kwargs: Any) -> Any:
        probe.counts[category] += 1
        return await method(*args, **kwargs)

    return call


def cache_type(
    base: type[AsyncSemanticCache], *, enabled: bool, probe: Probe | None
) -> type[AsyncSemanticCache]:
    class ExperimentCache:
        def __init__(self, **kwargs: Any) -> None:
            if probe is None:
                self._cache = base(**kwargs)
            else:
                observed = ObservedCache(**kwargs)
                observed.probe = probe
                observed._flights = ObservedFlights(probe)
                self._cache = observed
                for name in ("put", "record_hit", "find_nearest"):
                    setattr(
                        observed._store,
                        name,
                        counted(probe, getattr(observed._store, name), name),
                    )
            self._begun = False

        def __getattr__(self, name: str) -> Any:
            return getattr(self._cache, name)

        async def __aenter__(self) -> ExperimentCache:
            await self._cache.__aenter__()
            return self

        async def __aexit__(self, *args: Any) -> None:
            await self.aclose()

        async def resolve(self, prompt: str, **kwargs: Any) -> CacheResult:
            if probe is not None and not self._begun:
                probe.counts.clear()  # exclude frozen harness get() warmup
                self._begun = True
            started = perf_counter_ns() if probe is not None else 0
            if enabled:
                kwargs["coalescing_key"] = "synthetic-v1:immutable-generator"
            task = asyncio.current_task()
            try:
                result = await self._cache.resolve(prompt, **kwargs)
                if probe is not None and task is not None:
                    role = probe.roles.get(task, "independent")
                    probe.samples[role].append(perf_counter_ns() - started)
                    if role == "follower" and result.provider_called:
                        probe.counts["fallback"] += 1
                return result
            finally:
                if probe is not None and task is not None:
                    probe.roles.pop(task, None)
                    probe.lookup_ns.pop(task, None)

        async def aclose(self) -> None:
            if probe is not None:
                probe.final = self._cache._flights.counts()
            await self._cache.aclose()

    return cast(type[AsyncSemanticCache], ExperimentCache)


def archived_engine(path: Path) -> type[AsyncSemanticCache]:
    spec = importlib.util.spec_from_file_location(
        "semantix_cache._benchmark_base_engine", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load archived base engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(type[AsyncSemanticCache], module.AsyncSemanticCache)


async def experiment(
    case: Case, output: Path, *, mode: str, legacy_engine: Path | None = None
) -> dict[str, Any]:
    if mode not in {"control", "treatment", "legacy"}:
        raise ValueError("Unknown experiment mode")
    if mode == "legacy" and (legacy_engine is None or case.diagnostics):
        raise ValueError("Legacy mode requires an archive and uninstrumented timing")
    base = (
        archived_engine(legacy_engine)
        if mode == "legacy" and legacy_engine is not None
        else AsyncSemanticCache
    )
    probe = Probe() if case.diagnostics else None
    with patch.object(
        runtime,
        "AsyncSemanticCache",
        cache_type(base, enabled=mode == "treatment", probe=probe),
    ):
        result = await runtime.trial(case, output)
    result["coalescing_experiment"] = {
        "driver_version": DRIVER_VERSION,
        "mode": mode,
        "diagnostics": None if probe is None else probe.result(),
    }
    if probe is not None:
        result["correctness_passed"] = (
            result["correctness_passed"]
            and probe.final == (0, 0, 0, 0)
            and not probe.roles
            and not probe.lookup_ns
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    parser.add_argument(
        "--mode", choices=("control", "treatment", "legacy"), required=True
    )
    parser.add_argument("--legacy-engine", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--disposable-database", action="store_true")
    args = parser.parse_args()
    case = Case(**json.loads(args.case_json))
    if case.store == "pgvector" and not args.disposable_database:
        parser.error("Database workloads require --disposable-database")
    write_result(args.output, {"status": "running"})
    result = asyncio.run(
        experiment(case, args.output, mode=args.mode, legacy_engine=args.legacy_engine)
    )
    write_result(args.output, result)
    if not result["correctness_passed"]:
        raise SystemExit("Correctness/resource check failed; evidence retained")


if __name__ == "__main__":
    main()
