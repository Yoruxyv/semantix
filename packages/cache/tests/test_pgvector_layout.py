"""Provider-owned leaves preserve the public transaction and subclass boundaries."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import asyncpg
import pytest
from asyncpg.pool import PoolConnectionProxy

from semantix_cache import CacheStoreError
from semantix_cache.inspection import InspectionPage
from semantix_cache.stores import pgvector
from semantix_cache.stores.pgvector import PgVectorStore

from . import test_pgvector
from .test_memory import entry

pg_store = test_pgvector.pg_store

pytestmark = pytest.mark.pgvector


async def test_inspection_keeps_borrowed_readonly_snapshot_and_bound_scope(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = "scope_safe"
    original = entry("literal %_' before", namespace=namespace).model_copy(
        update={"response": "r" * 300}
    )
    await pg_store.put(original)
    observed: list[tuple[object, str, tuple[object, ...]]] = []
    fetchval = PoolConnectionProxy.fetchval
    fetch = PoolConnectionProxy.fetch

    async def count(
        connection: PoolConnectionProxy[asyncpg.Record], query: str, *args: object
    ) -> Any:
        result = await fetchval(connection, query, *args)
        if query.startswith("SELECT count(*) FROM ("):
            assert connection.is_in_transaction()
            assert (
                await fetchval(
                    connection, "SELECT current_setting('transaction_isolation')"
                )
                == "repeatable read"
            )
            assert (
                await fetchval(
                    connection, "SELECT current_setting('transaction_read_only')"
                )
                == "on"
            )
            observed.append((connection, query, args))
            # A separately borrowed writer commits between count and page fetch.
            await pg_store.put(entry("literal %_' after", namespace=namespace))
        return result

    async def page(
        connection: PoolConnectionProxy[asyncpg.Record], query: str, *args: object
    ) -> list[asyncpg.Record]:
        if query.startswith("WITH eligible"):
            observed.append((connection, query, args))
        return await fetch(connection, query, *args)

    with monkeypatch.context() as patch:
        patch.setattr(PoolConnectionProxy, "fetchval", count)
        patch.setattr(PoolConnectionProxy, "fetch", page)
        result = await pg_store.inspect_entries(namespace=namespace, search="%_'")
    assert result.total == len(result.items) == 1
    assert result.items[0].cache_key == original.cache_key
    assert result.items[0].response is None
    assert result.items[0].response_preview == "r" * 240
    assert result.items[0].response_preview_truncated
    assert len(observed) == 2
    assert observed[0][0] is observed[1][0]
    assert observed[0][2] == (
        pg_store.embedding_space.identity,
        2,
        namespace,
        None,
        None,
        "%_'",
    )
    assert observed[1][2] == (*observed[0][2], 0, 20)
    assert all(
        namespace not in query and "%_'" not in query for _, query, _ in observed
    )
    assert (await pg_store.inspect_entries(namespace=namespace)).total == 2
    assert await pg_store.inspect_entry(original.cache_key, namespaces=()) is None
    detail = await pg_store.inspect_entry(original.cache_key, namespaces=(namespace,))
    assert detail is not None
    assert detail.response == original.response
    assert pg_store._state.active == 0
    assert pg_store._pool.get_idle_size() == pg_store._pool.get_size()


@pytest.mark.parametrize("cancel", [False, True])
async def test_inspection_leaf_failure_releases_original_transaction(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    async def fail(
        connection: PoolConnectionProxy[asyncpg.Record], **arguments: object
    ) -> InspectionPage:
        assert connection.is_in_transaction()
        if cancel:
            raise asyncio.CancelledError
        await connection.execute("SELECT 1/0")
        raise AssertionError("Expected actual PostgreSQL failure")

    with monkeypatch.context() as patch:
        patch.setattr(pgvector, "_inspect_page", fail)
        expected = asyncio.CancelledError if cancel else CacheStoreError
        with pytest.raises(expected):
            await pg_store.inspect_entries()
    assert pg_store._state.active == 0
    assert pg_store._pool.get_idle_size() == pg_store._pool.get_size()
    assert not pg_store._pool.is_closing()
    await pg_store.validate_schema()


async def test_public_subclass_factory_and_inspection_hooks(
    pg_store: PgVectorStore,
) -> None:
    class ObservedStore(PgVectorStore):
        layouts = 0
        inspections = 0

        async def _layout(
            self,
            connection: PoolConnectionProxy[asyncpg.Record],
            *,
            require_schema: bool,
        ) -> dict[str, str]:
            self.layouts += 1
            return await super()._layout(connection, require_schema=require_schema)

        async def _inspect(self, **arguments: Any) -> InspectionPage:
            self.inspections += 1
            return await super()._inspect(**arguments)

    async with await ObservedStore.connect(
        dsn=os.environ["PGVECTOR_TEST_DATABASE_URL"],
        embedding_space=pg_store.embedding_space,
        schema=pg_store._config.schema,
    ) as owned:
        assert type(owned) is ObservedStore
        await owned.validate_schema()
        assert owned.layouts == 1
        assert (await owned.inspect_entries()).total == 0
        assert (
            await owned.inspect_entry(entry("absent").cache_key, namespaces=()) is None
        )
        assert owned.inspections == 2
        assert owned.layouts == 3
    assert owned._pool.is_closing()
    assert not pg_store._pool.is_closing()
