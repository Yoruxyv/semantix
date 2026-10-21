"""Real MySQL snapshot inspection and binding-scoped administration."""

import asyncio
import threading
from collections.abc import Sequence

import pytest

from examples.store_conformance import StoreFactory
from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheStoreError,
    CacheTimeoutError,
    EmbeddingSpace,
)
from semantix_cache.inspection import InspectionSort
from semantix_cache.stores._backends.mysql import database, schema
from semantix_cache.stores._backends.mysql.format import decode_payload, micros
from semantix_cache.stores._backends.mysql.worker import Job, Row
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, options, store_factory
from .test_memory import entry
from .test_mysql import mysql_store
from .test_mysql_faults import until
from .test_mysql_lifecycle import retired
from .test_mysql_transactions import persisted

__all__ = ["mysql_store", "store_factory"]
pytestmark = pytest.mark.mysql


@pytest.mark.parametrize(
    "response",
    ["answer", "\u00e9\U0001f642" * 121, " " * 240 + "answer"],
    ids=["short", "unicode", "leading-whitespace"],
)
async def test_detached_scoped_readonly_observation(
    mysql_store: MySQLStore, response: str
) -> None:
    value = entry("private prompt", namespace="alpha").model_copy(
        update={"response": response}
    )
    await mysql_store.put(value)
    await mysql_store.put(entry("foreign", namespace="beta"))
    found = await mysql_store.find_nearest((1, 0), namespace="alpha")
    assert found is not None
    assert await mysql_store.record_hit(
        value.cache_key, namespace="alpha", expected_created_at=found.entry.created_at
    )
    name = mysql_store._config.database
    before = await asyncio.to_thread(persisted, name)
    for _ in range(2):
        page = await mysql_store.inspect_entries(namespace="alpha")
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
        detail = await mysql_store.inspect_entry(value.cache_key, namespaces=("alpha",))
        assert detail is not None
        assert detail.response == response
        for scope in ((), ("beta",)):
            assert (
                await mysql_store.inspect_entry(value.cache_key, namespaces=scope)
                is None
            )
        assert await mysql_store.inspect_entry("0" * 64, namespaces=None) is None
    assert await asyncio.to_thread(persisted, name) == before
    await mysql_store.clear_all()
    assert observed.prompt == value.prompt
    assert observed.hit_count == 1


@pytest.mark.parametrize("sort", ["oldest", "newest", "most_hit", "nearest_expiry"])
async def test_order_pages_and_scoped_recency(
    mysql_store: MySQLStore, sort: InspectionSort
) -> None:
    for index, ttl in enumerate((100.0, 50.0, None)):
        await mysql_store.put(
            entry(f"needle {index}", namespace="alpha"), ttl_seconds=ttl
        )
    await mysql_store.put(entry("foreign", namespace="beta"))
    old = (await mysql_store.inspect_entries(namespace="alpha", sort="oldest")).items[0]
    assert await mysql_store.record_hit(
        old.cache_key, namespace="alpha", expected_created_at=old.created_at
    )
    before = await asyncio.to_thread(persisted, mysql_store._config.database)
    expected = {
        "oldest": [0, 1, 2],
        "newest": [2, 1, 0],
        "most_hit": [0, 2, 1],
        "nearest_expiry": [1, 0, 2],
    }[sort]
    full = await mysql_store.inspect_entries(namespace="alpha", sort=sort)
    assert [x.prompt for x in full.items] == [f"needle {i}" for i in expected]
    assert {x.prompt: x.recency_rank for x in full.items} == {
        "needle 0": 1,
        "needle 1": 3,
        "needle 2": 2,
    }
    for offset in range(5):
        page = await mysql_store.inspect_entries(
            namespace="alpha", sort=sort, offset=offset, limit=1
        )
        assert page.total == 3
        assert [x.cache_key for x in page.items] == [
            x.cache_key for x in full.items[offset : offset + 1]
        ]
        assert page.has_more == (offset < 2)
    searched = await mysql_store.inspect_entries(
        namespace="alpha", search=" NEEDLE 1 ", sort=sort
    )
    assert searched.total == 1
    assert searched.items[0].recency_rank == 3
    assert searched.items[0].remaining_ttl_seconds is not None
    assert await asyncio.to_thread(persisted, mysql_store._config.database) == before


@pytest.mark.parametrize("sort", ["oldest", "newest", "most_hit", "nearest_expiry"])
async def test_primary_ties_use_cache_key(
    mysql_store: MySQLStore, sort: InspectionSort
) -> None:
    values = [entry(text) for text in ("one", "two", "three")]
    for value in values:
        await mysql_store.put(value)
    revision = min(x.created_at for x in (await mysql_store.inspect_entries()).items)
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_entries SET revision_us=%s",
        (micros(revision),),
        name=mysql_store._config.database,
    )
    page = await mysql_store.inspect_entries(sort=sort)
    assert [x.cache_key for x in page.items] == sorted(
        value.cache_key for value in values
    )


async def test_unicode_search_max_page_and_exact_expiry(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(105):
        await mysql_store.put(entry(f"Stra\u00dfe {index:03}", namespace="alpha"))
    dead = entry("expired Stra\u00dfe", namespace="alpha")
    await mysql_store.put(dead)
    observed = 1700000000000000
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_entries SET expires_at_us=%s WHERE cache_key=%s",
        (observed, dead.cache_key.encode("ascii")),
        name=mysql_store._config.database,
    )
    original = Job.rows
    clocks: list[int] = []

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        if sql == "SELECT " + schema.NOW:
            clocks.append(1)
            return [(observed,)]
        return original(job, sql, parameters)

    monkeypatch.setattr(Job, "rows", rows)
    before = await asyncio.to_thread(persisted, mysql_store._config.database)
    first = await mysql_store.inspect_entries(
        namespace="alpha", search=" STRASSE ", limit=100
    )
    tail = await mysql_store.inspect_entries(
        namespace="alpha", search="strasse", offset=102, limit=2
    )
    assert first.total == tail.total == 105
    assert len(first.items) == 100
    assert first.has_more
    assert len(tail.items) == 2
    assert tail.has_more
    assert not (await mysql_store.inspect_entries(search="missing")).items
    assert (await mysql_store.inspect_entries(search=" \t ", limit=1)).total == 105
    assert await mysql_store.inspect_entry(dead.cache_key, namespaces=None) is None
    assert len(clocks) == 5
    assert await asyncio.to_thread(persisted, mysql_store._config.database) == before


async def test_payload_projection_corruption_and_buffer_bound(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = entry("old corrupt", namespace="alpha")
    new = entry("new valid", namespace="alpha")
    await mysql_store.put(old)
    await mysql_store.put(new)
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_payloads SET payload_blob=%s WHERE cache_key=%s",
        (b"{}", old.cache_key.encode("ascii")),
        name=mysql_store._config.database,
    )
    decoded: list[str] = []
    original_decode, original_rows = decode_payload, Job.rows

    def decode(payload: bytes, key: str, namespace: str) -> dict[str, str]:
        decoded.append(key)
        return original_decode(payload, key, namespace)

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        assert "vector_blob" not in sql or "OCTET_LENGTH(e.vector_blob)" in sql
        result = original_rows(job, sql, parameters)
        if sql.startswith("SELECT payload_blob"):
            assert "binding_id=%s AND cache_key=%s" in sql
            assert len(result) <= 1
        return result

    def no_vector(*args: object, **kwargs: object) -> object:
        raise AssertionError("Inspection decoded a vector")

    monkeypatch.setattr(database, "decode_payload", decode)
    monkeypatch.setattr(database, "decode_vector", no_vector)
    monkeypatch.setattr(Job, "rows", rows)
    assert (await mysql_store.inspect_entries(limit=1)).total == 2
    assert decoded == [new.cache_key]
    assert await mysql_store.inspect_entry(old.cache_key, namespaces=("beta",)) is None
    assert (await mysql_store.inspect_entries(offset=99)).total == 2
    assert decoded == [new.cache_key]
    for operation in (
        mysql_store.inspect_entries(limit=2),
        mysql_store.inspect_entries(search="valid"),
        mysql_store.inspect_entry(old.cache_key, namespaces=None),
    ):
        with pytest.raises(CacheStoreError) as caught:
            await operation
        assert caught.value.__context__ is None
        assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "payload", [b"[]", b'{"x":1,"x":2}', b'{"cache_key":null}', b"\xff", b'"text"']
)
async def test_malformed_payload_is_not_a_miss(
    mysql_store: MySQLStore, payload: bytes
) -> None:
    value = entry("malformed")
    await mysql_store.put(value)
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_payloads SET payload_blob=%s WHERE cache_key=%s",
        (payload, value.cache_key.encode("ascii")),
        name=mysql_store._config.database,
    )
    with pytest.raises(CacheStoreError):
        await mysql_store.inspect_entry(value.cache_key, namespaces=None)


async def test_binding_clear_preserves_other_state(mysql_store: MySQLStore) -> None:
    name = mysql_store._config.database
    config = options(name) | {
        "embedding_space": EmbeddingSpace(identity="other-inspection", dimensions=2),
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    async with await MySQLStore.connect(**config) as other:
        value = entry("shared key", namespace="alpha")
        await mysql_store.put(value)
        await mysql_store.put(entry("second", namespace="beta"))
        await other.put(value.model_copy(update={"response": "other binding"}))
        observed = await mysql_store.inspect_entry(value.cache_key, namespaces=None)
        assert observed is not None
        other_before = await other.inspect_entries()
        assert other_before.total == 1
        before = await asyncio.to_thread(persisted, name)
        assert await mysql_store.clear_all() == 2
        after = await asyncio.to_thread(persisted, name)
        assert after[0] == before[0]
        assert (await mysql_store.inspect_entries()).total == 0
        detail = await other.inspect_entry(value.cache_key, namespaces=None)
        assert detail is not None
        assert detail.response == "other binding"
        assert await other.inspect_entries() == other_before
        assert await mysql_store.clear_all() == 0
        await mysql_store.put(value)
        new = await mysql_store.inspect_entry(value.cache_key, namespaces=None)
        assert new is not None
        assert new.created_at > observed.created_at
        assert not await mysql_store.record_hit(
            value.cache_key, namespace="alpha", expected_created_at=observed.created_at
        )
    await mysql_store.aclose()
    await mysql_store.aclose()
    retired(mysql_store._worker)
    for operation in (
        mysql_store.inspect_entries(),
        mysql_store.inspect_entry(value.cache_key, namespaces=None),
        mysql_store.clear_all(),
    ):
        with pytest.raises(CacheClosedError):
            await operation


async def test_clear_removes_expired_without_counting_it(
    mysql_store: MySQLStore,
) -> None:
    live, dead = entry("live"), entry("expired")
    await mysql_store.put(live)
    await mysql_store.put(dead)
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_entries SET expires_at_us=1 WHERE cache_key=%s",
        (dead.cache_key.encode("ascii"),),
        name=mysql_store._config.database,
    )
    assert await mysql_store.clear_all() == 1
    assert await asyncio.to_thread(
        admin,
        "SELECT count(*) FROM semantix_payloads",
        name=mysql_store._config.database,
    ) == [(0,)]


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
@pytest.mark.parametrize("detail", [False, True])
async def test_interrupted_inspection_keeps_worker_owned(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch, stop: str, detail: bool
) -> None:
    value = entry("held search")
    await mysql_store.put(value)
    worker = mysql_store._worker
    original = decode_payload
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    calls: list[threading.Thread] = []
    timeouts: list[asyncio.Timeout] = []
    original_timeout = asyncio.timeout_at

    def deadline(when: float | None) -> asyncio.Timeout:
        timer = original_timeout(when)
        timeouts.append(timer)
        return timer

    def decode(payload: bytes, key: str, namespace: str) -> dict[str, str]:
        calls.append(threading.current_thread())
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return original(payload, key, namespace)

    with monkeypatch.context() as patch:
        patch.setattr(database, "decode_payload", decode)
        patch.setattr(asyncio, "timeout_at", deadline)
        operation = (
            mysql_store.inspect_entry(value.cache_key, namespaces=None)
            if detail
            else mysql_store.inspect_entries(search="held")
        )
        task = asyncio.create_task(operation)
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if stop == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert len(timeouts) == 1
                timeouts[0].reschedule(loop.time())
                with pytest.raises(CacheTimeoutError):
                    await task
            with pytest.raises(CacheBusyError):
                await mysql_store.aclose()
            assert worker.pending
            assert not worker.faulted.is_set()
            assert worker.thread is not None
            assert worker.thread.is_alive()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await until(lambda: not worker.pending)
    assert len(calls) == 1
    assert calls[0] is worker.thread
    assert (await mysql_store.inspect_entries()).total == 1
    assert not worker.faulted.is_set()
    await mysql_store.aclose()
    retired(worker)


async def test_read_snapshot_survives_concurrent_replacement(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = entry("old snapshot", namespace="alpha")
    await mysql_store.put(old)
    await mysql_store.put(entry("foreign", namespace="beta"))
    config = options(mysql_store._config.database) | {
        "embedding_space": mysql_store.embedding_space,
        "default_ttl_seconds": None,
    }
    async with await MySQLStore.connect(**config) as writer:
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        original = Job.rows
        once: list[int] = []

        def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
            result = original(job, sql, parameters)
            if (
                job.owner is mysql_store._worker
                and sql.startswith("SELECT cache_key,namespace,")
                and not once
            ):
                once.append(1)
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
            return result

        monkeypatch.setattr(Job, "rows", rows)
        task = asyncio.create_task(
            mysql_store.inspect_entries(namespace="alpha", search="snapshot")
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            assert await writer.delete_entry(old.cache_key, namespace="alpha")
            await writer.put(entry("new snapshot", namespace="alpha"))
            release.set()
            page = await task
            assert page.total == 1
            assert page.items[0].prompt == old.prompt
            assert page.items[0].response_preview == old.response
            current = await writer.inspect_entries(namespace="alpha")
            assert current.items[0].prompt == "new snapshot"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_clear_cancel_before_commit_rolls_back(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await mysql_store.put(entry("cancel clear"))
    worker = mysql_store._worker
    before = await asyncio.to_thread(persisted, mysql_store._config.database)
    original = Job.rows
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = original(job, sql, parameters)
        if sql == "DELETE FROM semantix_entries WHERE binding_id=%s":
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
        return result

    monkeypatch.setattr(Job, "rows", rows)
    task = asyncio.create_task(mysql_store.clear_all())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(CacheBusyError):
            await mysql_store.aclose()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await until(lambda: not worker.pending)
    assert worker.faulted.is_set()
    assert await asyncio.to_thread(persisted, mysql_store._config.database) == before
    with pytest.raises(CacheStoreError):
        await mysql_store.clear_all()


async def test_existing_restricted_runtime_grants_suffice(
    store_factory: StoreFactory,
) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    value = entry("least privilege", namespace="alpha")
    await store.put(value)
    assert (await store.inspect_entries(namespace="alpha")).total == 1
    detail = await store.inspect_entry(value.cache_key, namespaces=("alpha",))
    assert detail is not None
    assert detail.response == value.response
    assert await store.clear_all() == 1


async def test_clear_serializes_with_independent_writer(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await mysql_store.put(entry("before clear"))
    config = options(mysql_store._config.database) | {
        "embedding_space": mysql_store.embedding_space,
        "default_ttl_seconds": None,
    }
    async with await MySQLStore.connect(**config) as writer:
        deleted, waiting = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = Job.rows

        def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
            if (
                job.owner is writer._worker
                and sql.startswith("SELECT binding_id,")
                and sql.endswith(" FOR UPDATE")
            ):
                loop.call_soon_threadsafe(waiting.set)
            result = original(job, sql, parameters)
            if (
                job.owner is mysql_store._worker
                and sql == "DELETE FROM semantix_entries WHERE binding_id=%s"
            ):
                loop.call_soon_threadsafe(deleted.set)
                assert release.wait(5)
            return result

        monkeypatch.setattr(Job, "rows", rows)
        clear = asyncio.create_task(mysql_store.clear_all())
        put: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(deleted.wait(), 3)
            put = asyncio.create_task(writer.put(entry("after clear")))
            await asyncio.wait_for(waiting.wait(), 3)
            release.set()
            assert await clear == 1
            await put
            page = await writer.inspect_entries()
            assert page.total == 1
            assert page.items[0].prompt == "after clear"
        finally:
            release.set()
            await asyncio.gather(clear, return_exceptions=True)
            if put is not None:
                await asyncio.gather(put, return_exceptions=True)


@pytest.mark.parametrize(
    ("prompt", "search", "total"),
    [
        ("\u0130stanbul", "I\u0307STANBUL", 1),
        ("caf\u00e9", "cafe", 0),
        ("identifier", "response-only", 0),
    ],
)
async def test_search_is_unicode_casefolded_prompt_only(
    mysql_store: MySQLStore, prompt: str, search: str, total: int
) -> None:
    await mysql_store.put(
        entry(prompt).model_copy(update={"response": "response-only"})
    )
    page = await mysql_store.inspect_entries(search=search)
    assert page.total == total
    assert len(page.items) == total
