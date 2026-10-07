"""Measure the bounded Redis exact scan; synthetic data on disposable Redis."""

import asyncio
import ctypes
import json
import os
import platform
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import numpy as np

from semantix_cache import CacheTimeoutError, EmbeddingSpace
from semantix_cache._semantics import normalized_vector, prompt_cache_key
from semantix_cache.models import CacheEntry
from semantix_cache.stores import redis as module
from semantix_cache.stores.redis import RedisStore


def rss() -> int | None:
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
            return int(counters.working)
    elif Path("/proc/self/statm").exists():
        return int(Path("/proc/self/statm").read_text().split()[1]) * int(
            ctypes.CDLL(None).getpagesize()
        )
    return None


async def measure(size: int, dimensions: int) -> dict[str, Any]:
    store = await RedisStore.connect(
        url=os.environ["REDIS_TEST_URL"],
        embedding_space=EmbeddingSpace(identity="benchmark-v1", dimensions=dimensions),
        key_prefix="redis_bench_" + uuid4().hex,
        max_size=size,
        default_ttl_seconds=None,
    )
    active = store._client
    await store.initialize_schema(initialization_client=active)
    generator = np.random.default_rng(20261007)
    query = normalized_vector(
        tuple(float(v) for v in generator.normal(size=dimensions)),
        dimensions=dimensions,
    )
    before_rss = rss()
    try:
        for n in range(size):
            prompt = "synthetic benchmark " + str(n)
            await store.put(
                CacheEntry(
                    cache_key=prompt_cache_key(prompt),
                    namespace="default",
                    prompt=prompt,
                    response="approved synthetic response",
                    embedding=tuple(
                        float(v) for v in generator.normal(size=dimensions)
                    ),
                    created_at=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )
        rows = await active.eval_ro(
            module._READ,
            3,
            *store._config.keys,
            *store._config.descriptor,
            "snapshot",
            "default",
        )
        vector_bytes = sum(len(row[3]) for row in rows)
        assert vector_bytes == size * dimensions * 8
        scores = []
        for _ in range(5):
            started = perf_counter()
            module._score(query, rows, dimensions, "default")
            scores.append(perf_counter() - started)
        seeded_rss = rss()
        memory = [await active.memory_usage(key) or 0 for key in store._config.keys]
        await store.find_nearest(tuple(query), namespace="default")
        stats_before = (await active.info("commandstats"))["cmdstat_eval_ro"]
        lookups = []
        sampled_rss = []
        for _ in range(30):
            started = perf_counter()
            assert await store.find_nearest(tuple(query), namespace="default")
            lookups.append(perf_counter() - started)
            sampled_rss.append(rss() or 0)
        stats_after = (await active.info("commandstats"))["cmdstat_eval_ro"]
        slow = await active.slowlog_get(128)
        blocking = [
            item["duration"] / 1000
            for item in slow
            if b"EVAL_RO" in item["command"]
            and store._config.prefix.encode() in item["command"]
        ]
        script_mean = (
            (stats_after["usec"] - stats_before["usec"])
            / (stats_after["calls"] - stats_before["calls"])
            / 1000
        )
        result = {
            "entries": size,
            "dimensions": dimensions,
            "vector_bytes": vector_bytes,
            "redis_binding_bytes": sum(memory),
            "rss_before": before_rss,
            "rss_seeded": seeded_rss,
            "rss_sampled_max": max(sampled_rss),
            "scoring_ms_mean": 1000 * float(np.mean(scores)),
            "lua_eval_ro_ms_mean": script_mean,
            "lua_eval_ro_ms_max_observed": max(blocking, default=None),
            "lookup_ms_p50_p95_p99": list(1000 * np.percentile(lookups, [50, 95, 99])),
            "samples": len(lookups),
            "operation_deadline_seconds": 30,
        }
        # A genuine tiny operation deadline is a typed error, never a false miss.

        store._config = replace(store._config, timeout=0.000001)
        try:
            await store.find_nearest(tuple(query), namespace="default")
        except CacheTimeoutError:
            result["tiny_deadline"] = "CacheTimeoutError"
        else:
            raise AssertionError("Tiny deadline was not enforced")
        store._config = replace(store._config, timeout=30)
        print(json.dumps(result))
        return result
    finally:
        await store.aclose()
        cleanup = await RedisStore.connect(
            url=os.environ["REDIS_TEST_URL"],
            embedding_space=store.embedding_space,
            key_prefix=store._config.prefix,
            max_size=size,
            default_ttl_seconds=None,
        )
        await cleanup._client.delete(*cleanup._config.keys)
        await cleanup.aclose()


async def main() -> None:
    results = [await measure(500, 1536), await measure(2000, 1536)]
    output = Path(".cache/redis-performance.json")
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        output.write_text,
        json.dumps(
            {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
