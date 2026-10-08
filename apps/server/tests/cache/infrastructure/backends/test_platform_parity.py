import asyncio
import os
from contextlib import suppress
from uuid import uuid4

import asyncpg
import httpx
import pytest
from asyncpg.pool import PoolConnectionProxy
from pydantic import ValidationError

from app.cache.infrastructure.backends.pgvector import PgVectorCacheBackend
from app.cache.infrastructure.database import initialize_official_schema
from app.cache.infrastructure.factory import cache_backend_lifespan
from app.cache.infrastructure.setup import initialize_redis
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.factory import create_app
from semantix_cache import MemoryStore
from semantix_cache.inspection import InspectionPage
from semantix_cache.stores.pgvector import PgVectorStore
from semantix_cache.stores.redis import RedisStore
from tests.cache.infrastructure.backends.support import cache_entry


@pytest.fixture(
    params=[
        "memory",
        pytest.param("pgvector", marks=pytest.mark.pgvector),
        pytest.param("redis", marks=pytest.mark.redis),
    ]
)
async def platform_settings(request: pytest.FixtureRequest) -> Settings:
    kind = str(request.param)
    pg = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    redis = os.environ.get("REDIS_TEST_URL")
    if (kind == "pgvector" and not pg) or (kind == "redis" and not redis):
        pytest.skip("Disposable integration service is not configured")
    settings = Settings(
        cache_backend=kind,
        embedding_provider="mock",
        generation_provider="mock",
        database_url=pg,
        redis_url=redis,
        redis_key_prefix="platform_" + uuid4().hex,
        cache_ttl_seconds=1,
        max_cache_size=10,
        rate_limit="1000/minute",
        allowed_origins=["http://localhost:5173"],
    )
    if kind == "redis":
        assert redis is not None
        await initialize_redis(settings, initialization_url=redis)
    return settings


async def test_live_query_inspector_policies_expiry_and_clear(
    platform_settings: Settings,
) -> None:
    app = create_app(platform_settings)
    async with app.router.lifespan_context(app):
        backend = app.state.semantic_cache._backend
        expected = {
            "memory": MemoryStore,
            "pgvector": PgVectorStore,
            "redis": RedisStore,
        }
        assert isinstance(backend.store, expected[platform_settings.cache_backend])
        await backend.clear(None)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/ready")).json()[
                "cache_backend"
            ] == platform_settings.cache_backend
            diag = (await client.get("/api/v1/diagnostics")).json()
            assert diag["cache_backend"] == platform_settings.cache_backend
            assert "redis_url" not in diag
            assert "database_url" not in diag

            async def query(
                prompt: str, namespace: str = "alpha", policy: str = "normal"
            ) -> dict[str, object]:
                response = await client.post(
                    "/api/v1/query",
                    json={
                        "prompt": prompt,
                        "namespace": namespace,
                        **{
                            "normal": {},
                            "private": {"private": True},
                            "bypass": {"cache_enabled": False},
                            "read_only": {"cache_write_enabled": False},
                            "refresh": {"cache_read_enabled": False},
                        }[policy],
                    },
                )
                assert response.status_code == 200, response.text
                result: dict[str, object] = response.json()
                return result

            for policy in ("private", "bypass", "read_only"):
                result = await query("isolated " + policy, policy=policy)
                assert result["cache_hit"] is False
                assert result["provider_called"] is True
            assert (await backend.stats(None)).size == 0
            first = await query("repeatable prompt")
            assert first["cache_hit"] is False
            assert (await query("repeatable prompt"))["cache_hit"] is True
            assert (await query("repeatable prompt", namespace="beta"))[
                "cache_hit"
            ] is False
            assert (await query("repeatable prompt", policy="refresh"))[
                "cache_hit"
            ] is False
            listing = (
                await client.get("/api/v1/cache/entries", params={"namespace": "alpha"})
            ).json()
            assert listing["total"] == 1
            key = listing["items"][0]["cache_key"]
            assert listing["items"][0]["response"] is None
            assert "embedding" not in listing["items"][0]
            assert (await client.get("/api/v1/cache/entries/" + key)).json()["response"]
            assert (
                await client.delete("/api/v1/cache/entries/" + key)
            ).status_code == 200
            assert (await client.get("/api/v1/cache/entries/" + key)).status_code == 404
            await query("expiry prompt")
            await asyncio.sleep(1.05)
            assert (await query("expiry prompt"))["cache_hit"] is False
            assert (
                await client.delete("/api/v1/cache", params={"namespace": "alpha"})
            ).status_code == 200
            assert (
                await client.get("/api/v1/cache/entries", params={"namespace": "alpha"})
            ).json()["total"] == 0
            await backend.clear(None)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid",
        "redis://example.invalid:bad",
        "redis://example.invalid?password=marker",
    ],
)
def test_redis_configuration_errors_do_not_echo_credentials(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            embedding_provider="mock",
            generation_provider="mock",
            cache_backend="redis",
            redis_url=url,
            allowed_origins=["http://localhost:5173"],
        )
    assert url not in str(caught.value)


@pytest.mark.pgvector
async def test_legacy_entries_are_preserved_and_never_adopted() -> None:
    url = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL is not configured")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=1, command_timeout=10)
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        cache_backend="pgvector",
        database_url=url,
        cache_pgvector_table_prefix="transition_" + uuid4().hex[:12] + "_",
        allowed_origins=["http://localhost:5173"],
    )

    try:
        async with pool.acquire() as connection:
            before = await connection.fetch(
                "SELECT * FROM semantix.cache_entries ORDER BY embedding_space,cache_key"
            )
        with pytest.raises(CacheStorageError):
            async with cache_backend_lifespan(
                settings, dimensions=384, embedding_space="transition", pool=pool
            ):
                pytest.fail("Startup silently initialized absent official tables")
        assert await pool.fetchval("SELECT 1") == 1
        await initialize_official_schema(
            pool, table_prefix=settings.cache_pgvector_table_prefix
        )
        async with cache_backend_lifespan(
            settings, dimensions=384, embedding_space="transition", pool=pool
        ) as backend:
            assert (await backend.stats(None)).size == 0
        async with pool.acquire() as connection:
            after = await connection.fetch(
                "SELECT * FROM semantix.cache_entries ORDER BY embedding_space,cache_key"
            )
        assert before == after
        assert await pool.fetchval("SELECT 1") == 1
    finally:
        await pool.close()


@pytest.mark.pgvector
@pytest.mark.parametrize("operation", ["count", "clear", "stats"])
@pytest.mark.parametrize("failure", ["timeout", "cancel"])
async def test_pg_telemetry_pool_contention_respects_deadline(
    monkeypatch: pytest.MonkeyPatch, operation: str, failure: str
) -> None:
    url = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL is not configured")
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        cache_backend="pgvector",
        database_url=url,
        database_command_timeout_seconds=0.1 if failure == "timeout" else 1,
        allowed_origins=["http://localhost:5173"],
    )
    pool = await asyncpg.create_pool(url, min_size=1, max_size=1, command_timeout=2)
    backend = PgVectorCacheBackend(
        pool,
        10,
        None,
        dimensions=4,
        embedding_space="telemetry-deadline-" + uuid4().hex,
        operation_timeout_seconds=settings.database_command_timeout_seconds,
    )
    held: PoolConnectionProxy[asyncpg.Record] | None = None
    acquired = asyncio.Event()

    async def hold_connection() -> None:
        nonlocal held
        held = await pool.acquire(timeout=1)
        acquired.set()

    try:
        await backend.put(
            cache_entry("deadline entry", "complete answer", vector_index=0)
        )
        await backend.record_miss("default")
        with monkeypatch.context() as stage:
            if operation == "clear":
                original_clear = backend.store.clear_all

                async def clear_then_hold() -> int:
                    count = await original_clear()
                    await hold_connection()
                    return count

                stage.setattr(backend.store, "clear_all", clear_then_hold)
            elif operation == "stats":
                original_inspect = backend.store.inspect_entries

                async def inspect_then_hold(
                    *, namespace: str | None, limit: int
                ) -> InspectionPage:
                    page = await original_inspect(namespace=namespace, limit=limit)
                    await hold_connection()
                    return page

                stage.setattr(backend.store, "inspect_entries", inspect_then_hold)
            else:
                await hold_connection()

            async def perform() -> None:
                if operation == "count":
                    await backend.record_miss("default")
                elif operation == "clear":
                    await backend.clear(None)
                else:
                    await backend.stats(None)

            task = asyncio.create_task(perform())
            try:
                await asyncio.wait_for(acquired.wait(), timeout=2)
                if failure == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    with pytest.raises(
                        CacheStorageError, match=r"^Official cache operation failed$"
                    ) as caught:
                        await asyncio.wait_for(asyncio.shield(task), timeout=2)
                    assert caught.value.error_code == "cache_error"
                    assert caught.value.status_code == 500
                    assert caught.value.__cause__ is None
                    assert caught.value.__suppress_context__
                    assert url not in str(caught.value)
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                assert held is not None
                await pool.release(held, timeout=2)
                held = None

        # A failed counter wait never increments or resets successful telemetry.
        # Cache clear and telemetry are separate operations: report failure rather
        # than claiming that a completed authoritative mutation was rolled back.
        stats = await backend.stats(None)
        assert stats.misses == 1
        assert stats.hits == 0
        assert stats.size == (0 if operation == "clear" else 1)
        assert await pool.fetchval("SELECT 1") == 1
        assert pool.get_idle_size() == 1
        await backend.record_miss("default")
        assert (await backend.stats(None)).misses == 2
        await backend.clear(None)
        assert (await backend.stats(None)).model_dump() == {
            "size": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
        }
    finally:
        if held is not None:
            await pool.release(held, timeout=2)
        await backend.store.aclose()
        assert not pool.is_closing()
        async with asyncio.timeout(2):
            await pool.close()


@pytest.mark.pgvector
async def test_pg_telemetry_sql_timeout_releases_connection_without_counting() -> None:
    url = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL is not configured")
    pool = await asyncpg.create_pool(url, min_size=2, max_size=2, command_timeout=2)
    backend = PgVectorCacheBackend(
        pool,
        10,
        None,
        dimensions=4,
        embedding_space="telemetry-sql-deadline-" + uuid4().hex,
        operation_timeout_seconds=0.1,
    )
    try:
        await backend.record_miss("default")
        async with pool.acquire() as blocker, blocker.transaction():
            await blocker.execute(
                "LOCK TABLE semantix.cache_namespace_counters IN ACCESS EXCLUSIVE MODE"
            )
            with pytest.raises(
                CacheStorageError, match=r"^Official cache operation failed$"
            ):
                await asyncio.wait_for(backend.record_miss("default"), timeout=1)
        # The statement was cancelled, not allowed to count later when unlocked.
        assert pool.get_idle_size() == 2
        assert (await backend.stats(None)).misses == 1
        await backend.record_miss("default")
        assert (await backend.stats(None)).misses == 2
        await backend.clear(None)
        assert (await backend.stats(None)).misses == 0
    finally:
        await backend.store.aclose()
        assert not pool.is_closing()
        async with asyncio.timeout(2):
            await pool.close()
