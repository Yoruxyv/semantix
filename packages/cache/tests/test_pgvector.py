"""Real disposable-database isolation, migration, transaction and ownership tests."""

from __future__ import annotations

import asyncio
import os
import traceback
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from asyncpg.pool import PoolConnectionProxy

from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    EmbeddingSpace,
)
from semantix_cache.stores import pgvector
from semantix_cache.stores.pgvector import PgVectorStore

from .test_memory import entry

pytestmark = pytest.mark.pgvector
SPACE = EmbeddingSpace(identity="pg-contract-v1", dimensions=2)


@pytest.fixture
async def pg_store(pg_pool: asyncpg.Pool | None) -> AsyncIterator[PgVectorStore]:
    if pg_pool is None:
        pytest.skip("Set PGVECTOR_TEST_DATABASE_URL to a disposable database")
    schema = "cache_test_" + uuid4().hex
    store = PgVectorStore(pool=pg_pool, embedding_space=SPACE, schema=schema)
    try:
        await store.initialize_schema(migration_pool=pg_pool)
        yield store
    finally:
        await store.aclose()
        assert schema.startswith("cache_test_")
        assert len(schema) == 43
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


async def test_owned_pool_persistence_no_implicit_ddl_and_double_close(
    pg_pool: asyncpg.Pool | None,
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    schema = "cache_test_" + uuid4().hex
    dsn = os.environ["PGVECTOR_TEST_DATABASE_URL"]
    store = await PgVectorStore.connect(
        dsn=dsn, embedding_space=SPACE, schema=schema, pool_min_size=2, pool_max_size=2
    )
    owned = store._pool
    try:
        assert owned.get_size() == 2
        async with pg_pool.acquire() as connection:
            assert (
                await connection.fetchval("SELECT to_regnamespace($1)", schema) is None
            )
        with pytest.raises(CacheStoreError):
            await store.validate_schema()
        with pytest.raises(CacheStoreError):
            await store.find_nearest((1, 0), namespace="default")
        await store.initialize_schema(migration_pool=pg_pool)
        await store.validate_schema()
        await store.initialize_schema(migration_pool=pg_pool)
        await store.put(entry("persist"))
        await store.aclose()
        await store.aclose()
        assert owned.is_closing()
        assert not pg_pool.is_closing()
        async with await PgVectorStore.connect(
            dsn=dsn, embedding_space=SPACE, schema=schema
        ) as reopened:
            match = await reopened.find_nearest((1, 0), namespace="default")
            assert match is not None
            assert match.entry.prompt == "persist"
    finally:
        await store.aclose()
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


async def test_shared_tables_filter_identity_dimensions_and_namespace(
    pg_store: PgVectorStore,
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    other = PgVectorStore(
        pool=pool,
        embedding_space=EmbeddingSpace(identity="different", dimensions=2),
        schema=schema,
    )
    dimensions = PgVectorStore(
        pool=pool,
        embedding_space=EmbeddingSpace(identity=SPACE.identity, dimensions=3),
        schema=schema,
    )
    await pg_store.put(entry("same", namespace="a"))
    assert await other.find_nearest((1, 0), namespace="a") is None
    assert not await other.delete_entry(
        entry("same", namespace="a").cache_key, namespace="a"
    )
    await other.put(entry("same", namespace="a", vector=(0, 1)))
    await dimensions.put(entry("different", namespace="a", vector=(1, 0, 0)))
    assert (await pg_store.find_nearest((1, 0), namespace="a")) is not None
    match = await dimensions.find_nearest((1, 0, 0), namespace="a")
    assert match is not None
    assert len(match.entry.embedding) == 3
    assert await other.clear(namespace="a") == 1
    assert await pg_store.clear(namespace="a") == 1
    assert (await dimensions.find_nearest((1, 0, 0), namespace="a")) is not None
    await other.aclose()
    await dimensions.aclose()
    assert not pool.is_closing()


async def test_existing_database_collision_safe_migration_rollback_and_checksum(
    pg_store: PgVectorStore,
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    async with pool.acquire() as connection:
        await connection.execute(
            f'CREATE TABLE "{schema}".application_orders (id integer PRIMARY KEY, note text)'
        )
        await connection.execute(
            f'INSERT INTO "{schema}".application_orders VALUES (1,$1)',
            "application data",
        )
        await connection.execute(
            f'CREATE TABLE "{schema}".collision_cache_entries (note text)'
        )
    collision = PgVectorStore(
        pool=pool, embedding_space=SPACE, schema=schema, table_prefix="collision_"
    )
    with pytest.raises(CacheStoreError):
        await collision.initialize_schema(migration_pool=pool)
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(f'SELECT note FROM "{schema}".application_orders')
            == "application data"
        )
        assert (
            await connection.fetchval(
                "SELECT to_regclass($1)", f'"{schema}".collision_schema_migrations'
            )
            is None
        )
        await connection.execute(
            f'UPDATE "{schema}".schema_migrations SET checksum=$1', "tampered"
        )
    with pytest.raises(CacheStoreError):
        await pg_store.validate_schema()
    with pytest.raises(CacheStoreError):
        await pg_store.clear(namespace="default")
    await collision.aclose()


async def test_failed_write_transaction_rolls_back_revision_and_entries(
    pg_store: PgVectorStore,
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    await pg_store.put(entry("first"))
    async with pool.acquire() as connection:
        before = await connection.fetchrow(
            f'SELECT revision, access_order FROM "{schema}".binding_state'
        )
        await connection.execute(
            f"ALTER TABLE \"{schema}\".cache_entries ADD CONSTRAINT reject_failed_write CHECK (prompt <> 'reject')"
        )
    value = entry("reject")
    with pytest.raises(CacheStoreError) as failure:
        await pg_store.put(value)
    assert "reject" not in "".join(traceback.format_exception(failure.value))
    async with pool.acquire() as connection:
        after = await connection.fetchrow(
            f'SELECT revision, access_order FROM "{schema}".binding_state'
        )
        assert before == after
        assert (
            await connection.fetchval(f'SELECT count(*) FROM "{schema}".cache_entries')
            == 1
        )
    await pg_store.put(entry("after"))


async def test_migration_failure_rolls_back_all_owned_objects(
    pg_store: PgVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    monkeypatch.setattr(pgvector, "_MIGRATION", pgvector._MIGRATION + "\nSELECT 1/0;")
    broken = PgVectorStore(
        pool=pool, embedding_space=SPACE, schema=schema, table_prefix="failed_"
    )
    with pytest.raises(CacheStoreError):
        await broken.initialize_schema(migration_pool=pool)
    async with pool.acquire() as connection:
        for suffix in ("schema_migrations", "cache_entries", "binding_state"):
            assert (
                await connection.fetchval(
                    "SELECT to_regclass($1)", f'"{schema}".failed_{suffix}'
                )
                is None
            )
        assert (
            await connection.fetchval(
                "SELECT to_regclass($1)", f'"{schema}".cache_entries'
            )
            is not None
        )
    await broken.aclose()


async def test_runtime_role_has_no_ddl_permission_and_releases_borrowed_pool(
    pg_store: PgVectorStore,
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    role = "cache_role_" + uuid4().hex
    async with pool.acquire() as connection:
        await connection.execute(f'CREATE ROLE "{role}"')
        await connection.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        for suffix in ("schema_migrations", "binding_state", "cache_entries"):
            privileges = (
                "SELECT"
                if suffix == "schema_migrations"
                else "SELECT, INSERT, UPDATE, DELETE"
            )
            await connection.execute(
                f'GRANT {privileges} ON "{schema}"."{suffix}" TO "{role}"'
            )

    async def setup(connection: PoolConnectionProxy[asyncpg.Record]) -> None:
        await connection.execute(f'SET ROLE "{role}"')

    runtime = await asyncpg.create_pool(
        os.environ["PGVECTOR_TEST_DATABASE_URL"],
        min_size=1,
        max_size=1,
        setup=setup,
        command_timeout=5,
    )
    assert runtime is not None
    store = PgVectorStore(pool=runtime, embedding_space=SPACE, schema=schema)
    try:
        await store.validate_schema()
        await store.put(entry("runtime"))
        match = await store.find_nearest((1, 0), namespace="default")
        assert match is not None
        assert await store.record_hit(
            match.entry.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert await store.delete_entry(match.entry.cache_key, namespace="default")
        await store.put(entry("clear runtime"))
        assert await store.clear(namespace="default") == 1
        await store.aclose()
        assert not runtime.is_closing()
        async with runtime.acquire() as connection:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(f'CREATE TABLE "{schema}".forbidden (id int)')
    finally:
        await store.aclose()
        await runtime.close()
        async with pool.acquire() as connection:
            await connection.execute(f'DROP OWNED BY "{role}"')
            await connection.execute(f'DROP ROLE "{role}"')


async def test_busy_close_cancellation_and_acquisition_deadline(
    pg_store: PgVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = pg_store._pool
    schema = pg_store._config.schema
    blocked = PgVectorStore(
        pool=pool, embedding_space=SPACE, schema=schema, operation_timeout_seconds=0.1
    )
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            pg_store._config.lock_key + ":" + SPACE.identity + ":2",
        )
        started = asyncio.Event()
        original = blocked._lock

        async def blocked_lock(
            conn: PoolConnectionProxy[asyncpg.Record],
        ) -> None:
            started.set()
            await original(conn)

        monkeypatch.setattr(blocked, "_lock", blocked_lock)
        task = asyncio.create_task(blocked.put(entry("blocked")))
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(CacheBusyError):
            await blocked.aclose()
        with pytest.raises(CacheTimeoutError):
            await task
        cancel_started = asyncio.Event()
        cancel_original = pg_store._lock

        async def cancellation_lock(
            conn: PoolConnectionProxy[asyncpg.Record],
        ) -> None:
            cancel_started.set()
            await cancel_original(conn)

        monkeypatch.setattr(pg_store, "_lock", cancellation_lock)
        task = asyncio.create_task(pg_store.put(entry("cancelled")))
        await asyncio.wait_for(cancel_started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await pg_store.find_nearest((1, 0), namespace="default") is None
    await blocked.aclose()
    await pg_store.put(entry("works"))


async def test_factory_connection_failure_redaction_and_validation() -> None:
    private_dsn = "postgresql://private-user:private-password@127.0.0.1:1/private-db"
    with pytest.raises((CacheStoreError, CacheTimeoutError)) as failure:
        await PgVectorStore.connect(
            dsn=private_dsn,
            embedding_space=SPACE,
            connect_timeout_seconds=0.5,
        )
    trace = "".join(traceback.format_exception(failure.value))
    for secret in ("private-password", "private-user", "private-db", "127.0.0.1"):
        assert secret not in trace
        assert secret not in repr(failure.value)
    with pytest.raises(CacheConfigurationError):
        await PgVectorStore.connect(dsn="private-password", embedding_space=SPACE)


async def test_corrupt_persisted_payload_rejected(pg_store: PgVectorStore) -> None:
    await pg_store.put(entry("seed"))
    async with pg_store._pool.acquire() as connection:
        await connection.execute(
            f'UPDATE "{pg_store._config.schema}".cache_entries SET prompt=$1',
            "wrong key",
        )
    with pytest.raises(CacheStoreError):
        await pg_store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheStoreError):
        await pg_store.put(
            entry("nul").model_copy(update={"response": "not\0PostgreSQL text"})
        )


async def test_prefixes_and_concurrent_initialization_preserve_existing_objects(
    pg_store: PgVectorStore,
) -> None:
    a = PgVectorStore(
        pool=pg_store._pool,
        embedding_space=SPACE,
        schema=pg_store._config.schema,
        table_prefix="support_",
    )
    b = PgVectorStore(
        pool=pg_store._pool,
        embedding_space=SPACE,
        schema=pg_store._config.schema,
        table_prefix="support_",
    )
    await asyncio.gather(
        a.initialize_schema(migration_pool=pg_store._pool),
        b.initialize_schema(migration_pool=pg_store._pool),
    )
    await a.put(entry("persistent"))
    assert await pg_store.find_nearest((1, 0), namespace="default") is None
    assert await b.find_nearest((1, 0), namespace="default") is not None
    await a.aclose()
    await b.aclose()


async def test_closed_maintenance_and_validation_inputs(
    pg_store: PgVectorStore,
) -> None:
    await pg_store.aclose()
    with pytest.raises(CacheClosedError):
        await pg_store.validate_schema()
    with pytest.raises(CacheClosedError):
        await pg_store.initialize_schema(migration_pool=pg_store._pool)
    with pytest.raises(CacheClosedError):
        await pg_store.put(entry("closed"))
    with pytest.raises(CacheClosedError):
        await pg_store.__aenter__()


@pytest.mark.parametrize(
    "failure_type",
    [OSError, ValueError, TimeoutError, asyncio.CancelledError, RuntimeError],
)
async def test_partial_owned_startup_failure_closes_preopened_connections(
    pg_pool: asyncpg.Pool | None,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    original = asyncpg.create_pool
    connections: list[asyncpg.Connection[asyncpg.Record]] = []
    pools: list[asyncpg.Pool] = []
    raw_failure = failure_type("synthetic-private-endpoint")

    async def connect(*args: Any, **kwargs: Any) -> asyncpg.Connection[asyncpg.Record]:
        if connections:
            raise raw_failure
        connection = cast(
            "asyncpg.Connection[asyncpg.Record]", await asyncpg.connect(*args, **kwargs)
        )
        connections.append(connection)
        return connection

    def create(*args: Any, **kwargs: Any) -> asyncpg.Pool:
        pool = original(*args, connect=connect, **kwargs)
        assert pool is not None
        pools.append(pool)
        return pool

    monkeypatch.setattr(asyncpg, "create_pool", create)
    expected = {
        OSError: CacheStoreError,
        ValueError: CacheConfigurationError,
        TimeoutError: CacheTimeoutError,
        asyncio.CancelledError: asyncio.CancelledError,
        RuntimeError: RuntimeError,
    }[failure_type]
    with pytest.raises(expected) as failure:
        await PgVectorStore.connect(
            dsn=os.environ["PGVECTOR_TEST_DATABASE_URL"],
            embedding_space=SPACE,
            pool_min_size=2,
            pool_max_size=2,
        )
    assert len(connections) == 1
    assert connections[0].is_closed()
    assert pools[0].is_closing()
    if failure_type not in (RuntimeError, asyncio.CancelledError):
        assert failure.value.__context__ is None
        assert "synthetic-private-endpoint" not in repr(failure.value.__cause__)
    else:
        assert failure.value is raw_failure


@pytest.mark.parametrize("cancel", [False, True])
async def test_owned_close_timeout_or_cancellation_seals_and_terminates(
    pg_pool: asyncpg.Pool | None,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    store = await PgVectorStore.connect(
        dsn=os.environ["PGVECTOR_TEST_DATABASE_URL"],
        embedding_space=SPACE,
        close_timeout_seconds=0.1 if not cancel else 10,
    )
    pool = store._pool
    held = await pool.acquire()
    started = asyncio.Event()
    original = asyncpg.Pool.close
    closes = 0

    async def close(self: asyncpg.Pool) -> None:
        nonlocal closes
        if self is pool:
            closes += 1
            started.set()
        await original(self)

    monkeypatch.setattr(asyncpg.Pool, "close", close)
    try:
        task = asyncio.create_task(store.aclose())
        await asyncio.wait_for(started.wait(), timeout=5)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else CacheTimeoutError):
            await task
        assert pool.is_closing()
        assert pool.get_size() == 0
        with pytest.raises(asyncpg.InterfaceError):
            await held.fetchval("SELECT 1")
        await store.aclose()
        assert closes == 1
        with pytest.raises(CacheClosedError):
            await store.clear(namespace="default")
    finally:
        await pool.release(held)
        await store.aclose()


async def test_concurrent_distinct_prefixes_in_a_new_schema(
    pg_pool: asyncpg.Pool | None,
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    schema = "cache_test_" + uuid4().hex
    stores = [
        PgVectorStore(
            pool=pg_pool, embedding_space=SPACE, schema=schema, table_prefix=prefix
        )
        for prefix in ("a_", "b_")
    ]
    try:
        await asyncio.gather(
            *(store.initialize_schema(migration_pool=pg_pool) for store in stores)
        )
        await stores[0].put(entry("a"))
        assert await stores[1].find_nearest((1, 0), namespace="default") is None
    finally:
        for store in stores:
            await store.aclose()
        assert schema.startswith("cache_test_")
        assert len(schema) == 43
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


async def test_operator_extension_requirement_and_nonpublic_extension_schema(
    pg_pool: asyncpg.Pool | None,
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    database = "cache_blank_" + uuid4().hex
    parsed = urlsplit(os.environ["PGVECTOR_TEST_DATABASE_URL"])
    dsn = urlunsplit(parsed._replace(path="/" + database))
    async with pg_pool.acquire() as connection:
        await connection.execute(f'CREATE DATABASE "{database}"')
    try:
        async with await PgVectorStore.connect(dsn=dsn, embedding_space=SPACE) as store:
            with pytest.raises(CacheStoreError, match="Install the vector extension"):
                await store.validate_schema()
            with pytest.raises(CacheStoreError, match="Install the vector extension"):
                await store.initialize_schema(migration_pool=store._pool)
            async with store._pool.acquire() as connection:
                assert (
                    await connection.fetchval(
                        "SELECT to_regnamespace('semantix_cache')"
                    )
                    is None
                )
                # Operator action in a test-owned database; quoted catalog schema.
                await connection.execute('CREATE SCHEMA "Vector Library"')
                await connection.execute(
                    'CREATE EXTENSION vector WITH SCHEMA "Vector Library"'
                )
                await connection.execute("SET search_path TO pg_catalog")
            await store.initialize_schema(migration_pool=store._pool)
            await store.put(entry("extension schema"))
            assert await store.find_nearest((1, 0), namespace="default") is not None
    finally:
        assert database.startswith("cache_blank_")
        assert len(database) == 44
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP DATABASE "{database}"')
