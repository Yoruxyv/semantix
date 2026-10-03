from __future__ import annotations

import asyncpg
from asyncpg import Connection
from asyncpg.pool import Pool, PoolConnectionProxy

from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.infrastructure import database as shared_database
from app.infrastructure.database import Migration

MIGRATION_PACKAGE = "app.cache.infrastructure.migrations"
LEGACY_0001_RELATIONS = {
    "semantix.cache_entries",
    "semantix.cache_namespace_counters",
}
LEGACY_0001_COLUMNS = {
    "cache_entries": {
        "embedding_space",
        "embedding_dimensions",
        "cache_key",
        "namespace",
        "prompt",
        "response",
        "embedding",
        "created_at",
        "expires_at",
        "hit_count",
        "last_accessed_at",
    },
    "cache_namespace_counters": {
        "embedding_space",
        "namespace",
        "hits",
        "misses",
    },
}
CACHE_TABLES = (
    "semantix.cache_entries",
    "semantix.cache_namespace_counters",
)


def load_migrations() -> tuple[Migration, ...]:
    return shared_database.load_packaged_migrations(
        (MIGRATION_PACKAGE,),
        label="Cache database",
        error_type=CacheStorageError,
    )


async def create_pool(
    dsn: str,
    *,
    min_size: int,
    max_size: int,
    connect_timeout: float,
    command_timeout: float,
) -> Pool:
    return await shared_database.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        connect_timeout=connect_timeout,
        command_timeout=command_timeout,
        error_type=CacheStorageError,
        error_detail="Could not connect to the configured pgvector database",
    )


async def create_database_pool(settings: Settings) -> Pool:
    return await create_pool(
        settings.database_dsn,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        connect_timeout=settings.database_connect_timeout_seconds,
        command_timeout=settings.database_command_timeout_seconds,
    )


async def _validate_legacy_migration(
    connection: Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record],
    migration: Migration,
) -> bool:
    if migration.version != "0001":
        return False

    relations = {
        str(row["relation"])
        for row in await connection.fetch(
            """
            SELECT relation
            FROM unnest($1::text[]) AS expected(relation)
            WHERE to_regclass(relation) IS NOT NULL
            """,
            sorted(LEGACY_0001_RELATIONS),
        )
    }
    if relations != LEGACY_0001_RELATIONS:
        return False

    rows = await connection.fetch(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'semantix'
          AND table_name = ANY($1::text[])
        """,
        sorted(LEGACY_0001_COLUMNS),
    )
    actual_columns: dict[str, set[str]] = {
        table_name: set() for table_name in LEGACY_0001_COLUMNS
    }
    for row in rows:
        actual_columns[str(row["table_name"])].add(str(row["column_name"]))
    return all(
        required_columns <= actual_columns[table_name]
        for table_name, required_columns in LEGACY_0001_COLUMNS.items()
    )


async def apply_migrations(pool: Pool) -> None:
    await shared_database.apply_migrations(
        pool,
        load_migrations(),
        label="Cache database",
        error_type=CacheStorageError,
        bootstrap_statements=("CREATE EXTENSION IF NOT EXISTS vector",),
        legacy_validators={"0001": _validate_legacy_migration},
    )


async def grant_runtime_privileges(pool: Pool, runtime_role: str) -> None:
    await shared_database.grant_runtime_privileges(
        pool,
        runtime_role,
        CACHE_TABLES,
        error_type=CacheStorageError,
    )


__all__ = [
    "Migration",
    "apply_migrations",
    "create_database_pool",
    "create_pool",
    "grant_runtime_privileges",
    "load_migrations",
]
