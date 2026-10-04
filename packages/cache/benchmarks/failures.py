"""Bounded provider failures and unavailable-database connection cleanup.

The database failure uses a reserved non-listening loopback socket; it never
connects to an operator's database or requires its credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from semantix_cache import (
    AsyncSemanticCache,
    CacheStoreError,
    CacheTimeoutError,
    EmbeddingError,
    GenerationError,
    MemoryStore,
)

from .common import (
    Case,
    Dataset,
    Embedder,
    environment,
    now_ns,
    rss_bytes,
    summary,
    write_result,
)


class BrokenEmbedder(Embedder):
    async def embed(self, text: str) -> tuple[float, ...]:  # noqa: ARG002 -- structural signature
        self.calls += 1
        raise EmbeddingError("Synthetic benchmark embedding failure")


async def failed_generation(prompt: str) -> str:  # noqa: ARG001 -- generation signature
    raise GenerationError("Synthetic benchmark generation failure")


async def suite(case: Case) -> dict[str, Any]:
    data = Dataset(case)
    metrics: dict[str, Any] = {}
    async with MemoryStore(embedding_space=data.space) as store:
        for name, embedder, error in (
            ("embedding_error", BrokenEmbedder(data), EmbeddingError),
            ("generation_error", Embedder(data), GenerationError),
        ):
            async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
                samples = []
                began = perf_counter()
                for index in range(case.requests):
                    before = now_ns()
                    try:
                        await cache.resolve(
                            data.prompt(index),
                            namespace="failure",
                            generate=failed_generation,
                        )
                    except error:
                        samples.append(now_ns() - before)
                    else:
                        raise RuntimeError(
                            "Expected provider failure did not propagate"
                        )
                metrics[name] = {
                    **summary(samples, perf_counter() - began),
                    "expected_error_count": len(samples),
                    "embedding_calls": embedder.calls,
                }
            if await store.clear(namespace="failure") != 0:
                raise RuntimeError("Provider failure persisted partial output")
    if case.store == "pgvector":
        from semantix_cache.stores.pgvector import PgVectorStore  # noqa: PLC0415 -- optional database extra

        samples = []
        reported_errors: Counter[str] = Counter()
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            began = perf_counter()
            for _ in range(case.requests):
                before = now_ns()
                try:
                    await PgVectorStore.connect(
                        dsn=f"postgresql://benchmark@127.0.0.1:{port}/unused",
                        embedding_space=data.space,
                        connect_timeout_seconds=0.2,
                    )
                except (CacheStoreError, CacheTimeoutError) as exc:
                    reported_errors[type(exc).__name__] += 1
                    samples.append(now_ns() - before)
                else:
                    raise RuntimeError(
                        "Non-listening socket unexpectedly accepted connection"
                    )
        metrics["database_unavailable"] = {
            **summary(samples, perf_counter() - began),
            "expected_error_count": len(samples),
            "topology": "reserved non-listening loopback socket",
            "reported_error_classes": dict(reported_errors),
            "connect_timeout_seconds": 0.2,
        }
    remaining = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    if remaining:
        raise RuntimeError("Failure path retained background tasks")
    return {
        "schema_version": 1,
        "kind": "failures",
        "environment": environment(case),
        "dataset_sha256": data.digest,
        "metrics": metrics,
        "rss": rss_bytes(),
        "partial_writes": 0,
        "pending_tasks": 0,
        "correctness_passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--disposable-database", action="store_true")
    args = parser.parse_args()
    case = Case(**json.loads(args.case_json))
    case.validate()
    write_result(args.output, {"status": "running"})
    write_result(args.output, asyncio.run(suite(case)))


if __name__ == "__main__":
    main()
