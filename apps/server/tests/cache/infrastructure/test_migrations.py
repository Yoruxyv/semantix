import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
from asyncpg.pool import Pool

from app.cache.infrastructure import database
from app.cache.infrastructure.database import (
    Migration,
    apply_migrations,
    grant_runtime_privileges,
    load_migrations,
)
from app.core.exceptions import CacheStorageError

pytestmark = pytest.mark.pgvector


@pytest.fixture
async def migration_pool() -> AsyncIterator[Pool]:
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    async with pool.acquire() as connection:
        await connection.execute("DROP SCHEMA IF EXISTS semantix CASCADE")
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_fresh_and_idempotent_migration_apply(migration_pool: Pool) -> None:
    await apply_migrations(migration_pool)
    await apply_migrations(migration_pool)

    async with migration_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT version, checksum
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )

    migrations = load_migrations()
    assert [(row["version"], row["checksum"]) for row in rows] == [
        ("0001", migrations[0].checksum)
    ]


@pytest.mark.asyncio
async def test_migration_checksum_mismatch_is_rejected(
    migration_pool: Pool,
) -> None:
    await apply_migrations(migration_pool)
    async with migration_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = $1
            WHERE version = '0001'
            """,
            "0" * 64,
        )

    with pytest.raises(CacheStorageError, match="0001 checksum mismatch"):
        await apply_migrations(migration_pool)


@pytest.mark.asyncio
async def test_verified_pre_checksum_row_is_backfilled(
    migration_pool: Pool,
) -> None:
    await apply_migrations(migration_pool)
    async with migration_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = NULL
            WHERE version = '0001'
            """
        )

    await apply_migrations(migration_pool)

    async with migration_pool.acquire() as connection:
        checksum = await connection.fetchval(
            """
            SELECT checksum
            FROM semantix.schema_migrations
            WHERE version = '0001'
            """
        )
    assert checksum == load_migrations()[0].checksum


@pytest.mark.asyncio
async def test_unverifiable_pre_checksum_row_is_rejected(
    migration_pool: Pool,
) -> None:
    await apply_migrations(migration_pool)
    async with migration_pool.acquire() as connection:
        await connection.execute("DROP TABLE semantix.cache_namespace_counters")
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = NULL
            WHERE version = '0001'
            """
        )

    with pytest.raises(CacheStorageError, match="schema could not be verified"):
        await apply_migrations(migration_pool)


@pytest.mark.asyncio
async def test_concurrent_migration_applicators_serialize(
    migration_pool: Pool,
) -> None:
    await asyncio.gather(
        apply_migrations(migration_pool),
        apply_migrations(migration_pool),
    )

    async with migration_pool.acquire() as connection:
        count = await connection.fetchval(
            "SELECT COUNT(*) FROM semantix.schema_migrations"
        )
    assert count == 1


@pytest.mark.asyncio
async def test_multiple_migration_versions_upgrade_in_order(
    migration_pool: Pool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = load_migrations()[0]
    await apply_migrations(migration_pool)
    second = Migration(
        version="0002",
        sql="CREATE TABLE semantix.phase_b_upgrade (id INTEGER PRIMARY KEY);",
    )
    monkeypatch.setattr(
        database,
        "load_migrations",
        lambda: (first, second),
    )

    await apply_migrations(migration_pool)

    async with migration_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT version, checksum
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )
        upgraded = await connection.fetchval(
            "SELECT to_regclass('semantix.phase_b_upgrade') IS NOT NULL"
        )
    assert [(row["version"], row["checksum"]) for row in rows] == [
        ("0001", first.checksum),
        ("0002", second.checksum),
    ]
    assert upgraded is True


@pytest.mark.asyncio
async def test_runtime_role_receives_required_cache_privileges(
    migration_pool: Pool,
) -> None:
    await apply_migrations(migration_pool)
    role_name = f"semantix_test_{uuid4().hex[:12]}"
    password = uuid4().hex
    database_url = os.environ["PGVECTOR_TEST_DATABASE_URL"]

    async with migration_pool.acquire() as connection:
        await connection.execute(
            f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{password}'"
        )
    try:
        await grant_runtime_privileges(migration_pool, role_name)
        runtime = await asyncpg.connect(
            database_url,
            user=role_name,
            password=password,
        )
        try:
            await runtime.execute(
                """
                INSERT INTO semantix.cache_namespace_counters (
                    embedding_space,
                    namespace
                )
                VALUES ('role-test', 'default')
                """
            )
            assert (
                await runtime.fetchval(
                    """
                    SELECT hits
                    FROM semantix.cache_namespace_counters
                    WHERE embedding_space = 'role-test'
                    """
                )
                == 0
            )
            await runtime.execute(
                """
                UPDATE semantix.cache_namespace_counters
                SET hits = 1
                WHERE embedding_space = 'role-test'
                """
            )
            await runtime.execute(
                """
                DELETE FROM semantix.cache_namespace_counters
                WHERE embedding_space = 'role-test'
                """
            )
        finally:
            await runtime.close()
    finally:
        async with migration_pool.acquire() as connection:
            await connection.execute(f'DROP OWNED BY "{role_name}"')
            await connection.execute(f'DROP ROLE IF EXISTS "{role_name}"')
