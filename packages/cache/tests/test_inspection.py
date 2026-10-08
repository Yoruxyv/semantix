"""Optional observations over real stores; no parallel authoritative metadata."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import asyncpg
import pytest
from asyncpg.pool import PoolConnectionProxy
from pydantic import ValidationError

from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingSpace,
    MemoryStore,
)
from semantix_cache.inspection import InspectionEntry, InspectionSort
from semantix_cache.stores.pgvector import PgVectorStore
from semantix_cache.stores.redis import _INSPECT, RedisStore, _micros

from . import test_pgvector as pg_tests
from . import test_redis as redis_tests
from .test_memory import entry
from .test_redis import client

pg_store = pg_tests.pg_store
redis_client = redis_tests.redis_client
redis_store = redis_tests.redis_store

Store = MemoryStore | PgVectorStore | RedisStore
SPACE = EmbeddingSpace(identity="inspection-tests", dimensions=2)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("pgvector", marks=pytest.mark.pgvector),
        pytest.param("redis", marks=pytest.mark.redis),
    ]
)
async def inspected(
    request: pytest.FixtureRequest, pg_pool: asyncpg.Pool | None
) -> AsyncIterator[Store]:
    if request.param == "memory":
        store = MemoryStore(embedding_space=SPACE, default_ttl_seconds=None)
        try:
            yield store
        finally:
            await store.aclose()
    elif request.param == "pgvector":
        if pg_pool is None:
            pytest.skip("Disposable PostgreSQL required")
        schema = "cache_test_" + uuid4().hex
        pg = PgVectorStore(
            pool=pg_pool, embedding_space=SPACE, schema=schema, default_ttl_seconds=None
        )
        try:
            await pg.initialize_schema(migration_pool=pg_pool)
            yield pg
        finally:
            await pg.aclose()
            assert schema.startswith("cache_test_")
            assert len(schema) == 43
            await pg_pool.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    else:
        url = os.environ.get("REDIS_TEST_URL")
        if not url:
            pytest.skip("Disposable Redis required")
        active = client(url)
        redis = RedisStore(
            client=active,
            embedding_space=SPACE,
            key_prefix="inspect_test_" + uuid4().hex,
            default_ttl_seconds=None,
        )
        try:
            await redis.initialize_schema(initialization_client=active)
            yield redis
        finally:
            await redis.aclose()
            await active.delete(*redis._config.keys)
            await active.aclose(close_connection_pool=True)


async def snapshot(store: Store) -> object:
    if isinstance(store, MemoryStore):
        return (
            tuple(store._items.items()),
            tuple((k, id(v)) for k, v in store._snapshots.items()),
            store._last_revision,
            store.inspection_events,
        )
    if isinstance(store, PgVectorStore):
        return [
            await store._pool.fetch(
                " ".join(
                    (
                        "SELECT row_to_json(t)::text AS data FROM",
                        store._config.relation(name),
                        "t ORDER BY data",
                    )
                )
            )
            for name in ("cache_entries", "binding_state", "schema_migrations")
        ]
    return (
        await store._client.hgetall(store._config.keys[0]),
        await store._client.hgetall(store._config.keys[1]),
        await store._client.zrange(store._config.keys[2], 0, -1, withscores=True),
    )


@pytest.mark.parametrize(
    "response", ["small answer", "é🙂" * 121 + "private-tail", " " * 240 + "answer"]
)
async def test_metadata_scope_preview_and_repeated_readonly(
    inspected: Store, response: str
) -> None:
    original = entry("private prompt", namespace="alpha").model_copy(
        update={"response": response}
    )
    await inspected.put(original)
    hit = await inspected.find_nearest((1, 0), namespace="alpha")
    assert hit is not None
    assert await inspected.record_hit(
        original.cache_key, namespace="alpha", expected_created_at=hit.entry.created_at
    )
    await inspected.put(entry("foreign", namespace="beta"))
    before = await snapshot(inspected)
    for _ in range(2):
        page = await inspected.inspect_entries(namespace="alpha")
        assert page.total == 1
        assert not page.has_more
        metadata = page.items[0]
        assert metadata.created_at == hit.entry.created_at
        assert metadata.prompt == original.prompt
        assert metadata.cache_key == original.cache_key
        assert metadata.response_preview == response[:240]
        assert metadata.response_preview_truncated == (len(response) > 240)
        assert metadata.response is None
        assert metadata.hit_count == 1
        assert metadata.last_accessed_at is not None
        assert metadata.recency_rank == 1
        assert metadata.is_expired is False
        assert metadata.expires_at is None
        assert metadata.remaining_ttl_seconds is None
        assert "embedding" not in metadata.model_dump()
        assert "private-tail" not in page.model_dump_json()
        assert original.prompt not in repr(metadata)
        assert original.cache_key not in repr(metadata)
        detail = await inspected.inspect_entry(
            original.cache_key, namespaces=("alpha",)
        )
        assert detail is not None
        assert detail.response == response
        for scope in ((), ("beta",)):
            assert (
                await inspected.inspect_entry(original.cache_key, namespaces=scope)
                is None
            )
        assert await inspected.inspect_entry("0" * 64, namespaces=None) is None
    assert await snapshot(inspected) == before
    with pytest.raises(ValidationError):
        InspectionEntry.model_validate(
            {**metadata.model_dump(), "response_preview": "x" * 241}
        )


@pytest.mark.parametrize("sort", ["newest", "oldest", "most_hit", "nearest_expiry"])
async def test_sorted_pagination_and_search(
    inspected: Store, sort: InspectionSort
) -> None:
    now = datetime.now(UTC)
    for index, ttl in enumerate((100.0, 50.0, None)):
        item = entry(
            f"needle {index}",
            namespace="alpha",
            created_at=now + timedelta(microseconds=index),
        )
        await inspected.put(item, ttl_seconds=ttl)
    await inspected.put(entry("foreign", namespace="beta"))
    first = await inspected.inspect_entries(namespace="alpha", sort="oldest", limit=1)
    assert await inspected.record_hit(
        first.items[0].cache_key,
        namespace="alpha",
        expected_created_at=first.items[0].created_at,
    )
    before = await snapshot(inspected)
    full = await inspected.inspect_entries(namespace="alpha", sort=sort)
    expected = {
        "oldest": [0, 1, 2],
        "newest": [2, 1, 0],
        "most_hit": [0, 2, 1],
        "nearest_expiry": [1, 0, 2],
    }[sort]
    assert [x.prompt for x in full.items] == [f"needle {i}" for i in expected]
    pages = [
        await inspected.inspect_entries(namespace="alpha", sort=sort, offset=i, limit=1)
        for i in range(4)
    ]
    assert [p.items[0].cache_key for p in pages[:3]] == [
        x.cache_key for x in full.items
    ]
    assert [p.has_more for p in pages] == [True, True, False, False]
    assert pages[3].items == ()
    assert pages[3].total == 3
    search = await inspected.inspect_entries(
        namespace="alpha", search=" NEEDLE 1 ", sort=sort
    )
    assert search.total == 1
    assert search.items[0].prompt == "needle 1"
    assert (await inspected.inspect_entries(search="absent")).total == 0
    assert await snapshot(inspected) == before


async def test_maximum_page_and_incremental_search(inspected: Store) -> None:
    for index in range(105):
        await inspected.put(entry(f"batch {index:03}"))
    first = await inspected.inspect_entries(limit=100)
    second = await inspected.inspect_entries(limit=100, offset=100)
    assert len(first.items) == 100
    assert first.has_more
    assert len(second.items) == 5
    assert not second.has_more
    assert len({x.cache_key for x in (*first.items, *second.items)}) == 105
    search = await inspected.inspect_entries(search=" batch ", offset=102, limit=2)
    assert search.total == 105
    assert len(search.items) == 2
    assert search.has_more
    assert [x.cache_key for x in search.items] == [
        x.cache_key for x in second.items[2:4]
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit", 0),
        ("limit", 101),
        ("limit", True),
        ("offset", -1),
        ("offset", False),
        ("namespace", "bad|scope"),
        ("search", 42),
        ("search", "x" * 2001),
        ("sort", []),
        ("sort", "unknown"),
    ],
)
async def test_invalid_inspection_inputs(
    inspected: Store, field: str, value: object
) -> None:
    options = {field: value}
    with pytest.raises(CacheValidationError):
        await inspected.inspect_entries(
            namespace=cast(str | None, options.get("namespace")),
            offset=cast(int, options.get("offset", 0)),
            limit=cast(int, options.get("limit", 20)),
            search=cast(str | None, options.get("search")),
            sort=cast(InspectionSort, options.get("sort", "newest")),
        )


@pytest.mark.parametrize(
    ("key", "scope"), [("bad", None), ("0" * 64, ("bad|scope",)), ("0" * 64, "alpha")]
)
async def test_invalid_detail_inputs(inspected: Store, key: str, scope: object) -> None:
    with pytest.raises(CacheValidationError):
        await inspected.inspect_entry(
            key, namespaces=cast(tuple[str, ...] | None, scope)
        )


async def test_expired_exclusion_without_purging(
    inspected: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = entry("expired")
    await inspected.put(original)
    if isinstance(inspected, MemoryStore):
        old = inspected._items[original.cache_key]
        inspected._items[original.cache_key] = replace(
            old, expires_monotonic=1.0, expires_at=datetime(2000, 1, 1, tzinfo=UTC)
        )
        monkeypatch.setattr("semantix_cache.memory.monotonic", lambda: 2.0)
    elif isinstance(inspected, PgVectorStore):
        await inspected._pool.execute(
            " ".join(
                (
                    "UPDATE",
                    inspected._config.relation("cache_entries"),
                    "SET expires_at=$1",
                )
            ),
            datetime(2000, 1, 1, tzinfo=UTC),
        )
    else:
        await inspected._client.hset(
            inspected._config.keys[1],
            "default|" + original.cache_key + ":e",
            _micros(datetime(2000, 1, 1, tzinfo=UTC)),
        )
    before = await snapshot(inspected)
    assert (await inspected.inspect_entries()).total == 0
    assert await inspected.inspect_entry(original.cache_key, namespaces=None) is None
    assert await snapshot(inspected) == before
    # Normal cache operations still apply their original expiry behavior.
    assert await inspected.find_nearest((1, 0), namespace="default") is None


async def test_native_ttl_and_clear_all_are_separate_mutations(
    inspected: Store,
) -> None:
    await inspected.put(entry("short", namespace="alpha"), ttl_seconds=0.2)
    await inspected.put(entry("live", namespace="beta"))
    before = await inspected.inspect_entries(namespace="alpha")
    assert before.items[0].remaining_ttl_seconds is not None
    await asyncio.sleep(0.25)
    assert (await inspected.inspect_entries(namespace="alpha")).total == 0
    assert (await inspected.inspect_entries(namespace="beta")).total == 1
    assert await inspected.clear_all() == 1
    assert (await inspected.inspect_entries()).total == 0
    assert await inspected.clear_all() == 0
    await inspected.put(entry("after clear"))
    assert (await inspected.inspect_entries()).total == 1
    await inspected.aclose()
    with pytest.raises(CacheClosedError):
        await inspected.inspect_entries()
    with pytest.raises(CacheClosedError):
        await inspected.inspect_entry("0" * 64, namespaces=None)
    with pytest.raises(CacheClosedError):
        await inspected.clear_all()


@pytest.mark.redis
async def test_redis_small_page_does_not_decode_unselected_payloads() -> None:
    url = os.environ.get("REDIS_TEST_URL")
    if not url:
        pytest.skip("Disposable Redis required")
    active = client(url)
    store = RedisStore(
        client=active,
        embedding_space=SPACE,
        key_prefix="inspect_test_" + uuid4().hex,
        default_ttl_seconds=None,
    )
    try:
        await store.initialize_schema(initialization_client=active)
        old = entry("old corrupted payload")
        await store.put(old)
        await store.put(entry("new valid payload"))
        await active.hset(
            store._config.keys[1], "default|" + old.cache_key + ":p", "invalid JSON"
        )
        assert (await store.inspect_entries(limit=1)).items[
            0
        ].prompt == "new valid payload"
        with pytest.raises(CacheStoreError):
            await store.inspect_entries(limit=2)
        with pytest.raises(CacheStoreError):
            await store.inspect_entries(search="valid")
    finally:
        await store.aclose()
        await active.delete(*store._config.keys)
        assert await active.ping()  # borrowed owner is still usable
        await active.aclose(close_connection_pool=True)


@pytest.mark.pgvector
async def test_pg_plan_limits_payload_projection(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspected = pg_store
    for index in range(12):
        await inspected.put(
            entry(f"plan {index}").model_copy(
                update={"response": "large answer " * 7000}
            )
        )
    plans: list[str] = []
    fetch = PoolConnectionProxy.fetch

    async def traced(
        connection: PoolConnectionProxy[asyncpg.Record],
        query: str,
        *args: object,
    ) -> list[asyncpg.Record]:
        if query.startswith("WITH eligible"):
            rows = await fetch(
                connection, "EXPLAIN (ANALYZE, VERBOSE, FORMAT JSON) " + query, *args
            )
            plans.append(str(rows[0][0]))
        return await fetch(connection, query, *args)

    monkeypatch.setattr(PoolConnectionProxy, "fetch", traced)
    page = await inspected.inspect_entries(limit=2)
    assert len(page.items) == 2
    assert len(plans) == 1
    plan = cast(list[dict[str, object]], json.loads(plans[0]))[0]["Plan"]

    def nodes(node: object) -> list[dict[str, object]]:
        current = cast(dict[str, object], node)
        return [
            current,
            *(
                child
                for part in cast(list[object], current.get("Plans", []))
                for child in nodes(part)
            ),
        ]

    all_nodes = nodes(plan)
    eligible = next(n for n in all_nodes if n.get("Subplan Name") == "CTE eligible")
    assert all("response" not in str(v) for v in cast(list[object], eligible["Output"]))
    assert all(
        not str(v).endswith(".embedding")
        for v in cast(list[object], eligible["Output"])
    )
    bounded = next(n for n in all_nodes if n.get("Subplan Name") == "CTE page")
    assert bounded["Node Type"] == "Limit"
    assert bounded["Actual Rows"] == 2
    assert bounded["Actual Loops"] == 1


@pytest.mark.redis
async def test_redis_inspection_deadline_and_cancellation(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspected = redis_store
    before = await snapshot(inspected)
    started = asyncio.Event()
    resume = asyncio.Event()

    async def blocked(*args: object, **kwargs: object) -> object:
        started.set()
        await resume.wait()
        return [0, []]

    monkeypatch.setattr(inspected._client, "eval_ro", blocked)
    inspected._config = replace(inspected._config, timeout=0.02)
    with pytest.raises(CacheTimeoutError):
        await inspected.inspect_entries(search="query")
    started.clear()
    task = asyncio.create_task(inspected.inspect_entries())
    await started.wait()
    await asyncio.sleep(0)
    with pytest.raises(CacheBusyError):
        await inspected.aclose()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await snapshot(inspected) == before


@pytest.mark.redis
@pytest.mark.parametrize(
    "malformation",
    [
        "shape",
        "count",
        "oversized",
        "scope",
        "full_response",
        "flag",
        "expired",
        "invalid_utf8",
        "invalid_timestamp",
        "root_length",
        "count_type",
        "rows_type",
        "row_type",
        "field_type",
        "field_count",
    ],
)
async def test_redis_inspection_rejects_invalid_projections(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch, malformation: str
) -> None:
    inspected = redis_store
    await inspected.put(entry("projection", namespace="alpha"))
    valid = cast(
        list[object],
        await inspected._client.eval_ro(
            _INSPECT,
            3,
            *inspected._config.keys,
            *inspected._config.descriptor,
            "alpha",
            "",
            "null",
            0,
            1,
            "newest",
        ),
    )
    records = cast(list[list[bytes]], valid[1])
    raw: object = valid
    if malformation in {"shape", "root_length"}:
        raw = {"shape": None, "root_length": [1]}[malformation]
    elif malformation == "count":
        valid[0] = -1
    elif malformation == "oversized":
        valid[1] = records * 2
    elif malformation == "scope":
        records[0][0] = b"beta|" + b"0" * 64
    elif malformation == "full_response":
        records[0][2] = b"must not escape"
    elif malformation == "flag":
        records[0][10] = b"unexpected"
    elif malformation == "expired":
        records[0][5] = b"1"
    elif malformation == "invalid_utf8":
        records[0][3] = b"\xff"
    elif malformation == "invalid_timestamp":
        records[0][4] = b"9" * 300
    elif malformation == "count_type":
        valid[0] = b"1"
    elif malformation == "rows_type":
        valid[1] = None
    elif malformation == "row_type":
        valid[1] = [None]
    elif malformation == "field_type":
        valid[1] = [[None] * 11]
    else:
        valid[1] = [[b"x"] * 10]

    async def injected(*args: object, **kwargs: object) -> object:
        return raw

    monkeypatch.setattr(inspected._client, "eval_ro", injected)
    with pytest.raises(CacheStoreError, match="Invalid Redis inspection metadata"):
        await inspected.inspect_entries(namespace="alpha", limit=1)


@pytest.mark.pgvector
async def test_pg_invalid_inspection_metadata_is_sanitized(
    pg_store: PgVectorStore,
) -> None:
    original = entry("valid prompt")
    await pg_store.put(original)
    relation = pg_store._config.relation("cache_entries")
    await pg_store._pool.execute(" ".join(("UPDATE", relation, "SET prompt=$1")), " ")
    before = await snapshot(pg_store)
    with pytest.raises(
        CacheStoreError, match="Invalid PostgreSQL inspection metadata"
    ) as failure:
        await pg_store.inspect_entries()
    assert original.cache_key not in str(failure.value)
    assert await snapshot(pg_store) == before


@pytest.mark.pgvector
async def test_pg_inspection_and_clear_respect_embedding_binding(
    pg_store: PgVectorStore,
) -> None:
    other = PgVectorStore(
        pool=pg_store._pool,
        embedding_space=EmbeddingSpace(identity="other-space", dimensions=2),
        schema=pg_store._config.schema,
    )
    try:
        await pg_store.put(entry("shared prompt"))
        await other.put(entry("foreign binding"))
        assert (await pg_store.inspect_entries()).total == 1
        assert (
            await pg_store.inspect_entry(
                entry("foreign binding").cache_key, namespaces=None
            )
            is None
        )
        assert await pg_store.clear_all() == 1
        assert (await other.inspect_entries()).total == 1
    finally:
        await other.aclose()
        assert not pg_store._pool.is_closing()
