import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import TYPE_CHECKING, cast

from asyncpg.pool import Pool

from app.cache.domain.protocols import CacheBackend, CacheEventRecorder
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.cache.infrastructure.backends.pgvector import PgVectorCacheBackend
from app.cache.infrastructure.database import create_database_pool
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from semantix_cache import EmbeddingSpace, SemantixCacheError

if TYPE_CHECKING:
    from semantix_cache.stores.redis import RedisStore


@asynccontextmanager
async def cache_backend_lifespan(
    settings: Settings,
    *,
    dimensions: int,
    embedding_space: str,
    events: CacheEventRecorder | None = None,
    pool: Pool | None = None,
) -> AsyncGenerator[CacheBackend, None]:
    owned_pool: Pool | None = None
    backend: OfficialStoreBackend | None = None
    try:
        if settings.cache_backend == "memory":
            backend = InMemoryCacheBackend(
                settings.max_cache_size,
                settings.cache_ttl_seconds,
                dimensions=dimensions,
                embedding_space=embedding_space,
                events=events,
            )
        elif settings.cache_backend == "pgvector":
            if pool is None:
                owned_pool = await create_database_pool(settings)
                pool = owned_pool
            pg_backend = PgVectorCacheBackend(
                pool,
                settings.max_cache_size,
                settings.cache_ttl_seconds,
                dimensions=dimensions,
                embedding_space=embedding_space,
                events=events,
                schema=settings.cache_pgvector_schema,
                table_prefix=settings.cache_pgvector_table_prefix,
                operation_timeout_seconds=settings.database_command_timeout_seconds,
            )
            backend = pg_backend
            await pg_backend.store.validate_schema()
            # Validate existing server telemetry separately; never adopt legacy entries.
            await backend.stats(None)
        elif settings.cache_backend == "redis":
            try:
                redis_store = cast(
                    "type[RedisStore]",
                    import_module("semantix_cache.stores.redis").RedisStore,
                )
            except ImportError:
                raise CacheStorageError(
                    "Install the server redis extra for CACHE_BACKEND=redis"
                ) from None
            if settings.redis_url is None:
                raise CacheStorageError("REDIS_URL is required")
            store = await redis_store.connect(
                url=settings.redis_url.get_secret_value(),
                embedding_space=EmbeddingSpace(
                    identity=embedding_space, dimensions=dimensions
                ),
                key_prefix=settings.redis_key_prefix,
                max_size=settings.max_cache_size,
                default_ttl_seconds=settings.cache_ttl_seconds,
                operation_timeout_seconds=settings.redis_operation_timeout_seconds,
                close_timeout_seconds=settings.redis_close_timeout_seconds,
            )
            backend = OfficialStoreBackend(store, events=events)
            await store.validate_schema()
        else:
            raise CacheStorageError("Unsupported cache backend")
        yield backend
    except SemantixCacheError:
        raise CacheStorageError(
            "Official cache setup or operation failed; run explicit setup and verify configuration"
        ) from None
    finally:
        try:
            if backend is not None:
                try:
                    await backend.store.aclose()
                except SemantixCacheError:
                    raise CacheStorageError("Official cache cleanup failed") from None
        finally:
            if owned_pool is not None:
                try:
                    async with asyncio.timeout(
                        settings.database_command_timeout_seconds
                    ):
                        await owned_pool.close()
                except BaseException:
                    owned_pool.terminate()
                    raise
