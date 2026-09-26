from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asyncpg.pool import Pool

from app.benchmark.infrastructure import database as evaluation_database
from app.cache.infrastructure import database as cache_database
from app.core.config import Settings
from app.core.exceptions import (
    CacheStorageError,
    CoordinationStorageError,
    DatabaseStorageError,
    EvaluationDatasetStorageError,
    EvaluationRunHistoryStorageError,
)
from app.infrastructure import coordination_database
from app.infrastructure.database import create_pool


@asynccontextmanager
async def database_pool_lifespan(settings: Settings) -> AsyncIterator[Pool | None]:
    if not settings.database_required:
        yield None
        return

    error_type: (
        type[DatabaseStorageError]
        | type[CacheStorageError]
        | type[CoordinationStorageError]
        | type[EvaluationDatasetStorageError]
        | type[EvaluationRunHistoryStorageError]
    )
    if settings.cache_backend == "pgvector":
        error_type = CacheStorageError
    elif settings.evaluation_dataset_storage == "postgres":
        error_type = EvaluationDatasetStorageError
    elif settings.coordination_backend == "postgres":
        error_type = CoordinationStorageError
    else:
        error_type = EvaluationRunHistoryStorageError
    pool = await create_pool(
        settings.database_dsn,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        connect_timeout=settings.database_connect_timeout_seconds,
        command_timeout=settings.database_command_timeout_seconds,
        error_type=error_type,
    )
    try:
        if settings.database_migration_mode == "auto":
            if settings.coordination_backend == "postgres":
                await coordination_database.apply_migrations(pool)
            if settings.cache_backend == "pgvector":
                await cache_database.apply_migrations(pool)
            if (
                settings.evaluation_dataset_storage == "postgres"
                or settings.evaluation_run_history_storage == "postgres"
            ):
                await evaluation_database.apply_migrations(pool)
        yield pool
    finally:
        await pool.close()
