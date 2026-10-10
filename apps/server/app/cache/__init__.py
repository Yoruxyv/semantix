"""Server semantic-cache matching, administration and storage boundaries.

``application.service.SemanticCache`` coordinates embedding, compatible candidate
search, threshold eligibility and confirmed-hit evidence. ``domain`` owns keys,
namespaces, models, vector validation and backend protocols. Shared semantic
primitives come from the embedded package through server boundary wrappers; the
server retains its own HTTP contract and administration behavior.

``api`` exposes inspection, mutation and threshold routes; authentication and
namespace authorization remain server-owned. ``infrastructure.factory`` exposes
``cache_backend_lifespan``, which composes official MemoryStore, PgVectorStore or
RedisStore through the server's OfficialStoreBackend adapter. InMemoryCacheBackend
and PgVectorCacheBackend are compatibility constructors over that adapter, not
separate authoritative caches. The lifespan supplies the embedding service and,
when needed, a shared PostgreSQL pool borrowed by PgVectorStore; Redis composition
owns its connected client/pool. Cache lifespan closes the selected store.

The official stores own entries, vectors, revisions, expiry and LRU. The adapter
maps inspection to HTTP models and records request hit/miss telemetry: process-local
for memory/Redis, or in ``semantix.cache_namespace_counters`` for pgvector. Those
counters do not determine cache eligibility or replace store-owned entry metadata.

Filter namespaces and embedding spaces before matching, preserve expiry and
revision-aware hit confirmation, and keep foreign entry details undisclosed.
Persistent cache bindings require explicit operator setup; startup only validates
them. ``infrastructure.database`` initializes the official PostgreSQL schema and
runtime grants, while ``infrastructure.setup`` handles explicit Redis setup.
PgVectorStore's configurable schema/prefix and package ledger are separate from
``semantix.schema_migrations``. Server migration ``0001`` retains the legacy cache
layout and telemetry; preserved legacy entries are not read, converted or adopted.
Store-specific lifecycle, transaction and inspection guarantees belong to each
store's contract; sharing this HTTP adapter does not standardize those guarantees.

Start with the application service and domain protocols, then the selected
backend and focused cache tests. Query generation/policy orchestration belongs to
``app.query``; controlled evaluation caches belong to ``app.benchmark``. See
``docs/guides/platform-storage.md`` and the backend contract/platform-parity tests
before changing storage composition, telemetry or setup.
"""
