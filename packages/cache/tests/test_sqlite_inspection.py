"""Real SQLite observations and binding-scoped administration, without shadow state."""

import asyncio
import json
import threading
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

import pytest

from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingSpace,
)
from semantix_cache.inspection import InspectionSort
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores._backends.sqlite.format import decode_payload
from semantix_cache.stores._backends.sqlite.worker import Job, Row
from semantix_cache.stores.sqlite import SQLiteStore

from . import sqlite_helpers
from .sqlite_helpers import connection, drain_workers, state
from .test_memory import entry

sqlite_store = sqlite_helpers.sqlite_store


@pytest.mark.parametrize(
    "response", ["answer", "\u00e9\U0001f642" * 121, " " * 240 + "answer"]
)
async def test_detached_scoped_readonly_observation(
    sqlite_store: SQLiteStore, response: str
) -> None:
    value = entry("private prompt", namespace="alpha").model_copy(
        update={"response": response}
    )
    await sqlite_store.put(value)
    await sqlite_store.put(entry("foreign", namespace="beta"))
    found = await sqlite_store.find_nearest((1, 0), namespace="alpha")
    assert found is not None
    assert await sqlite_store.record_hit(
        value.cache_key, namespace="alpha", expected_created_at=found.entry.created_at
    )
    before = state(sqlite_store._config.path)
    for _ in range(2):
        page = await sqlite_store.inspect_entries(namespace="alpha")
        assert page.total == 1
        assert not page.has_more
        observed = page.items[0]
        assert observed.response is None
        assert observed.response_preview == response[:240]
        assert observed.response_preview_truncated == (len(response) > 240)
        assert observed.hit_count == observed.recency_rank == 1
        assert observed.last_accessed_at is not None
        assert observed.created_at == found.entry.created_at
        assert observed.remaining_ttl_seconds is None
        assert "embedding" not in observed.model_dump()
        detail = await sqlite_store.inspect_entry(
            value.cache_key, namespaces=("alpha",)
        )
        assert detail is not None
        assert detail.response == response
        for scope in ((), ("beta",)):
            assert (
                await sqlite_store.inspect_entry(value.cache_key, namespaces=scope)
                is None
            )
        assert await sqlite_store.inspect_entry("0" * 64, namespaces=None) is None
    assert state(sqlite_store._config.path) == before
    await sqlite_store.clear_all()
    assert observed.prompt == value.prompt
    assert observed.hit_count == 1


@pytest.mark.parametrize("sort", ["oldest", "newest", "most_hit", "nearest_expiry"])
async def test_order_pages_and_scoped_recency(
    sqlite_store: SQLiteStore, sort: InspectionSort, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index, ttl in enumerate((100.0, 50.0, None)):
        await sqlite_store.put(
            entry(f"needle {index}", namespace="alpha"), ttl_seconds=ttl
        )
    await sqlite_store.put(entry("foreign", namespace="beta"))
    old = (await sqlite_store.inspect_entries(namespace="alpha", sort="oldest")).items[
        0
    ]
    assert await sqlite_store.record_hit(
        old.cache_key, namespace="alpha", expected_created_at=old.created_at
    )
    observed_at = database.now_us()
    monkeypatch.setattr(database, "now_us", lambda: observed_at)
    before = state(sqlite_store._config.path)
    expected = {
        "oldest": [0, 1, 2],
        "newest": [2, 1, 0],
        "most_hit": [0, 2, 1],
        "nearest_expiry": [1, 0, 2],
    }[sort]
    full = await sqlite_store.inspect_entries(namespace="alpha", sort=sort)
    assert [x.prompt for x in full.items] == [f"needle {i}" for i in expected]
    assert {x.prompt: x.recency_rank for x in full.items} == {
        "needle 0": 1,
        "needle 1": 3,
        "needle 2": 2,
    }
    for offset in range(5):
        page = await sqlite_store.inspect_entries(
            namespace="alpha", sort=sort, offset=offset, limit=1
        )
        assert page.total == 3
        assert page.items == full.items[offset : offset + 1]
        assert page.has_more == (offset < 2)
    searched = await sqlite_store.inspect_entries(
        namespace="alpha", search=" NEEDLE 1 ", sort=sort
    )
    assert searched.total == 1
    assert searched.items[0].recency_rank == 3
    assert searched.items[0].remaining_ttl_seconds is not None
    assert state(sqlite_store._config.path) == before


@pytest.mark.parametrize("sort", ["oldest", "newest", "most_hit", "nearest_expiry"])
async def test_primary_ties_use_cache_key(
    sqlite_store: SQLiteStore, sort: InspectionSort
) -> None:
    values = [entry(text) for text in ("one", "two", "three")]
    for value in values:
        await sqlite_store.put(value)
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET revision_us=(SELECT min(revision_us) FROM cache_entries)"
        )
    page = await sqlite_store.inspect_entries(sort=sort)
    assert [x.cache_key for x in page.items] == sorted(
        value.cache_key for value in values
    )


async def test_unicode_search_max_page_and_expiry(sqlite_store: SQLiteStore) -> None:
    for index in range(105):
        await sqlite_store.put(entry(f"Stra\u00dfe {index:03}", namespace="alpha"))
    dead = entry("expired Stra\u00dfe", namespace="alpha")
    await sqlite_store.put(dead)
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET expires_at_us=1 WHERE cache_key=?",
            (dead.cache_key,),
        )
    before = state(sqlite_store._config.path)
    first = await sqlite_store.inspect_entries(
        namespace="alpha", search=" STRASSE ", limit=100
    )
    tail = await sqlite_store.inspect_entries(
        namespace="alpha", search="strasse", offset=102, limit=2
    )
    assert first.total == tail.total == 105
    assert len(first.items) == 100
    assert first.has_more
    assert len(tail.items) == 2
    assert tail.has_more
    assert not (await sqlite_store.inspect_entries(search="missing")).items
    assert (await sqlite_store.inspect_entries(search=" \t ", limit=1)).total == 105
    assert await sqlite_store.inspect_entry(dead.cache_key, namespaces=None) is None
    assert state(sqlite_store._config.path) == before


async def test_payload_projection_and_corruption(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = entry("old corrupt", namespace="alpha")
    await sqlite_store.put(old)
    new = entry("new valid", namespace="alpha")
    await sqlite_store.put(new)
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_payloads SET payload_blob=? WHERE cache_key=?",
            (b"{}", old.cache_key),
        )
    decoded: list[str] = []
    original = decode_payload

    def decode(payload: bytes, key: str, namespace: str) -> dict[str, str]:
        decoded.append(key)
        return original(payload, key, namespace)

    def no_vector(*args: object, **kwargs: object) -> object:
        raise AssertionError("Inspection decoded a vector")

    monkeypatch.setattr(database, "decode_payload", decode)
    monkeypatch.setattr(database, "decode_vector", no_vector)
    page = await sqlite_store.inspect_entries(limit=1)
    assert page.total == 2
    assert decoded == [new.cache_key]
    assert await sqlite_store.inspect_entry(old.cache_key, namespaces=("beta",)) is None
    assert decoded == [new.cache_key]
    assert (await sqlite_store.inspect_entries(offset=99)).total == 2
    assert decoded == [new.cache_key]
    for operation in (
        sqlite_store.inspect_entries(limit=2),
        sqlite_store.inspect_entries(search="valid"),
        sqlite_store.inspect_entry(old.cache_key, namespaces=None),
    ):
        with pytest.raises(CacheStoreError) as caught:
            await operation
        assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "payload", [b"[]", b'{"x":1,"x":2}', b'{"cache_key":null}', b"\xff", b'"text"']
)
async def test_malformed_payload_is_not_a_miss(
    sqlite_store: SQLiteStore, payload: bytes
) -> None:
    value = entry("malformed")
    await sqlite_store.put(value)
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_payloads SET payload_blob=? WHERE cache_key=?",
            (payload, value.cache_key),
        )
    with pytest.raises(CacheStoreError):
        await sqlite_store.inspect_entries()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit", True),
        ("limit", 101),
        ("offset", -1),
        ("namespace", "bad|scope"),
        ("search", 42),
        ("search", "x" * 2001),
        ("sort", "bad"),
    ],
)
async def test_invalid_list_arguments(
    sqlite_store: SQLiteStore, field: str, value: object
) -> None:
    options = {field: value}
    with pytest.raises(CacheValidationError):
        await sqlite_store.inspect_entries(
            namespace=cast(str | None, options.get("namespace")),
            offset=cast(int, options.get("offset", 0)),
            limit=cast(int, options.get("limit", 20)),
            search=cast(str | None, options.get("search")),
            sort=cast(InspectionSort, options.get("sort", "newest")),
        )


@pytest.mark.parametrize(
    ("key", "scope"), [("bad", None), ("0" * 64, "alpha"), ("0" * 64, ("bad|scope",))]
)
async def test_invalid_detail_arguments(
    sqlite_store: SQLiteStore, key: str, scope: object
) -> None:
    with pytest.raises(CacheValidationError):
        await sqlite_store.inspect_entry(
            key, namespaces=cast(tuple[str, ...] | None, scope)
        )


async def test_binding_clear_preserves_other_state(sqlite_store: SQLiteStore) -> None:
    path = sqlite_store._config.path
    other_space = EmbeddingSpace(identity="other-inspection", dimensions=2)
    await SQLiteStore.initialize_schema(
        path, embedding_space=other_space, default_ttl_seconds=None
    )
    async with await SQLiteStore.connect(
        path, embedding_space=other_space, default_ttl_seconds=None
    ) as other:
        value = entry("shared key", namespace="alpha")
        await sqlite_store.put(value)
        await sqlite_store.put(entry("second", namespace="beta"))
        await other.put(value.model_copy(update={"response": "other binding"}))
        observed = await sqlite_store.inspect_entry(value.cache_key, namespaces=None)
        assert observed is not None
        before = state(path)
        assert await sqlite_store.clear_all() == 2
        after = state(path)
        assert after[0] == before[0]
        assert (await sqlite_store.inspect_entries()).total == 0
        detail = await other.inspect_entry(value.cache_key, namespaces=None)
        assert detail is not None
        assert detail.response == "other binding"
        assert await sqlite_store.clear_all() == 0
        await sqlite_store.put(value)
        new = await sqlite_store.inspect_entry(value.cache_key, namespaces=None)
        assert new is not None
        assert new.created_at > observed.created_at
        assert not await sqlite_store.record_hit(
            value.cache_key, namespace="alpha", expected_created_at=observed.created_at
        )
    await sqlite_store.aclose()
    for operation in (
        sqlite_store.inspect_entries(),
        sqlite_store.inspect_entry(value.cache_key, namespaces=None),
        sqlite_store.clear_all(),
    ):
        with pytest.raises(CacheClosedError):
            await operation


async def test_clear_failure_rolls_back(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("atomic", namespace="alpha"))
    before = state(sqlite_store._config.path)
    original = Job.rows

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = original(job, sql, parameters)
        if sql == "DELETE FROM cache_entries WHERE binding_id=?":
            raise OSError("private injected write failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        with pytest.raises(CacheStoreError) as caught:
            await sqlite_store.clear_all()
    assert "private" not in str(caught.value)
    assert state(sqlite_store._config.path) == before


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_interrupted_scan_keeps_worker_owned(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    await sqlite_store.put(entry("scan"))
    before = state(sqlite_store._config.path)
    original = decode_payload
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def decode(payload: bytes, key: str, namespace: str) -> dict[str, str]:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Scan test was not released")
        return original(payload, key, namespace)

    if stop == "timeout":
        sqlite_store._worker.config = replace(sqlite_store._worker.config, timeout=0.05)
    with monkeypatch.context() as patch:
        patch.setattr(database, "decode_payload", decode)
        task = asyncio.create_task(sqlite_store.inspect_entries(search="scan"))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if stop == "cancel":
                task.cancel()
            with pytest.raises(
                asyncio.CancelledError if stop == "cancel" else CacheTimeoutError
            ):
                await asyncio.wait_for(task, 2)
            with pytest.raises(CacheBusyError):
                await sqlite_store.aclose()
        finally:
            release.set()
            await drain_workers(sqlite_store)
    assert state(sqlite_store._config.path) == before
    assert (await sqlite_store.inspect_entries()).total == 1


async def test_read_snapshot_survives_concurrent_replacement(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = entry("snapshot")
    await sqlite_store.put(value)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = database.Database._inspection_metadata

    def metadata(
        active: database.Database,
        job: Job,
        binding: int,
        observed: int,
        namespace: str | None = None,
    ) -> list[Row]:
        result = original(active, job, binding, observed, namespace)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Snapshot test was not released")
        return result

    async with await SQLiteStore.connect(
        sqlite_store._config.path,
        embedding_space=sqlite_store.embedding_space,
        default_ttl_seconds=None,
    ) as other:
        with monkeypatch.context() as patch:
            patch.setattr(database.Database, "_inspection_metadata", metadata)
            task = asyncio.create_task(sqlite_store.inspect_entries())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                await asyncio.wait_for(
                    other.put(value.model_copy(update={"response": "replacement"})), 2
                )
            finally:
                release.set()
            page = await asyncio.wait_for(task, 5)
        assert page.items[0].response_preview == value.response
        detail = await sqlite_store.inspect_entry(value.cache_key, namespaces=None)
        assert detail is not None
        assert detail.response == "replacement"


@pytest.mark.parametrize(
    "change", ["canonical", "prompt", "key", "namespace", "empty", "type", "extra"]
)
async def test_invalid_payload_invariants(
    sqlite_store: SQLiteStore, change: str
) -> None:
    value = entry("valid prompt", namespace="alpha")
    await sqlite_store.put(value)
    with connection(sqlite_store._config.path) as native:
        raw = native.execute("SELECT payload_blob FROM cache_payloads").fetchone()[0]
        payload = json.loads(raw)
        if change == "canonical":
            payload["prompt"] = " valid prompt "
        elif change == "prompt":
            payload["prompt"] = "another prompt"
        elif change == "key":
            payload["cache_key"] = "0" * 64
        elif change == "namespace":
            payload["namespace"] = "beta"
        elif change == "empty":
            payload["response"] = ""
        elif change == "type":
            payload["response"] = 1
        else:
            payload["extra"] = "forbidden"
        native.execute(
            "UPDATE cache_payloads SET payload_blob = ?",
            (json.dumps(payload).encode("ascii"),),
        )
    before = state(sqlite_store._config.path)
    with pytest.raises(CacheStoreError):
        await sqlite_store.inspect_entries()
    with pytest.raises(CacheStoreError):
        await sqlite_store.inspect_entry(value.cache_key, namespaces=("alpha",))
    assert state(sqlite_store._config.path) == before


async def test_clear_cancel_before_commit_rolls_back(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("cancel clear"))
    before = state(sqlite_store._config.path)
    original = Job.rows
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = original(job, sql, parameters)
        if sql == "DELETE FROM cache_entries WHERE binding_id=?":
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("Clear barrier was not released")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        task = asyncio.create_task(sqlite_store.clear_all())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(CacheBusyError):
                await sqlite_store.aclose()
        finally:
            release.set()
            await drain_workers(sqlite_store)
    assert state(sqlite_store._config.path) == before
    assert await sqlite_store.clear_all() == 1


async def test_clear_removes_expired_without_counting_it(
    sqlite_store: SQLiteStore,
) -> None:
    live = entry("live", namespace="alpha")
    expired = entry("expired", namespace="beta")
    await sqlite_store.put(live)
    await sqlite_store.put(expired)
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET expires_at_us=1 WHERE cache_key=?",
            (expired.cache_key,),
        )
    assert await sqlite_store.clear_all() == 1
    _, rows, payloads = state(sqlite_store._config.path)
    assert rows == []
    assert payloads == []
