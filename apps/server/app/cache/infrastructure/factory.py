"""Compose the selected package store for the lifetime of server cache services.

Normal startup binds/validates existing storage; explicit setup owns cache
migrations and binding initialization. The returned server adapter adds
presentation and telemetry while the package store remains authoritative.
"""

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
    """Yield a configured cache adapter and release resources owned by this scope.

    Memory creates a process-local store. PostgreSQL borrows a supplied pool or
    opens its own, validates the official schema, then separately reads server
    telemetry. Redis connect owns its client/pool and validates the existing marked
    binding. Neither persistent branch installs or adopts a cache schema.

    On exit or failed setup, close any assigned store first. A nested finally then
    attempts to close only a pool opened here, under the database command timeout;
    a failed/cancelled pool close terminates it and re-raises. Supplied pools remain
    caller-owned. Store cleanup errors can replace an earlier failure, and partial
    startup/cancellation does not guarantee successful cleanup. Redis connect owns
    cleanup before it returns a store. Application query services borrow this
    backend while the enclosing lifespan is active.

    Args:
        settings: Validated backend, binding, capacity, TTL and timeout configuration.
        dimensions: Required dimension count of the selected embedding provider.
        embedding_space: Provider/configuration identity binding compatible vectors.
        events: Optional synchronous application eviction/expiration recorder.
        pool: Optional borrowed application pool for PostgreSQL storage and telemetry.

    Yields:
        Server CacheBackend adapting one package-owned store.

    Raises:
        CacheStorageError: Unsupported/missing backend configuration or translated
            official setup/operation/cleanup failures. Other failures and cancellation
            propagate; this context also handles official errors thrown from its body.
    """
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
