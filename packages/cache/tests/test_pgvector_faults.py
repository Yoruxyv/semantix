"""Real PostgreSQL disconnect, acknowledgement and cleanup ownership regressions."""

from __future__ import annotations

import asyncio
import os
import traceback

import asyncpg
import pytest
from asyncpg.pool import PoolConnectionProxy

from semantix_cache import (
    CacheClosedError,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache.stores.pgvector import PgVectorStore

from . import test_pgvector
from .test_memory import entry

SPACE = test_pgvector.SPACE
pg_store = test_pgvector.pg_store

pytestmark = pytest.mark.pgvector


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("committed", [False, True])
async def test_disconnect_at_commit_never_replays_or_closes_other_pool_users(
    pg_store: PgVectorStore,
    monkeypatch: pytest.MonkeyPatch,
    owned: bool,
    committed: bool,
) -> None:
    async with asyncio.timeout(10):
        store = (
            await PgVectorStore.connect(
                dsn=os.environ["PGVECTOR_TEST_DATABASE_URL"],
                embedding_space=SPACE,
                schema=pg_store._config.schema,
                pool_min_size=2,
                pool_max_size=2,
            )
            if owned
            else pg_store
        )
        original = entry("disconnect at commit")
        execute = asyncpg.Connection.execute
        connections: list[asyncpg.Connection[asyncpg.Record]] = []
        writes = 0
        commits = 0

        async def interrupt(
            connection: asyncpg.Connection[asyncpg.Record],
            query: str,
            *args: object,
            **kwargs: float | None,
        ) -> str:
            nonlocal writes, commits
            if original.cache_key in args:
                writes += 1
            if query == "COMMIT;":
                commits += 1
                if commits == 1:
                    connections.append(connection)
                    if committed:
                        await execute(connection, query, *args, **kwargs)
                        connection.terminate()
                        raise OSError("synthetic-private-commit-endpoint")
                    async with pg_store._pool.acquire(timeout=2) as operator:
                        assert await operator.fetchval(
                            "SELECT pg_terminate_backend($1)",
                            connection.get_server_pid(),
                        )
            return await execute(connection, query, *args, **kwargs)

        try:
            async with pg_store._pool.acquire(timeout=2) as unrelated:
                pid = unrelated.get_server_pid()
                with monkeypatch.context() as patch:
                    patch.setattr(asyncpg.Connection, "execute", interrupt)
                    with pytest.raises(CacheStoreError) as failure:
                        await store.put(original)
                for rendered in (
                    str(failure.value),
                    repr(failure.value),
                    "".join(traceback.format_exception(failure.value)),
                ):
                    assert "synthetic-private-commit-endpoint" not in rendered
                assert failure.value.__context__ is None
                assert commits == writes == 1
                observed = await store.find_nearest((1, 0), namespace="default")
                assert (observed is not None) is committed
                if observed is not None:
                    assert observed.entry.cache_key == original.cache_key
                    assert observed.entry.response == original.response
                assert store._state.active == 0
                assert store._pool.get_size() - store._pool.get_idle_size() == (
                    0 if owned else 1
                )
                assert not pg_store._pool.is_closing()
                assert await unrelated.fetchval("SELECT pg_backend_pid()") == pid
                await store.put(entry("explicit caller recovery"))
                assert await store.find_nearest((1, 0), namespace="default")
                await store.aclose()
                assert await unrelated.fetchval("SELECT 42") == 42
                if owned:
                    assert store._pool.get_size() == 0
        finally:
            # Keep a failing pre-fix regression from stranding its test fixture.
            for connection in connections:
                connection.terminate()
            await store.aclose()


@pytest.mark.parametrize(
    "failure_type", [asyncpg.InternalClientError, RuntimeError, asyncio.CancelledError]
)
@pytest.mark.parametrize("retire", [False, True])
@pytest.mark.parametrize("release_failure", [False, True])
async def test_unexpected_error_identity_and_cancellation_are_preserved(
    pg_store: PgVectorStore,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
    retire: bool,
    release_failure: bool,
) -> None:
    async with asyncio.timeout(5):
        raw = failure_type("unexpected-programming-error")

        async def fail(
            connection: PoolConnectionProxy[asyncpg.Record], *, require_schema: bool
        ) -> dict[str, str]:
            if retire:
                connection.terminate()
            raise raw

        release = asyncpg.Pool.release

        async def fail_release(
            pool: asyncpg.Pool,
            connection: PoolConnectionProxy[asyncpg.Record],
            **kwargs: float | None,
        ) -> None:
            await release(pool, connection, **kwargs)
            if pool is pg_store._pool:
                raise RuntimeError("unexpected-release-error")

        with monkeypatch.context() as patch:
            patch.setattr(pg_store, "_layout", fail)
            if release_failure:
                patch.setattr(asyncpg.Pool, "release", fail_release)
            with pytest.raises(failure_type) as observed:
                await pg_store.validate_schema()
        assert observed.value is raw
        assert pg_store._state.active == 0
        assert pg_store._pool.get_size() == pg_store._pool.get_idle_size()
        assert not pg_store._pool.is_closing()
        await pg_store.validate_schema()


@pytest.mark.parametrize(
    "failure_type", [OSError, RuntimeError, asyncio.CancelledError]
)
async def test_owned_close_failure_terminates_an_already_closing_pool(
    pg_store: PgVectorStore,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    async with asyncio.timeout(10):
        store = await PgVectorStore.connect(
            dsn=os.environ["PGVECTOR_TEST_DATABASE_URL"],
            embedding_space=SPACE,
            schema=pg_store._config.schema,
        )
        pool = store._pool
        held = await pool.acquire(timeout=2)
        started = asyncio.Event()
        close = asyncpg.Pool.close
        raw = failure_type("synthetic-private-close-endpoint")
        calls = 0

        async def in_progress() -> None:
            started.set()
            await close(pool)

        closing = asyncio.create_task(in_progress())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            assert pool.is_closing()
            assert pool.get_size() == 1

            async def fail(active: asyncpg.Pool) -> None:
                nonlocal calls
                if active is pool:
                    calls += 1
                    raise raw
                await close(active)

            with monkeypatch.context() as patch:
                patch.setattr(asyncpg.Pool, "close", fail)
                expected = CacheStoreError if failure_type is OSError else failure_type
                with pytest.raises(expected) as observed:
                    await store.aclose()
                assert pool.get_size() == 0
                await store.aclose()
                assert calls == 1
            if failure_type is OSError:
                for rendered in (
                    str(observed.value),
                    repr(observed.value),
                    "".join(traceback.format_exception(observed.value)),
                ):
                    assert "synthetic-private-close-endpoint" not in rendered
                assert observed.value.__context__ is None
            else:
                assert observed.value is raw
            with pytest.raises(CacheClosedError):
                await store.validate_schema()
            await asyncio.wait_for(closing, timeout=2)
        finally:
            pool.terminate()
            await pool.release(held, timeout=2)
            await asyncio.wait_for(closing, timeout=2)
            await store.aclose()


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("body_failure", [False, True])
async def test_release_finishes_before_deadline_or_cancellation_returns(
    pg_store: PgVectorStore,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    body_failure: bool,
) -> None:
    async with asyncio.timeout(5):
        started = asyncio.Event()
        finished = asyncio.Event()
        unblock = asyncio.Event()

        async def reset(connection: asyncpg.Connection[asyncpg.Record]) -> None:
            started.set()
            try:
                await unblock.wait()
            finally:
                finished.set()

        pool = await asyncpg.create_pool(
            os.environ["PGVECTOR_TEST_DATABASE_URL"],
            min_size=0,
            max_size=1,
            timeout=2,
            command_timeout=2,
            reset=reset,
        )
        store = PgVectorStore(
            pool=pool,
            embedding_space=SPACE,
            schema=pg_store._config.schema,
            operation_timeout_seconds=0.2,
        )
        layout = store._layout

        async def fail_layout(
            connection: PoolConnectionProxy[asyncpg.Record], *, require_schema: bool
        ) -> dict[str, str]:
            raise OSError("synthetic-private-body-endpoint")

        if body_failure:
            monkeypatch.setattr(store, "_layout", fail_layout)
        task = asyncio.create_task(store.validate_schema())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            if cancel:
                task.cancel()
                asyncio.get_running_loop().call_soon(task.cancel)
            with pytest.raises(asyncio.CancelledError if cancel else CacheTimeoutError):
                await asyncio.wait_for(task, timeout=2)
            assert finished.is_set()
            assert store._state.active == 0
            assert pool.get_size() == pool.get_idle_size()
            assert not pool.is_closing()
            unblock.set()
            monkeypatch.setattr(store, "_layout", layout)
            await store.validate_schema()
        finally:
            unblock.set()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.wait_for(finished.wait(), timeout=2)
            await store.aclose()
            async with asyncio.timeout(2):
                await pool.close()
