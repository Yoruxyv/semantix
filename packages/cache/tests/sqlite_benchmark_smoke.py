"""Measure real bounded SQLite scans on disposable files; never calls a provider."""

import argparse
import asyncio
import ctypes
import json
import multiprocessing
import os
import platform
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from semantix_cache import CacheConfigurationError, EmbeddingSpace
from semantix_cache._semantics import prompt_cache_key
from semantix_cache.models import CacheEntry
from semantix_cache.stores.sqlite import SQLiteStore


def rss(*, peak: bool = False) -> int | None:
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("faults", ctypes.c_ulong),
                ("peak", ctypes.c_size_t),
                ("working", ctypes.c_size_t),
                ("paged_peak", ctypes.c_size_t),
                ("paged", ctypes.c_size_t),
                ("nonpaged_peak", ctypes.c_size_t),
                ("nonpaged", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t),
                ("pagefile_peak", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return int(counters.peak if peak else counters.working)
    elif Path("/proc/self/statm").exists():
        return int(Path("/proc/self/statm").read_text().split()[1]) * int(
            ctypes.CDLL(None).getpagesize()
        )
    return None


def quantiles(samples: list[float]) -> list[float]:
    return list(1000 * np.percentile(samples, [50, 95, 99]))


async def measure(path: Path, size: int, dimensions: int) -> dict[str, Any]:
    space = EmbeddingSpace(identity="sqlite-benchmark-v1", dimensions=dimensions)
    await SQLiteStore.initialize_schema(
        path, embedding_space=space, max_size=size, default_ttl_seconds=None
    )
    store = await SQLiteStore.connect(
        path, embedding_space=space, max_size=size, default_ttl_seconds=None
    )
    rng = np.random.default_rng(20261011)
    query = tuple(float(value) for value in rng.normal(size=dimensions))
    seeded_at = perf_counter()
    try:
        for index in range(size):
            prompt = "synthetic SQLite benchmark " + str(index)
            await store.put(
                CacheEntry(
                    cache_key=prompt_cache_key(prompt),
                    namespace="default",
                    prompt=prompt,
                    response="approved synthetic response",
                    embedding=tuple(
                        float(value) for value in rng.normal(size=dimensions)
                    ),
                    created_at=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )
        populate = perf_counter() - seeded_at
        await store.aclose()
        store = await SQLiteStore.connect(
            path, embedding_space=space, max_size=size, default_ttl_seconds=None
        )
        lag: list[float] = []
        memory: list[int] = []
        running = True

        async def sample() -> None:
            while running:
                before = perf_counter()
                await asyncio.sleep(0.005)
                lag.append(max(0, perf_counter() - before - 0.005))
                memory.append(rss() or 0)

        sampler = asyncio.create_task(sample())
        scans: list[float] = []
        confirmations: list[float] = []
        try:
            started = perf_counter()
            candidate = await store.find_nearest(query, namespace="default")
            reopen_first = perf_counter() - started
            assert candidate is not None
            for _ in range(30):
                started = perf_counter()
                candidate = await store.find_nearest(query, namespace="default")
                scans.append(perf_counter() - started)
                assert candidate is not None
                started = perf_counter()
                assert await store.record_hit(
                    candidate.entry.cache_key,
                    namespace="default",
                    expected_created_at=candidate.entry.created_at,
                )
                confirmations.append(perf_counter() - started)
        finally:
            running = False
            await sampler
        result = {
            "entries": size,
            "dimensions": dimensions,
            "payload": "small ASCII response",
            "population_seconds": populate,
            "reopen_first_scan_ms": reopen_first * 1000,
            "warm_scan_ms_p50_p95_p99": quantiles(scans),
            "confirmed_hit_write_ms_p50_p95_p99": quantiles(confirmations),
            "samples": len(scans),
            "timeouts": 0,
            "lock_errors": 0,
            "sampled_rss_max_bytes": max(memory, default=rss()),
            "process_lifetime_peak_rss_bytes": rss(peak=True)
            if sys.platform == "win32"
            else None,
            "event_loop_lag_ms_p50_p95_p99": quantiles(lag),
            "event_loop_lag_max_ms": max(lag, default=0) * 1000,
            "file_bytes": (await asyncio.to_thread(path.stat)).st_size,
            "wal_bytes": (
                await asyncio.to_thread(path.with_name(path.name + "-wal").stat)
            ).st_size,
            "cold_os_cache": "not measured; reopen retains host page cache",
            "processes": 1,
        }
        started = perf_counter()
        await store.aclose()
        result["close_ms"] = (perf_counter() - started) * 1000
        result["sidecars_after_close"] = [
            sidecar.name
            for sidecar in await asyncio.to_thread(
                lambda: list(path.parent.glob(path.name + "-*"))
            )
        ]
        print(json.dumps(result), flush=True)
        return result
    finally:
        await store.aclose()


def process_scan(path: str, channel: Any) -> None:
    async def run() -> None:
        space = EmbeddingSpace(identity="sqlite-benchmark-v1", dimensions=1536)
        async with await SQLiteStore.connect(
            path, embedding_space=space, max_size=500, default_ttl_seconds=None
        ) as store:
            channel.send("ready")
            assert channel.recv() == "go"
            query = tuple(
                float(value)
                for value in np.random.default_rng(20261011).normal(size=1536)
            )
            scans: list[float] = []
            hits: list[float] = []
            for _ in range(30):
                started = perf_counter()
                candidate = await store.find_nearest(query, namespace="default")
                scans.append(perf_counter() - started)
                assert candidate is not None
                started = perf_counter()
                assert await store.record_hit(
                    candidate.entry.cache_key,
                    namespace="default",
                    expected_created_at=candidate.entry.created_at,
                )
                hits.append(perf_counter() - started)
            channel.send((scans, hits, rss(peak=True)))
            assert channel.recv() == "stop"

    try:
        asyncio.run(run())
    finally:
        channel.close()


def contention(path: Path, count: int) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    children = []
    try:
        for _ in range(count):
            parent, child = context.Pipe()
            process = context.Process(target=process_scan, args=(str(path), child))
            process.start()
            child.close()
            children.append((process, parent))
        for _, channel in children:
            assert channel.poll(30)
            assert channel.recv() == "ready"
        started = perf_counter()
        for _, channel in children:
            channel.send("go")
        results = []
        for _, channel in children:
            assert channel.poll(30)
            results.append(channel.recv())
        elapsed = perf_counter() - started
        return {
            "processes": count,
            "entries": 500,
            "dimensions": 1536,
            "scan_ms_p50_p95_p99": quantiles(
                [value for scans, _, _ in results for value in scans]
            ),
            "confirmed_hit_ms_p50_p95_p99": quantiles(
                [value for _, hits, _ in results for value in hits]
            ),
            "elapsed_seconds": elapsed,
            "operations_per_process": 30,
            "process_lifetime_peak_rss_bytes": [peak for _, _, peak in results],
            "timeouts": 0,
            "lock_errors": 0,
        }
    finally:
        for process, channel in children:
            if process.is_alive():
                channel.send("stop")
                process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(10)
            channel.close()
            assert not process.is_alive()
            assert process.exitcode == 0
            process.close()


async def extended() -> None:
    with tempfile.TemporaryDirectory(prefix="semantix-sqlite-contention-") as directory:
        path = Path(directory) / "contention.db"
        baseline = await measure(path, 500, 1536)
        processes = [
            await asyncio.to_thread(contention, path, count) for count in (1, 2, 4)
        ]
        space = EmbeddingSpace(identity="large-payload", dimensions=384)
        large_path = Path(directory) / "large.db"
        await SQLiteStore.initialize_schema(
            large_path, embedding_space=space, max_size=5, default_ttl_seconds=None
        )
        async with await SQLiteStore.connect(
            large_path, embedding_space=space, max_size=5, default_ttl_seconds=None
        ) as store:
            for index in range(5):
                prompt = str(index)
                await store.put(
                    CacheEntry(
                        cache_key=prompt_cache_key(prompt),
                        namespace="default",
                        prompt=prompt,
                        response="😀" * 100000,
                        embedding=(1.0,) + (0.0,) * 383,
                        created_at=datetime.now(UTC),
                    )
                )
            samples = []
            for _ in range(30):
                started = perf_counter()
                match = await store.find_nearest(
                    (1.0,) + (0.0,) * 383, namespace="default"
                )
                assert match is not None
                assert match.entry.response == "😀" * 100000
                samples.append(perf_counter() - started)
            large = {
                "entries": 5,
                "dimensions": 384,
                "response": "100000 non-BMP Unicode characters per entry",
                "scan_ms_p50_p95_p99": quantiles(samples),
                "file_bytes": (await asyncio.to_thread(large_path.stat)).st_size,
                "wal_bytes": (
                    await asyncio.to_thread(
                        large_path.with_name(large_path.name + "-wal").stat
                    )
                ).st_size,
                "process_lifetime_peak_rss_bytes": rss(peak=True),
                "timeouts": 0,
                "lock_errors": 0,
            }
    result = {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "baseline": baseline,
        "concurrent_processes": processes,
        "large_payload": large,
    }
    await asyncio.to_thread(
        Path(".cache/sqlite-performance-extended.json").write_text,
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result), flush=True)


async def main() -> None:
    output = Path(".cache/sqlite-performance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="semantix-sqlite-benchmark-") as directory:
        results = []
        for size, dimensions in (
            (500, 384),
            (500, 1536),
            (500, 16000),
            (5000, 384),
            (5000, 1536),
        ):
            results.append(
                await measure(
                    Path(directory) / f"cache-{size}-{dimensions}.db", size, dimensions
                )
            )
        try:
            await SQLiteStore.initialize_schema(
                Path(directory) / "rejected.db",
                embedding_space=EmbeddingSpace(identity="too-wide", dimensions=16000),
                max_size=5000,
            )
        except CacheConfigurationError:
            rejected = True
        else:
            raise AssertionError("Oversized vector envelope accepted")
    await asyncio.to_thread(
        output.write_text,
        json.dumps(
            {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "logical_cpus": os.cpu_count(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "numpy": np.__version__,
                "method": "seed 20261011; real public puts with FULL/WAL; first scan after reopen; 30 sequential warm scans each followed by confirmation; 5ms loop/RSS sampler; no OS cache flush",
                "rejected_5000x16000": rejected,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extended-only", action="store_true")
    asyncio.run(extended() if parser.parse_args().extended_only else main())
