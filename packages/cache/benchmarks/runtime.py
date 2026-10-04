"""Run one fresh-process runtime trial, with optional separate profiling evidence.

From packages/cache: python -m benchmarks.runtime --case-json ... --output ...
Database access requires SEMANTIX_BENCHMARK_DATABASE_URL and an explicit disposable
acknowledgement. Fixtures, migrations, prefill, warmup and teardown are never timed.
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import os
import tracemalloc
from collections import Counter
from collections.abc import AsyncGenerator, Sequence
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager, nullcontext
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

from semantix_cache import (
    AsyncSemanticCache,
    CacheMatch,
    CachePolicy,
    CacheResult,
    CacheStore,
    CacheTimeoutError,
    MemoryStore,
    memory,
)

from .common import (
    Case,
    Dataset,
    Embedder,
    Generator,
    environment,
    now_ns,
    rss_bytes,
    summary,
    write_result,
)

WORKLOADS = {
    "hits",
    "get",
    "mixed90",
    "mixed50",
    "normal90",
    "cold",
    "burst",
    "read-only",
    "refresh",
    "bypass",
    "private",
    "search",
    "write",
    "empty",
    "embedding",
    "generation",
    "cancellation",
    "search-cancellation",
    "saturation",
    "stability",
}


class FixtureStore(MemoryStore):
    """Fixed validated candidate/confirmation: isolate engine work, no search IO.

    This is a benchmark test double, not a proposed storage implementation. Uses
    no expiry or mutations; entry/space validation in AsyncSemanticCache remains.
    """

    def __init__(self, data: Dataset) -> None:
        super().__init__(embedding_space=data.space, default_ttl_seconds=None)
        self.match = CacheMatch(
            entry=data.entry(0), similarity_score=1.0, expires_at=None
        )

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        if len(embedding) != self.embedding_space.dimensions:
            raise ValueError("Invalid fixture vector")
        return self.match if namespace == "benchmark" else None

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        return (
            namespace == "benchmark"
            and cache_key == self.match.entry.cache_key
            and expected_created_at == self.match.entry.created_at
        )


class DatabaseProbe:
    """Diagnostic-only instrumentation; never used for uninstrumented baselines."""

    def __init__(self) -> None:
        self.wait_ns: list[int] = []
        self.peak = 0
        self.queries: Counter[str] = Counter()
        self.query_seconds: Counter[str] = Counter()
        self.search_statement: tuple[str, tuple[Any, ...]] | None = None

    def query(self, record: Any) -> None:
        sql = record.query
        category = (
            "catalog"
            if "pg_catalog" in sql
            else "search"
            if "WITH eligible" in sql
            else "other"
        )
        self.queries[category] += 1
        self.query_seconds[category] += record.elapsed
        if category == "search":
            self.search_statement = (sql, record.args)

    def reset(self) -> None:
        self.wait_ns.clear()
        self.peak = 0
        self.queries.clear()
        self.query_seconds.clear()
        self.search_statement = None

    def result(self) -> dict[str, Any]:
        return {
            "acquisition": summary(self.wait_ns, sum(self.wait_ns) / 1e9),
            "connection_peak_exact": self.peak,
            "driver_logged_queries": dict(self.queries),
            "driver_logged_query_seconds": dict(self.query_seconds),
            "acquisition_note": "includes acquire/setup; not exclusively queue wait; SQL logs include pool-reset batches and cold-connection type introspection",
        }


@asynccontextmanager
async def make_store(
    case: Case, data: Dataset, probe: DatabaseProbe
) -> AsyncGenerator[tuple[CacheStore, Any, dict[str, Any]], None]:
    if case.store == "fixture":
        async with FixtureStore(data) as fixture_store:
            yield fixture_store, None, {}
        return
    if case.store == "memory":
        async with MemoryStore(
            embedding_space=data.space,
            max_size=case.capacity,
            default_ttl_seconds=case.ttl_seconds,
        ) as memory_store:
            yield memory_store, None, {}
        return
    import asyncpg  # noqa: PLC0415 -- optional database extra

    from semantix_cache.stores.pgvector import PgVectorStore  # noqa: PLC0415 -- optional database extra

    dsn = os.environ.get("SEMANTIX_BENCHMARK_DATABASE_URL")
    if not dsn:
        raise ValueError("Set SEMANTIX_BENCHMARK_DATABASE_URL to a disposable database")
    schema = "semantix_bench_" + uuid4().hex

    async def initialize(connection: Any) -> None:
        if case.diagnostics:
            connection.add_query_logger(probe.query)

    pool = await asyncpg.create_pool(
        dsn,
        min_size=case.pool_size,
        max_size=case.pool_size,
        timeout=10,
        command_timeout=30,
        init=initialize,
    )
    if pool is None:
        raise RuntimeError("Pool construction failed")
    store = PgVectorStore(
        pool=pool,
        embedding_space=data.space,
        schema=schema,
        max_size=case.capacity,
        default_ttl_seconds=case.ttl_seconds,
        operation_timeout_seconds=0.1 if case.workload == "saturation" else 30,
    )
    try:
        async with pool.acquire() as connection:
            # Explicit operator setup for this acknowledged disposable database.
            await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            meta = {
                "postgres_version": await connection.fetchval("SHOW server_version"),
                "pgvector_version": await connection.fetchval(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'"
                ),
                "asyncpg_version": asyncpg.__version__,
                "topology": "external database; caller-owned long-lived asyncpg pool; fresh UUID schema per trial",
                "settings": {
                    key: await connection.fetchval("SELECT current_setting($1)", key)
                    for key in (
                        "shared_buffers",
                        "max_connections",
                        "max_parallel_workers_per_gather",
                        "jit",
                        "fsync",
                        "synchronous_commit",
                    )
                },
                "pool_min": case.pool_size,
                "pool_max": case.pool_size,
                "statement_cache_size": 100,
                "prepared_statements": "asyncpg defaults retained",
            }
        await store.initialize_schema(migration_pool=pool)
        await store.validate_schema()
        original = cast(Any, asyncpg.pool.Pool)._acquire

        async def acquire(instance: Any, acquire_timeout: float | None) -> Any:
            started = now_ns()
            connection = await original(instance, acquire_timeout)
            if instance is pool:
                probe.wait_ns.append(now_ns() - started)
                probe.peak = max(probe.peak, pool.get_size() - pool.get_idle_size())
            return connection

        with (
            patch.object(asyncpg.pool.Pool, "_acquire", acquire)
            if case.diagnostics
            else nullcontext()
        ):
            yield store, pool, meta
    finally:
        await store.aclose()
        if pool.is_closing():
            raise RuntimeError("Borrowed pool was unexpectedly closed")
        async with pool.acquire() as connection:
            if not schema.startswith("semantix_bench_") or len(schema) != 47:
                raise RuntimeError("Unsafe benchmark cleanup target")
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        async with asyncio.timeout(10):
            await pool.close()


class Operations:
    def __init__(
        self,
        case: Case,
        data: Dataset,
        store: CacheStore,
        cache: AsyncSemanticCache,
        embedder: Embedder,
        generate: Generator,
    ) -> None:
        self.case, self.data, self.store, self.cache = case, data, store, cache
        self.embedder, self.generate = embedder, generate
        self.stability_mode = case.workload == "stability"
        self.rotation = 0
        self.hits = 0
        self.writes = 0
        self.expected_hits = 0
        self.errors: Counter[str] = Counter()
        self.entries = (
            [data.entry(case.cache_size + i) for i in range(case.requests)]
            if case.workload == "write"
            else []
        )

    def request(self, index: int) -> tuple[int, CachePolicy]:
        c = self.case
        workload = c.workload
        if self.stability_mode:
            return (self.rotation + index) % len(
                self.data.vectors
            ), CachePolicy.REFRESH if workload == "refresh" else CachePolicy.NORMAL
        if c.store == "fixture":
            return 0, CachePolicy.NORMAL
        if workload == "stability":
            return index % max(1, c.cache_size), CachePolicy.NORMAL
        if workload in {
            "hits",
            "get",
            "search",
            "read-only",
            "refresh",
            "bypass",
            "private",
            "empty",
            "embedding",
            "generation",
        }:
            return index % max(1, c.cache_size), {
                "read-only": CachePolicy.READ_ONLY,
                "refresh": CachePolicy.REFRESH,
                "bypass": CachePolicy.BYPASS,
                "private": CachePolicy.PRIVATE,
            }.get(workload, CachePolicy.NORMAL)
        if workload in {"mixed90", "normal90", "mixed50"}:
            hit = index % (2 if workload == "mixed50" else 10) < (
                1 if workload == "mixed50" else 9
            )
            return (
                index % max(1, c.cache_size) if hit else c.cache_size + index
            ), CachePolicy.NORMAL if workload == "normal90" else CachePolicy.READ_ONLY
        if workload == "burst":
            return c.cache_size + index // c.concurrency, CachePolicy.NORMAL
        return c.cache_size + index, CachePolicy.NORMAL

    async def execute(self, index: int) -> Any:
        vector_index, policy = self.request(index)
        prompt = self.data.prompt(vector_index)
        workload = self.case.workload
        if workload == "embedding":
            return await self.embedder.embed(prompt)
        if workload == "generation":
            return await self.generate(prompt)
        if workload == "search":
            return await self.store.find_nearest(
                self.data.vectors[vector_index], namespace="benchmark"
            )
        if workload == "write":
            await self.store.put(self.entries[index])
            return None
        if workload in {"get", "empty"}:
            return await self.cache.get(
                prompt, namespace="empty" if workload == "empty" else "benchmark"
            )
        return await self.cache.resolve(
            prompt, namespace="benchmark", policy=policy, generate=self.generate
        )

    def verify(self, index: int, result: Any) -> None:
        vector_index, policy = self.request(index)
        prompt = self.data.prompt(vector_index)
        workload = self.case.workload
        if workload == "write":
            self.writes += 1
            return
        if workload in {"embedding", "generation", "empty"}:
            if workload == "empty" and result is not None:
                raise RuntimeError("Empty namespace returned a hit")
            return
        if workload in {"get", "search"}:
            if result is None:
                raise RuntimeError("Known seeded lookup missed")
            response = (
                result.entry.response
                if isinstance(result, CacheMatch)
                else result.response
            )
            if response != self.data.response(prompt):
                raise RuntimeError("Wrong candidate/result reuse")
            self.hits += 1
            return
        if not isinstance(result, CacheResult) or result.response != self.data.response(
            prompt
        ):
            raise TypeError("Invalid or cross-request result")
        nominal_hit = vector_index < self.case.cache_size and policy in {
            CachePolicy.NORMAL,
            CachePolicy.READ_ONLY,
        }
        self.expected_hits += int(nominal_hit)
        if (
            workload not in {"normal90", "burst", "stability"}
            and result.cache_hit != nominal_hit
        ):
            raise RuntimeError("Unexpected hit/miss on deterministic corpus")
        self.hits += int(result.cache_hit)
        self.writes += int(result.cache_written)


async def measure(
    operation: Operations, indices: Sequence[int], concurrency: int
) -> tuple[list[int], float]:
    remaining = iter(indices)
    samples: list[int] = []
    start = asyncio.Event()

    async def worker() -> None:
        await start.wait()
        for index in remaining:
            before = now_ns()
            try:
                result = await operation.execute(index)
            except Exception as exc:  # noqa: BLE001 -- trial records failures and exits nonzero, never hides them
                operation.errors[type(exc).__name__] += 1
            else:
                samples.append(now_ns() - before)
                try:
                    operation.verify(index, result)
                except RuntimeError:
                    operation.errors["correctness_failure"] += 1
                continue
            samples.append(now_ns() - before)

    tasks = [
        asyncio.create_task(worker()) for _ in range(min(concurrency, len(indices)))
    ]
    began = perf_counter()
    start.set()
    await asyncio.gather(*tasks)
    return samples, perf_counter() - began


async def cancellation_probe(
    cache: AsyncSemanticCache, store: CacheStore, data: Dataset, concurrency: int
) -> dict[str, Any]:
    started = asyncio.Event()
    calls = 0

    async def blocked(prompt: str) -> str:  # noqa: ARG001 -- generation signature
        nonlocal calls
        calls += 1
        if calls == concurrency:
            started.set()
        await asyncio.Event().wait()
        return "unreachable"

    tasks = [
        asyncio.create_task(
            cache.resolve(data.prompt(i), namespace="cancel", generate=blocked)
        )
        for i in range(concurrency)
    ]
    async with asyncio.timeout(30):
        await started.wait()
        before = now_ns()
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = now_ns() - before
        if not all(isinstance(value, asyncio.CancelledError) for value in results):
            raise RuntimeError("Cancellation did not propagate")
        if await store.find_nearest(data.vectors[0], namespace="cancel") is not None:
            raise RuntimeError("Cancelled generation wrote a partial entry")
    return {
        "cancelled": len(tasks),
        "cancel_and_drain_ms": elapsed / 1e6,
        "partial_writes": 0,
    }


async def search_cancellation_probe(
    store: CacheStore, data: Dataset, concurrency: int
) -> dict[str, Any]:
    """Cancel real searches/queue waiters, then drain shielded numerical/DB work."""
    tasks = [
        asyncio.create_task(store.find_nearest(data.vectors[0], namespace="benchmark"))
        for _ in range(concurrency)
    ]
    await asyncio.sleep(0)
    before = now_ns()
    requested = 0
    for task in tasks[::2]:
        if not task.done():
            task.cancel()
            requested += 1
    async with asyncio.timeout(30):
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(store, MemoryStore) and store._workers:
            await asyncio.gather(*tuple(store._workers))
            await asyncio.sleep(0)
    cancelled = sum(isinstance(value, asyncio.CancelledError) for value in results)
    successful = [
        value for value in results if not isinstance(value, asyncio.CancelledError)
    ]
    if cancelled != requested or any(
        not isinstance(value, CacheMatch)
        or value.entry.response != data.response(data.prompt(0))
        for value in successful
    ):
        raise RuntimeError("Search cancellation corrupted state or failed to propagate")
    return {
        "requested_cancellations": requested,
        "observed_cancellations": cancelled,
        "successful_searches": len(successful),
        "cancel_and_drain_ms": (now_ns() - before) / 1e6,
        "numerical_workers_remaining": len(store._workers)
        if isinstance(store, MemoryStore)
        else None,
    }


async def saturation_probe(
    cache: AsyncSemanticCache, pool: Any, size: int, data: Dataset
) -> dict[str, Any]:
    if pool is None:
        raise ValueError("Saturation workload requires pgvector")
    async with AsyncExitStack() as stack:
        for _ in range(size):
            await stack.enter_async_context(pool.acquire(timeout=10))
        began = now_ns()
        try:
            await cache.get(data.prompt(0))
        except CacheTimeoutError:
            timeout_ms = (now_ns() - began) / 1e6
        else:
            raise RuntimeError("Saturated pool did not time out")
        task = asyncio.create_task(cache.get(data.prompt(0)))
        await asyncio.sleep(0.025)
        began = now_ns()
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        if not isinstance(result[0], asyncio.CancelledError):
            raise TypeError("Pool waiter cancellation did not propagate")
        cancel_ms = (now_ns() - began) / 1e6
    async with pool.acquire(timeout=10) as connection:
        if await connection.fetchval("SELECT 1") != 1:
            raise RuntimeError("Pool did not recover")
    return {
        "timeout_ms": timeout_ms,
        "waiter_cancel_ms": cancel_ms,
        "pool_reusable": True,
    }


async def run_workload(
    case: Case,
    operation: Operations,
    cache: AsyncSemanticCache,
    store: CacheStore,
    pool: Any,
    data: Dataset,
    result: dict[str, Any],
) -> tuple[list[int], float]:
    if case.workload == "cancellation":
        result["cancellation"] = await cancellation_probe(
            cache, store, data, case.concurrency
        )
        return [], 0.0
    if case.workload == "search-cancellation":
        result["search_cancellation"] = await search_cancellation_probe(
            store, data, case.concurrency
        )
        return [], 0.0
    if case.workload == "saturation":
        result["saturation"] = await saturation_probe(cache, pool, case.pool_size, data)
        return [], 0.0
    if case.workload == "stability":
        return await stability(case, operation, result)
    if case.workload == "burst":
        samples, elapsed = [], 0.0
        for offset in range(0, case.requests, case.concurrency):
            batch, seconds = await measure(
                operation,
                list(range(offset, min(offset + case.concurrency, case.requests))),
                case.concurrency,
            )
            samples.extend(batch)
            elapsed += seconds
        return samples, elapsed
    return await measure(operation, list(range(case.requests)), case.concurrency)


@asynccontextmanager
async def runtime_probe(
    store: CacheStore, enabled: bool, profile_output: Path | None = None
) -> AsyncGenerator[dict[str, list[int]], None]:
    """Separate diagnostic pass: queue acquisition symptoms and event-loop lag."""
    measurements: dict[str, list[int]] = {
        "slot_acquire": [],
        "lock_acquire": [],
        "event_loop_lag": [],
    }
    if not enabled:
        yield measurements
        return

    async def monitor() -> None:
        while True:
            expected = now_ns() + 10_000_000
            await asyncio.sleep(0.01)
            measurements["event_loop_lag"].append(max(0, now_ns() - expected))

    def tracked(original: Any, name: str) -> Any:
        async def acquire() -> bool:
            before = now_ns()
            result = await original()
            measurements[name].append(now_ns() - before)
            return bool(result)

        return acquire

    with ExitStack() as stack:
        if isinstance(store, MemoryStore) and profile_output is not None:
            original_nearest = memory._nearest
            calls = 0

            def profiled_nearest(query: Any, items: Any) -> CacheMatch:
                nonlocal calls
                if calls >= 3:
                    return original_nearest(query, items)
                ordinal = calls
                calls += 1
                worker_profile = cProfile.Profile()
                worker_profile.enable()
                try:
                    return original_nearest(query, items)
                finally:
                    worker_profile.disable()
                    worker_profile.dump_stats(
                        str(profile_output.with_suffix(f".worker-{ordinal}.prof"))
                    )

            stack.enter_context(patch.object(memory, "_nearest", profiled_nearest))
        if isinstance(store, MemoryStore):
            for resource, name in (
                (store._slot, "slot_acquire"),
                (store._lock, "lock_acquire"),
            ):
                stack.enter_context(
                    patch.object(resource, "acquire", tracked(resource.acquire, name))
                )
        task = asyncio.create_task(monitor())
        try:
            yield measurements
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def trial(case: Case, output: Path) -> dict[str, Any]:
    case.validate()
    if case.workload not in WORKLOADS:
        raise ValueError("Unknown workload")
    before_data = rss_bytes()
    data = Dataset(case)
    embedder, generate = Embedder(data), Generator(case.generation_delay)
    probe = DatabaseProbe()
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "runtime",
        "environment": environment(case),
        "dataset_sha256": data.digest,
        "rss": {"before_dataset": before_data, "after_dataset": rss_bytes()},
    }
    async with make_store(case, data, probe) as (store, pool, database):
        result["database"] = database
        for index in range(case.cache_size if case.store != "fixture" else 0):
            await store.put(data.entry(index))
        async with AsyncSemanticCache(
            embedder=embedder, store=store, similarity_threshold=case.threshold
        ) as cache:
            # Initialize the executor/BLAS and pool statements without timing setup.
            await asyncio.to_thread(lambda: None)
            if case.cache_size:
                await cache.get(data.prompt(0), namespace="benchmark")
            embedder.calls = 0
            generate.calls = 0
            generate.prompts.clear()
            probe.reset()
            operation = Operations(case, data, store, cache, embedder, generate)
            result["rss"]["after_seed"] = rss_bytes()
            profile = cProfile.Profile()
            if case.allocations:
                tracemalloc.start()
            if case.profile:
                profile.enable()
            async with runtime_probe(
                store, case.diagnostics, output if case.worker_profile else None
            ) as measurements:
                samples, elapsed = await run_workload(
                    case, operation, cache, store, pool, data, result
                )
            if case.diagnostics:
                result["runtime_probe"] = {
                    name: summary(values, elapsed)
                    for name, values in measurements.items()
                }
            if case.profile:
                profile.disable()
                profile.dump_stats(str(output.with_suffix(".prof")))
            if case.allocations:
                current, peak = tracemalloc.get_traced_memory()
                result["allocation"] = {
                    "retained_bytes": current,
                    "peak_bytes": peak,
                    "top_retained": [
                        str(stat)
                        for stat in tracemalloc.take_snapshot().statistics("lineno")[
                            :15
                        ]
                    ],
                    "note": "tracemalloc Python-tracked/NumPy-tracked allocations; native BLAS/DB buffers may be absent; latency is instrumented",
                }
                tracemalloc.stop()
            result.update(summary(samples, elapsed))
            result.update(
                {
                    "latencies_ns": samples,
                    "cache_hits": operation.hits,
                    "cache_writes": operation.writes,
                    "hit_ratio": operation.hits / len(samples) if samples else None,
                    "nominal_seeded_requests": operation.expected_hits,
                    "embedding_calls": embedder.calls,
                    "generation_calls": generate.calls,
                    "duplicate_generation_count": generate.calls
                    - len(generate.prompts),
                    "errors": dict(operation.errors),
                    "error_rate": sum(operation.errors.values()) / len(samples)
                    if samples
                    else 0.0,
                    "instrumented": case.diagnostics
                    or case.profile
                    or case.allocations,
                }
            )
            if case.workload == "stability":
                total = result["stability"]["total_operations"]
                result["operations"] = total
                result["elapsed_seconds"] = result["stability"]["active_seconds"]
                result["operations_per_second"] = result["stability"][
                    "operations_per_second"
                ]
                result["hit_ratio"] = operation.hits / total
                result["error_rate"] = sum(operation.errors.values()) / total
            result["rss"]["after_measurement"] = rss_bytes()
            if case.diagnostics:
                result["database_probe"] = probe.result() if pool is not None else None
                if pool is not None and probe.search_statement is not None:
                    sql, args = probe.search_statement
                    async with pool.acquire() as connection:
                        plan = await connection.fetchval(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *args
                        )
                    result["explain"] = json.loads(plan)
            if isinstance(store, MemoryStore) and store._workers:
                await asyncio.gather(*tuple(store._workers))
                await asyncio.sleep(0)
            result["live_entries_after"] = await store.clear(namespace="benchmark")
            if result["live_entries_after"] > case.capacity:
                raise RuntimeError("Store exceeded configured capacity")
            result["cleanup_before_close"] = {
                "engine_active": cache._state.active,
                "store_active": cast(Any, store)._state.active,
                "numerical_workers": len(store._workers)
                if isinstance(store, MemoryStore)
                else None,
                "pool_idle": pool.get_idle_size() if pool is not None else None,
                "pool_size": pool.get_size() if pool is not None else None,
                "pending_other_tasks": len(
                    [
                        task
                        for task in asyncio.all_tasks()
                        if task is not asyncio.current_task() and not task.done()
                    ]
                ),
            }
    result["rss"]["after_close"] = rss_bytes()
    cleanup = result["cleanup_before_close"]
    result["correctness_passed"] = (
        not result["errors"]
        and cleanup["pending_other_tasks"] == 0
        and cleanup["engine_active"] == 0
        and cleanup["store_active"] == 0
        and cleanup["numerical_workers"] in (None, 0)
        and cleanup["pool_idle"] == cleanup["pool_size"]
    )
    return result


async def stability(
    case: Case, operation: Operations, result: dict[str, Any]
) -> tuple[list[int], float]:
    """Bounded churn: alternate fixed-corpus lookup and refresh under short TTL.

    Batch counters/latencies are reduced per window so benchmark bookkeeping does
    not itself grow with duration. RSS includes the interpreter allocator's caches.
    """
    began = perf_counter()
    windows: list[dict[str, Any]] = []
    count = 0
    elapsed = 0.0
    last_elapsed = 0.0
    representative: list[int] = []
    while perf_counter() - began < case.duration:
        operation.case = Case(
            **{
                **asdict(case),
                "workload": "refresh" if len(windows) % 5 == 0 else "stability",
            }
        )
        operation.rotation = count % len(operation.data.vectors)
        batch, seconds = await measure(
            operation, list(range(case.requests)), case.concurrency
        )
        representative = batch
        last_elapsed = seconds
        elapsed += seconds
        count += len(batch)
        windows.append(
            {
                "seconds": perf_counter() - began,
                "operations": count,
                "rss": rss_bytes(),
                "latency": summary(batch, seconds),
                "tasks": len(asyncio.all_tasks()),
                "store_items": len(operation.store._items)
                if isinstance(operation.store, MemoryStore)
                else None,
            }
        )
        if len(windows) > 120:
            windows = windows[::2]
        # Yield outside timed batches for IO/sampling; not counted as throughput.
        await asyncio.sleep(0)
    if count == 0:
        raise RuntimeError("Stability duration elapsed before any measured batch")
    result["stability"] = {
        "duration_seconds": perf_counter() - began,
        "total_operations": count,
        "active_seconds": elapsed,
        "operations_per_second": count / elapsed,
        "windows": windows,
        "note": "last-batch quantiles below; cumulative counters above; bounded fixture corpus and benchmark bookkeeping",
    }
    return representative, last_elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--disposable-database", action="store_true")
    args = parser.parse_args()
    case = Case(**json.loads(args.case_json))
    if case.store == "pgvector" and not args.disposable_database:
        parser.error("Database workloads require --disposable-database")
    # Validate the destination before profile output can be written.
    write_result(args.output, {"status": "running", "case": asdict(case)})
    result = asyncio.run(trial(case, args.output))
    write_result(args.output, result)
    if not result["correctness_passed"]:
        raise SystemExit(
            "Benchmark correctness/resource check failed; raw evidence retained"
        )


if __name__ == "__main__":
    main()
