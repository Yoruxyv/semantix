"""Server presentation adapters over package-owned cache stores.

``official.OfficialStoreBackend`` delegates cache operations and inspection to the
official store, maps HTTP models/errors and maintains server request counters.
``memory.InMemoryCacheBackend`` constructs MemoryStore.
``pgvector.PgVectorCacheBackend`` constructs PgVectorStore using the supplied pool
and configured schema/prefix.
Both extend OfficialStoreBackend. The parent infrastructure factory wraps
RedisStore directly in OfficialStoreBackend; there is no separate Redis backend
module here.

Entries, vectors, revisions, expiry and LRU remain store-owned. Request counters
are separate telemetry: memory/Redis keep them process-local, while pgvector uses
``semantix.cache_namespace_counters``. Storage setup and resource lifetime belong
to the factory/lifespan and explicit setup commands, not this package initializer.
See the backend contract and platform-parity tests for server-facing behavior;
store-specific guarantees remain with ``semantix_cache``.
"""
