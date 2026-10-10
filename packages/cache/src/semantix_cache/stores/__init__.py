"""Storage choices for the embedded semantic-cache engine.

``AsyncSemanticCache`` depends on the structural ``CacheStore`` protocol, not a
database driver. A store holds entries for its declared ``EmbeddingSpace``;
search, hit confirmation, deletion and clearing are scoped to a namespace. The
engine applies the similarity threshold, generation policy and response evidence.
Store implementations enforce retention, capacity and safe concurrent mutations.

Available implementations
-------------------------
``semantix_cache.MemoryStore``
    Bounded process-local memory with exact cosine search and non-sliding TTL.
    Import it from the package root; no database dependency is required.
``semantix_cache.stores.pgvector.PgVectorStore``
    Optional persistence in an application-owned PostgreSQL schema/table prefix.
    Install ``semantix-cache[pgvector]`` and import the class explicitly::

        from semantix_cache.stores.pgvector import PgVectorStore

    Operators install the vector extension. Initialize the marked schema through
    ``await store.initialize_schema(migration_pool=authorized_pool)`` and use
    ``await store.validate_schema()`` to check it. Construction, ``connect()`` and
    ordinary cache operations do not create database objects. Embedded tables and
    migrations are independent of the server's storage schema.

``semantix_cache.stores.redis.RedisStore``
    Optional three-key binding on a direct writable standalone Redis Open Source
    primary >=8.10.2,<8.11 using noeviction. Install ``semantix-cache[redis]`` and
    import explicitly::

        from semantix_cache.stores.redis import RedisStore

    Use authorized ``initialize_schema(initialization_client=...)`` during
    deployment, then ``validate_schema()`` at startup. Neither construction nor
    ``connect()`` initializes or adopts keys. Prefix and space identity/dimensions
    select the marked meta/entries/LRU keys; capacity and TTL policy must match
    the existing descriptor. Applications authorize namespaces and operators own
    persistence, backups and ACLs. Redis Cluster/Sentinel/failover are unsupported.

    ``RedisStore(client=...)`` borrows the client/pool; ``await RedisStore.connect(...)``
    creates owned resources. After draining operations and retained numerical
    workers, ``aclose()``/async context exit seals the store. Owned close shares a
    shielded bounded cleanup task; borrowed resources stay caller-owned and keys
    remain. See ``redis.py`` for validation, decoding, deadlines and client
    lifecycle; ``_redis_scripts.py`` owns fixed Lua bytes, layouts and checksums.
    Change Redis behavior with its conformance/fault/inspection tests and the guide:
    https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-redis.md.

Ownership and custom stores
---------------------------
The cache borrows its store. Close the cache before the store after draining or
cancelling work. ``PgVectorStore(pool=...)`` borrows the supplied asyncpg pool;
``await PgVectorStore.connect(dsn=..., embedding_space=...)`` creates an owned pool.
Its async context manager/``aclose()`` closes an owned pool, leaving borrowed pools
for the application to close. MemoryStore and PgVectorStore both support async
context management.

A custom store implements ``CacheStore`` directly; no subclass or registration is
needed. Preserve namespace/space isolation, TTL, detached candidates and atomic
revision-aware hit confirmation. See ``CacheEntry``, ``CacheMatch`` and the
repository's ``examples/custom_store.py`` and store conformance tests.

Importing this namespace does not import adapters, asyncpg or redis-py, select a
store, connect to a database or initialize a schema. Pgvector uses float32 vectors, so
scores near a threshold can differ slightly from MemoryStore's float64 scores.
The storage guide describes setup, failure semantics and the complete contract:
https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-storage.md.
"""
