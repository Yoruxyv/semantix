import asyncio
import os
from collections.abc import AsyncIterator
from hashlib import sha256
from uuid import uuid4

import asyncpg
import pytest
from asyncpg.pool import Pool
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.exceptions import CoordinationStorageError
from app.factory import create_app
from app.infrastructure.coordination import PostgresCoordination
from app.infrastructure.coordination_database import (
    apply_migrations,
    grant_runtime_privileges,
)

pytestmark = pytest.mark.pgvector


@pytest.fixture
async def coordination_pool() -> AsyncIterator[Pool]:
    url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=8)
    async with pool.acquire() as connection:
        await connection.execute("DROP SCHEMA IF EXISTS semantix CASCADE")
    await apply_migrations(pool)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_rate_limit_is_atomic_shared_scoped_and_expires(
    coordination_pool: Pool,
) -> None:
    first = PostgresCoordination(coordination_pool)
    second = PostgresCoordination(coordination_pool)
    results = await asyncio.gather(
        *(
            (first if index % 2 else second).allow_request(
                "198.51.100.10", "/api/v1/cache/stats", "3/second", 3, 1
            )
            for index in range(10)
        )
    )
    assert results.count(True) == 3
    assert await second.allow_request(
        "198.51.100.11", "/api/v1/cache/stats", "3/second", 3, 1
    )
    assert await first.allow_request(
        "198.51.100.10", "/api/v1/cache/threshold", "3/second", 3, 1
    )
    await asyncio.sleep(1.05)
    assert await PostgresCoordination(coordination_pool).allow_request(
        "198.51.100.10", "/api/v1/cache/stats", "3/second", 3, 1
    )
    async with coordination_pool.acquire() as connection:
        keys = await connection.fetch(
            "SELECT bucket_key FROM semantix.rate_limit_buckets"
        )
    assert all("198.51.100.10" not in row["bucket_key"] for row in keys)


@pytest.mark.asyncio
async def test_cancelled_rate_wait_does_not_count(coordination_pool: Pool) -> None:
    url = os.environ["PGVECTOR_TEST_DATABASE_URL"]
    single_connection_pool = await asyncpg.create_pool(url, min_size=1, max_size=1)
    try:
        coordinator = PostgresCoordination(single_connection_pool)
        async with single_connection_pool.acquire():
            pending = asyncio.create_task(
                coordinator.allow_request("198.51.100.30", "/query", "1/minute", 1, 60)
            )
            await asyncio.sleep(0.05)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert await coordinator.allow_request(
            "198.51.100.30", "/query", "1/minute", 1, 60
        )
        assert not await coordinator.allow_request(
            "198.51.100.30", "/query", "1/minute", 1, 60
        )
    finally:
        await single_connection_pool.close()


@pytest.mark.asyncio
async def test_progressive_lockout_is_atomic_shared_and_resets(
    coordination_pool: Pool,
) -> None:
    first = PostgresCoordination(coordination_pool)
    second = PostgresCoordination(coordination_pool)
    results = await asyncio.gather(
        *(
            (first if index % 2 else second).record_session_attempt(
                "198.51.100.10", succeeded=False
            )
            for index in range(8)
        )
    )
    assert results.count(None) == 2
    assert all(result is None or 1 <= result <= 30 for result in results)
    assert await second.record_session_attempt("198.51.100.11", succeeded=False) is None
    assert (
        await first.record_session_attempt("198.51.100.10", succeeded=True) is not None
    )

    async with coordination_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.authentication_attempts
            SET locked_until = clock_timestamp() - interval '1 second'
            WHERE client_key = $1
            """,
            sha256(b"198.51.100.10").hexdigest(),
        )
    assert await first.record_session_attempt("198.51.100.10", succeeded=False) is None
    assert await second.record_session_attempt("198.51.100.10", succeeded=False) is None
    assert await first.record_session_attempt("198.51.100.10", succeeded=False) == 60

    async with coordination_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.authentication_attempts
            SET locked_until = clock_timestamp() - interval '1 second'
            WHERE client_key = $1
            """,
            sha256(b"198.51.100.10").hexdigest(),
        )
    assert await second.record_session_attempt("198.51.100.10", succeeded=True) is None
    assert await first.record_session_attempt("198.51.100.10", succeeded=False) is None

    async with coordination_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.authentication_attempts
            SET last_activity = clock_timestamp() - interval '1 day'
            WHERE client_key = $1
            """,
            sha256(b"198.51.100.10").hexdigest(),
        )
    assert await second.record_session_attempt("198.51.100.10", succeeded=False) is None
    assert await first.record_session_attempt("198.51.100.10", succeeded=False) is None
    assert await second.record_session_attempt("198.51.100.10", succeeded=False) == 30


@pytest.mark.asyncio
async def test_cancelled_lockout_update_does_not_count(
    coordination_pool: Pool,
) -> None:
    coordinator = PostgresCoordination(coordination_pool)
    address = "198.51.100.20"
    assert await coordinator.record_session_attempt(address, succeeded=False) is None
    async with coordination_pool.acquire() as connection, connection.transaction():
        await connection.fetchrow(
            """
            SELECT client_key FROM semantix.authentication_attempts
            WHERE client_key = $1 FOR UPDATE
            """,
            sha256(address.encode()).hexdigest(),
        )
        pending = asyncio.create_task(
            coordinator.record_session_attempt(address, succeeded=False)
        )
        await asyncio.sleep(0.05)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert await coordinator.record_session_attempt(address, succeeded=False) is None
    assert await coordinator.record_session_attempt(address, succeeded=False) == 30


@pytest.mark.asyncio
async def test_threshold_is_shared_and_outage_fails_closed(
    coordination_pool: Pool,
) -> None:
    first = PostgresCoordination(coordination_pool)
    second = PostgresCoordination(coordination_pool)
    await first.initialize_threshold(0.92)
    await second.initialize_threshold(0.75)
    assert await second.read_threshold() == 0.92
    assert await second.write_threshold(0.8) == 0.8
    assert await first.read_threshold() == 0.8

    await coordination_pool.close()
    with pytest.raises(CoordinationStorageError):
        await first.allow_request("198.51.100.10", "/query", "1/minute", 1, 60)
    with pytest.raises(CoordinationStorageError):
        await first.record_session_attempt("198.51.100.10", succeeded=False)
    with pytest.raises(CoordinationStorageError):
        await first.read_threshold()

    recovered_pool = await asyncpg.create_pool(
        os.environ["PGVECTOR_TEST_DATABASE_URL"], min_size=1, max_size=2
    )
    try:
        recovered = PostgresCoordination(recovered_pool)
        assert await recovered.read_threshold() == 0.8
        assert await recovered.allow_request(
            "198.51.100.10", "/query", "1/minute", 1, 60
        )
    finally:
        await recovered_pool.close()


@pytest.mark.asyncio
async def test_two_apps_share_rate_lockout_and_threshold(
    coordination_pool: Pool,
) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        cache_backend="memory",
        coordination_backend="postgres",
        database_url=os.environ["PGVECTOR_TEST_DATABASE_URL"],
        database_migration_mode="external",
        auth_mode="token",
        auth_principals=[
            {
                "name": "admin",
                "token_sha256": sha256(b"valid-token").hexdigest(),
                "role": "admin",
                "namespaces": ["*"],
            }
        ],
        allowed_origins=["http://localhost:5173"],
        rate_limit="2/minute",
    )
    first_app, second_app = create_app(settings), create_app(settings)
    headers = {"Authorization": "Bearer valid-token"}
    async with (
        first_app.router.lifespan_context(first_app),
        second_app.router.lifespan_context(second_app),
        AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as first,
        AsyncClient(
            transport=ASGITransport(app=second_app), base_url="http://test"
        ) as second,
    ):
        assert (
            await first.get("/api/v1/cache/stats", headers=headers)
        ).status_code == 200
        assert (
            await second.get("/api/v1/cache/stats", headers=headers)
        ).status_code == 200
        assert (
            await first.get("/api/v1/cache/stats", headers=headers)
        ).status_code == 429

        assert (
            await first.put(
                "/api/v1/cache/threshold",
                headers=headers,
                json={"threshold": 0.8},
            )
        ).status_code == 200
        threshold = await second.get("/api/v1/cache/threshold", headers=headers)
        assert threshold.json() == {"threshold": 0.8}
        bypassed = await second.post(
            "/api/v1/query",
            headers=headers,
            json={"prompt": "threshold test", "cache_enabled": False},
        )
        assert bypassed.status_code == 200
        assert bypassed.json()["similarity_threshold"] == 0.8

        invalid = {"Authorization": "Bearer invalid-token"}
        assert (
            await first.get("/api/v1/auth/session", headers=invalid)
        ).status_code == 401
        assert (
            await second.get("/api/v1/auth/session", headers=invalid)
        ).status_code == 401
        assert (
            await first.get("/api/v1/auth/session", headers=invalid)
        ).status_code == 429
        assert (
            await second.get("/api/v1/auth/session", headers=headers)
        ).status_code == 429


@pytest.mark.asyncio
async def test_runtime_role_can_use_coordination_tables(
    coordination_pool: Pool,
) -> None:
    role = f"semantix_coord_{uuid4().hex[:12]}"
    password = uuid4().hex
    async with coordination_pool.acquire() as connection:
        await connection.execute(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
    try:
        await grant_runtime_privileges(coordination_pool, role)
        runtime_pool = await asyncpg.create_pool(
            os.environ["PGVECTOR_TEST_DATABASE_URL"],
            user=role,
            password=password,
            min_size=1,
            max_size=1,
        )
        try:
            coordinator = PostgresCoordination(runtime_pool)
            await coordinator.initialize_threshold(0.92)
            assert await coordinator.read_threshold() == 0.92
            assert await coordinator.allow_request(
                "198.51.100.40", "/query", "1/minute", 1, 60
            )
            assert (
                await coordinator.record_session_attempt(
                    "198.51.100.40", succeeded=False
                )
                is None
            )
        finally:
            await runtime_pool.close()
    finally:
        async with coordination_pool.acquire() as connection:
            await connection.execute(f'DROP OWNED BY "{role}"')
            await connection.execute(f'DROP ROLE "{role}"')
