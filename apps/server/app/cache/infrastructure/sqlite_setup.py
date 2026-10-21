"""Operator-only SQLite binding setup; runtime startup only connects."""

import asyncio

from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.providers.factory import create_default_provider_registry
from app.providers.registry import EmbeddingMetadata
from semantix_cache import EmbeddingSpace, SemantixCacheError
from semantix_cache.stores.sqlite import SQLiteStore


async def initialize_sqlite(settings: Settings, *, metadata: EmbeddingMetadata) -> None:
    """Use immutable resolved metadata without constructing providers or doing inference.

    Setup uses the public package operation timeout for setup and its owned close.
    Runtime connect/close timeout settings apply separately to normal application use.
    Filesystem privacy is operator-owned; this command does not certify permissions.
    """
    if settings.cache_backend != "sqlite" or settings.cache_sqlite_path is None:
        raise CacheStorageError(
            "SQLite setup requires CACHE_BACKEND=sqlite and CACHE_SQLITE_PATH"
        )
    try:
        await SQLiteStore.initialize_schema(
            settings.cache_sqlite_path.get_secret_value(),
            embedding_space=EmbeddingSpace(
                identity=metadata.space, dimensions=metadata.dimensions
            ),
            max_size=settings.max_cache_size,
            default_ttl_seconds=settings.cache_ttl_seconds,
            operation_timeout_seconds=settings.cache_sqlite_operation_timeout_seconds,
        )
    except SemantixCacheError:
        raise CacheStorageError(
            "SQLite setup failed; verify local runtime, file and binding configuration"
        ) from None


async def run() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue] - environment supplies required fields
    metadata = (
        create_default_provider_registry(settings)
        .resolve(settings.embedding_provider, settings.generation_provider)
        .embedding_metadata
    )
    await initialize_sqlite(settings, metadata=metadata)


if __name__ == "__main__":
    asyncio.run(run())
