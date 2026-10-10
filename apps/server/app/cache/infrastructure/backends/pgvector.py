"""Server presentation constructor; all cache semantics belong to PgVectorStore."""

import json
from hashlib import sha256

from asyncpg.pool import Pool

from app.cache.domain.protocols import CacheEventRecorder
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from semantix_cache import EmbeddingSpace
from semantix_cache.stores.pgvector import PgVectorStore


class PgVectorCacheBackend(OfficialStoreBackend):
    """Compose PgVectorStore with separately scoped server PostgreSQL telemetry."""

    store: PgVectorStore

    def __init__(
        self,
        pool: Pool,
        max_size: int,
        ttl_seconds: float | None,
        *,
        dimensions: int,
        embedding_space: str,
        events: CacheEventRecorder | None = None,
        schema: str = "semantix_cache",
        table_prefix: str = "workbench_",
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        """Bind a package store and counter adapter to the same borrowed pool.

        Storage stays in the official schema/prefix; counters use the existing server
        table with a scope hashed from space, dimensions, schema and prefix. Neither
        construction nor ordinary operations install/adopt schemas. The caller owns
        the pool; the composing lifespan closes the store and any pool it opened.

        Args:
            pool: Already-open pool borrowed by both storage and server telemetry.
            max_size: Official binding-wide entry capacity across namespaces.
            ttl_seconds: Default retention, or None for no default expiry.
            dimensions: Required vector dimensions of the embedding space.
            embedding_space: Compatible-provider/configuration identity.
            events: Optional recorder; MemoryStore event forwarding does not apply here.
            schema: Existing package-owned schema identifier.
            table_prefix: Existing official table binding prefix.
            operation_timeout_seconds: Deadline covering store work and counter waits.
        """
        super().__init__(
            PgVectorStore(
                pool=pool,
                embedding_space=EmbeddingSpace(
                    identity=embedding_space, dimensions=dimensions
                ),
                schema=schema,
                table_prefix=table_prefix,
                max_size=max_size,
                default_ttl_seconds=ttl_seconds,
                operation_timeout_seconds=operation_timeout_seconds,
            ),
            events=events,
            counter_pool=pool,
            operation_timeout_seconds=operation_timeout_seconds,
            counter_scope="official:"
            + sha256(
                json.dumps((embedding_space, dimensions, schema, table_prefix)).encode()
            ).hexdigest(),
        )
