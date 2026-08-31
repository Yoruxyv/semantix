from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asyncpg.pool import Pool

from app.cache.domain.protocols import CacheBackend, CacheEventRecorder
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.cache.infrastructure.backends.pgvector import PgVectorCacheBackend
from app.cache.infrastructure.database import apply_migrations, create_database_pool
from app.core.config import Settings


@asynccontextmanager
async def cache_backend_lifespan(
    settings: Settings,
    *,
    dimensions: int,
    embedding_space: str,
    events: CacheEventRecorder | None = None,
    pool: Pool | None = None,
) -> AsyncIterator[CacheBackend]:
    if settings.cache_backend == "memory":
        yield InMemoryCacheBackend(
            settings.max_cache_size,
            settings.cache_ttl_seconds,
            dimensions=dimensions,
            events=events,
        )
        return

    if pool is not None:
        yield PgVectorCacheBackend(
            pool,
            settings.max_cache_size,
            settings.cache_ttl_seconds,
            dimensions=dimensions,
            embedding_space=embedding_space,
            events=events,
        )
        return

    owned_pool = await create_database_pool(settings)
    try:
        if settings.database_migration_mode == "auto":
            await apply_migrations(owned_pool)
        yield PgVectorCacheBackend(
            owned_pool,
            settings.max_cache_size,
            settings.cache_ttl_seconds,
            dimensions=dimensions,
            embedding_space=embedding_space,
            events=events,
        )
    finally:
        await owned_pool.close()
