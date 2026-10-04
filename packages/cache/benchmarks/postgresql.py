"""Profile read-only PostgreSQL search components, without changing store behavior.

The current captured statement remains the reference. Narrow distance/serialization
queries isolate server-side work; they omit candidate payload validation and atomic
hit confirmation and are diagnostic controls, not replacement store APIs. One pooled
connection is held during timing, so these numbers exclude pool acquisition/reset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from .common import Case, Dataset, environment, now_ns, rss_bytes, summary, write_result
from .runtime import DatabaseProbe, make_store


async def suite(case: Case, iterations: int) -> dict[str, Any]:
    data = Dataset(case)
    probe = DatabaseProbe()
    metrics: dict[str, Any] = {}
    plans: dict[str, Any] = {}
    async with make_store(case, data, probe) as (store, pool, database):
        for index in range(case.cache_size):
            await store.put(data.entry(index))
        await store.find_nearest(data.vectors[0], namespace="benchmark")
        await asyncio.sleep(0)
        if probe.search_statement is None or pool is None:
            raise RuntimeError("Actual PostgreSQL search statement was not captured")
        current_sql, args = probe.search_statement
        async with pool.acquire() as connection:
            layout = await cast(Any, store)._layout(connection, require_schema=True)
            # Store layout identifiers/operators are validated and quoted by _layout.
            # All workload values remain bound parameters; no user SQL is interpolated.
            eligible = f"""
                WITH eligible AS MATERIALIZED (
                    SELECT embedding, cache_key, created_at FROM {layout["entries"]}
                    WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3
                      AND (expires_at IS NULL OR expires_at>clock_timestamp())
                )
            """  # noqa: S608 -- validated store-owned identifiers
            distance = f"embedding {layout['cosine']} $4::{layout['vector']}"
            statements = {
                "current_captured_search": (current_sql, args),
                "distance_and_key_top1": (
                    eligible  # noqa: S608 -- validated identifiers and bound values
                    + f"SELECT cache_key, 1-({distance}) AS score FROM eligible ORDER BY {distance}, created_at, cache_key LIMIT 1",  # noqa: S608 -- validated identifiers
                    args,
                ),
                "cosine_scan_only": (
                    eligible + f"SELECT max(1-({distance})) AS score FROM eligible",  # noqa: S608 -- validated identifiers
                    args,
                ),
                "candidate_text_serialization_only": (
                    eligible  # noqa: S608 -- validated identifiers and bound values
                    + "SELECT sum(octet_length(embedding::text)) AS bytes FROM eligible",
                    args[:3],
                ),
            }
            prepared = await connection.prepare(current_sql)
            parameter_types = [
                {"name": value.name, "schema": value.schema, "oid": value.oid}
                for value in prepared.get_parameters()
            ]
            reference = await connection.fetchrow(current_sql, *args)
            if reference is None or reference["cache_key"] != data.entry(0).cache_key:
                raise RuntimeError("Reference search selected an unexpected candidate")
            for name, (sql, parameters) in statements.items():
                await connection.fetchrow(sql, *parameters)
                samples = []
                began = perf_counter()
                value = None
                for _ in range(iterations):
                    before = now_ns()
                    value = await connection.fetchrow(sql, *parameters)
                    samples.append(now_ns() - before)
                if value is None:
                    raise RuntimeError("Read-only component returned no row")
                value = dict(value)
                if "score" in value and abs(value["score"] - reference["score"]) > 1e-6:
                    raise RuntimeError("Distance control disagreed with reference")
                if (
                    "cache_key" in value
                    and value["cache_key"] != reference["cache_key"]
                ):
                    raise RuntimeError("Top1 control changed candidate identity")
                metrics[name] = summary(samples, perf_counter() - began)
                metrics[name]["result_bytes"] = value.get("bytes")
                raw = await connection.fetchval(
                    "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) " + sql,
                    *parameters,
                )
                plans[name] = json.loads(raw)
        if pool.get_idle_size() != pool.get_size():
            raise RuntimeError("Read-only component retained a pool connection")
    if any(
        task is not asyncio.current_task() and not task.done()
        for task in asyncio.all_tasks()
    ):
        raise RuntimeError("Read-only components retained background tasks")
    return {
        "schema_version": 1,
        "kind": "postgresql",
        "environment": environment(case),
        "dataset_sha256": data.digest,
        "database": database,
        "iterations": iterations,
        "metrics": metrics,
        "plans": plans,
        "parameter_types": parameter_types,
        "rss": rss_bytes(),
        "scope": "read-only SQL components on one held pooled connection; no facade/pool/reset/confirmation costs; not optimized runtime implementations",
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
    if case.store != "pgvector" or not case.diagnostics or not args.disposable_database:
        parser.error(
            "Use diagnostic pgvector cases and an acknowledged disposable database"
        )
    write_result(args.output, {"status": "running"})
    write_result(args.output, asyncio.run(suite(case, 20)))


if __name__ == "__main__":
    main()
