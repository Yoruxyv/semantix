"""Compatibility constructor for the server's package-owned memory store."""

from app.cache.domain.protocols import CacheEventRecorder
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from semantix_cache import EmbeddingSpace, MemoryStore


class InMemoryCacheBackend(OfficialStoreBackend):
    """Compose MemoryStore with server presentation and process-local telemetry."""

    def __init__(
        self,
        max_size: int,
        ttl_seconds: float | None,
        *,
        dimensions: int,
        events: CacheEventRecorder | None = None,
        embedding_space: str = "server-memory",
    ) -> None:
        """Create a package MemoryStore; its composing lifespan owns closure.

        Args:
            max_size: Store-wide capacity across namespaces.
            ttl_seconds: Default retention, or None for no default expiry.
            dimensions: Required vector dimensions in this binding.
            events: Optional synchronous MemoryStore eviction/expiration recorder.
            embedding_space: Identity for compatible vectors in this process-local store.
        """
        super().__init__(
            MemoryStore(
                embedding_space=EmbeddingSpace(
                    identity=embedding_space, dimensions=dimensions
                ),
                max_size=max_size,
                default_ttl_seconds=ttl_seconds,
            ),
            events=events,
        )
