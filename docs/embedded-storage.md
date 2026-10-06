# Embedded storage and application databases

`semantix-cache` runs in your Python process. It does not require the Semantix
FastAPI server. Its async engine consumes the structural
[`CacheStore` protocol](../packages/cache/src/semantix_cache/protocols.py), not SQL.
The maintained stores are `MemoryStore` and the optional `PgVectorStore`.
The separate `semantix_client` package is the optional/reference HTTP client.

## Choose a store

| Store | Persistence | Dependency | Ownership |
| --- | --- | --- | --- |
| `MemoryStore` | Process-local, non-durable | Default NumPy/Pydantic core | Owns its state and workers |
| `PgVectorStore` | PostgreSQL/pgvector | `semantix-cache[pgvector]` adds asyncpg | Borrows `pool=`; `connect()` creates an owned pool |
| Your `CacheStore` | Your implementation | Your application chooses | Your implementation documents ownership |

MemoryStore is bounded and appropriate for tests, local use and small ephemeral
workloads. The [package quick start](../packages/cache/README.md) is executable
with a demonstration embedder. The
[custom integration example](../packages/cache/examples/custom_integration.py)
runs offline and supplies its own async embedding/generation.

Install the PostgreSQL extra with `python -m pip install 'semantix-cache[pgvector]'`
when published, or install the built local wheel with its `[pgvector]` extra.
Import the adapter explicitly:

```python
from semantix_cache.stores.pgvector import PgVectorStore
```

Root imports load neither asyncpg nor provider HTTP dependencies. Imports and
exports from `semantix_cache` are unchanged by adding persistent storage.

## New PostgreSQL database

Create a database through your normal operator tooling. Install pgvector on the
server and explicitly enable it in this database using an authorized operator:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Use [pgvector's installation instructions](https://github.com/pgvector/pgvector)
for your PostgreSQL deployment. The library never installs extensions. It looks up
and quotes the extension's catalog schema instead of assuming `public` or changing
`search_path`. The adapter supports 1–16,000 vector dimensions. Different vector
sizes can coexist in the same cache tables and are filtered before comparison.

Apply the cache migration as an explicit deployment step with a separately
provided asyncpg migration pool, then start the runtime with its own credentials:

```python
import asyncpg
from semantix_cache.stores.pgvector import PgVectorStore

async def initialize(runtime_pool, migration_dsn, embedding_space):
    store = PgVectorStore(pool=runtime_pool, embedding_space=embedding_space)
    try:
        async with asyncpg.create_pool(
            migration_dsn, min_size=1, max_size=1,
            timeout=10, command_timeout=30,
        ) as migration_pool:
            await store.initialize_schema(migration_pool=migration_pool)
        await store.validate_schema()
    finally:
        await store.aclose()  # Neither supplied pool is closed by the store.
```

Construction, `connect()`, validation and normal cache operations perform no DDL.
An absent or incompatible schema raises a typed error; it never falls back to memory.
For external deployment control, call this initialization from your migration job
rather than application startup. The SQL template is packaged at
`semantix_cache.stores.migrations/0001_cache.sql`; it contains quoted-layout
placeholders and is not a standalone unrendered SQL script. The explicit
initializer renders it, applies it transactionally and records its checksum.

## Existing application database

Keep your application tables. Use the default dedicated `semantix_cache` schema,
or configure `schema="support_cache"` and optionally `table_prefix="answers_"`.
An existing schema is allowed when the three selected cache table names are free.
Only those owned tables, their constraints and scope index are created. There is
no automatic drop, recreation, adoption, or migration of unrelated application data.
The official server's `semantix` schema and migrations remain separate.

Schema names must match `[a-z_][a-z0-9_]{0,62}` in ASCII. Prefixes may be empty or
match the same pattern, and every complete prefix-plus-object name must fit 63
characters. `pg_*` and `information_schema` schemas are rejected. Identifiers are
quoted after validation; prompt, response, namespace, keys and identity use bound
parameters. No user payload becomes SQL syntax.

The owned objects are `<prefix>schema_migrations`, `<prefix>binding_state`,
`<prefix>cache_entries`, and `<prefix>scope_idx`. Tables have ownership markers.
Initialization takes transaction-scoped advisory locks for schema creation and
the selected prefix;
concurrent initialization is idempotent. The migration ledger requires exactly the
known version and packaged checksum. Unmarked collisions, partial layouts and
mismatches fail before cache writes. Do not edit the shipped migration after applying
it, or manually copy server tables into this schema. Use a fresh schema/prefix when
an incompatible layout exists. Validation checks markers/version/checksum; database
administrators remain responsible for preventing out-of-band schema tampering.

Migration credentials need `CREATE` on the database when creating a schema, or
`USAGE`/`CREATE` on an existing target schema, plus ownership of the created tables
and access to the extension schema/type/functions. Extension installation may
require stronger operator privileges and is a separate action.
Runtime credentials need `USAGE` on the cache and vector-extension schemas,
`SELECT` on the ledger, and `SELECT, INSERT, UPDATE, DELETE` on binding/entry tables.
They need no schema-creation or table-creation privilege. Configure grants through
your deployment tooling; do not grant access to unrelated application tables.

## Persistent customer-support example

The [executable example](../packages/cache/examples/persistent_support.py) uses
application-owned async embedding/generation and an owned persistent pool. Its
small deterministic embedder demonstrates wiring; substitute a language model
with a stable identity before real use. No Semantix server process is involved.

From `packages/cache`, supply `SEMANTIX_CACHE_DATABASE_URL` through your secret
manager/environment. For the explicit deployment step also supply
`SEMANTIX_CACHE_MIGRATION_DATABASE_URL` with authorized migration credentials:

```text
uv sync --locked --extra dev
uv run --no-sync python -m examples.persistent_support --initialize
uv run --no-sync python -m examples.persistent_support
```

The second run validates and reuses the existing schema and persisted cache.
On a disposable local database the same operator DSN can serve both demonstration
roles; production should use separate grants. The same commands apply to a new
database or an existing application database after extension installation.
Never print DSNs or put credentials in source control.

## Data, search and retention

Each store binds immutable `EmbeddingSpace(identity=..., dimensions=...)`. Identity
must distinguish model/revision/dimensions/preprocessing and contain no secrets.
Each operation filters that identity, dimension, concrete namespace and expiry.
Direct `put()` callers are responsible for using entries from the declared space.
Namespaces partition data; your application still performs authorization.

Search is exact cosine over eligible rows; no ANN index or recall approximation is
used. Scores are `1 - cosine_distance`, clamped to `[-1, 1]`; the facade applies its
inclusive threshold (default 0.92). pgvector uses float32 storage, so scores can
differ slightly from NumPy float64 near a threshold. Evaluate the threshold for
your embeddings/workload. Ties use ascending `created_at`, then canonical key.

Defaults are 500 entries per identity/dimension binding, at most 100,000, and a
3,600-second TTL. Capacity and confirmed-hit LRU span the binding's namespaces.
Search does not update LRU. Writes serialize per binding, upsert atomically and
remove overflow before committing; at most 500 expired rows are explicitly cleaned
per write, and overflow removal remains bounded by configured capacity.

A per-write TTL must be positive, finite and at most 31,536,000 seconds. `None`
inherits the store default; a default of `None` means no expiry. A finite default
caps requested retention. PostgreSQL's clock starts TTL at the write; expiry is
inclusive at the deadline. Replacement resets TTL; hits never extend it.
MemoryStore uses its monotonic clock instead. UTC `expires_at` is metadata, not a
second client-side expiry authority. Deletion of expired data may happen later;
expired rows cannot be returned or confirmed.

Candidate snapshots are detached immutable domain values. Persisted `created_at`
is also a strictly increasing revision per binding, including reinsertion after
clear/delete. `record_hit()` atomically checks namespace, binding, expiry and the
expected revision; stale confirmations return `False` and do not increment hit
metadata. Successful confirmations update `hit_count`, `last_accessed_at` and LRU,
without changing revision or expiry. Clear/delete affect only the specified scope.

Prompts are canonical 1–2,000 character strings; responses are nonempty, bounded to
100,000 characters. PostgreSQL text cannot contain NUL: a response with NUL is
rejected instead of silently changed. Space identity is limited to 1,024 characters
and cannot contain NUL. Invalid or nonfinite vectors and wrong dimensions are
rejected before driver work. Returned database payloads are validated again.

## Connections, cancellation and failures

Reuse one store/pool across requests. `PgVectorStore(pool=..., embedding_space=...)`
requires an actual asyncpg pool, not a transaction-bound connection. It borrows the
pool. `await PgVectorStore.connect(dsn=..., embedding_space=...)` owns its created
pool, with default initial size 1, maximum 5; accepted bounds are 1–100. It opens
connections without DDL. See the [asyncpg pool API](https://magicstack.github.io/asyncpg/current/api/index.html)
for application-owned pool configuration, including idle lifetime and TLS.

Startup has a total 10-second default deadline. Operations include acquisition,
commands, transaction completion and release within the default 30-second deadline.
Owned-pool close defaults to 30 seconds. Timeouts must be positive finite numbers
up to 86,400 seconds. Cancellation propagates; failed writes/migrations roll back
and release acquired connections. Close during an admitted operation raises
`CacheBusyError` and leaves the store open. Drain or cancel work before close;
closed stores cannot reopen, and repeated close is harmless.

Async context managers close the owned store resources. `AsyncSemanticCache` borrows
its store/embedder/generator and does not close them. A borrowed pool stays open even
when its store closes. Owned pool close failure/cancellation terminates remaining
owned connections and seals the store. Expected driver failures become safe typed
`CacheStoreError`/`CacheTimeoutError`; configuration errors are separate. Raw DSNs,
server error detail and payloads are excluded from public exception chains. Unexpected
programming errors propagate. There is no automatic replay: a connection loss at
commit may leave outcome uncertain, so application recovery must account for that.
Your own driver callbacks/logging and domain serialization still require care.

## Custom database or vector service

Implement the exact protocol; inheritance and registration are unnecessary:

```python
from collections.abc import Sequence
from datetime import datetime
from semantix_cache import CacheEntry, CacheMatch, EmbeddingSpace

class CompanyCacheStore:
    @property
    def embedding_space(self) -> EmbeddingSpace: ...
    @property
    def default_ttl_seconds(self) -> float | None: ...
    async def find_nearest(self, embedding: Sequence[float], *, namespace: str) -> CacheMatch | None: ...
    async def record_hit(self, cache_key: str, *, namespace: str, expected_created_at: datetime) -> bool: ...
    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None: ...
    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool: ...
    async def clear(self, *, namespace: str) -> int: ...
    async def aclose(self) -> None: ...
```

This is an interface sketch, not a functional backend. The independent
[company-store example](../packages/cache/examples/custom_store.py) implements
it without wrapping/subclassing either built-in store. It is process-local demo
storage; replace its dictionary with your own infrastructure. Run it with
`uv run --no-sync python -m examples.custom_store`, and inject it into
`AsyncSemanticCache(embedder=my_embedder, store=my_store)`.

For MySQL, Redis, Qdrant, Weaviate, Milvus, SQLite extensions or proprietary services,
verify these ten requirements before choosing an implementation:

1. **Representation:** bounded numeric vectors, finite components, exact dimensions,
   normalization and stable space identity. Database availability alone is insufficient.
2. **Metric:** cosine similarity in `[-1, 1]`; translate distance explicitly. Define
   exact search/ties, or disclose any approximate recall limitation.
3. **Threshold:** return the nearest eligible candidate even below threshold; the
   facade applies inclusive eligibility and confirms a candidate before returning it.
4. **Namespace:** filter a concrete namespace before ranking; scoped delete/clear.
5. **Space:** filter identity and dimension before comparison; never match across spaces.
6. **TTL:** authoritative store clock, inherited/capped retention, non-sliding hits and
   atomic expiry checks, including expired candidates between search and confirmation.
7. **Updates:** validate immutable snapshots, canonical keys, monotonic revisions and
   truthful capacity/upsert results. Preserve stale detection across delete/clear.
8. **Concurrency:** atomic revision/expiry confirmation and metadata; transactional
   writes/eviction where supported; bounded failure/cancellation cleanup, no blind replay.
9. **Lifecycle:** finite I/O deadlines, explicit supplied/owned resources, safe typed
   errors, busy-close and idempotent close; do not block the event loop.
10. **Conformance:** run the [developer kit](cache-store-conformance.md) with your
    factory and authoritative expiry fixture; add connection/transaction failure cases.

Only shipped, tested adapters are maintained. There is no first-party MySQL adapter.
A deployment without suitable vector similarity cannot satisfy semantic lookup just
because it supports SQL. Custom embedding adapters and generation callables remain
available for providers/versions whose external APIs change independently.

## Validation and adapter-author evidence

The [developer conformance kit](cache-store-conformance.md) runs against
MemoryStore, PgVectorStore and the independent example through the maintained
[store suite](../packages/cache/tests/test_store_conformance.py). It covers empty/exact/similar
search, threshold misses, isolation, dimensional validation, expiry, revisions, scoped
mutation, LRU, concurrency and close. PostgreSQL-specific
[tests](../packages/cache/tests/test_pgvector.py) exercise persistence, existing
application data, runtime roles without DDL, migrations/checksums, rollback,
resource ownership, cancellation and deadlines.

Use only a disposable PostgreSQL database for tests: the fixtures install the vector
extension, create UUID-named test schemas/roles, then remove their owned objects.
Supply `PGVECTOR_TEST_DATABASE_URL` through the environment, then run from the package:

```text
uv run --no-sync pytest --cov=semantix_cache
uv run --no-sync mypy src tests examples
```

Without the test DSN, database cases skip; that is insufficient to validate a
PostgreSQL release. CI runs the full suite with a pinned pgvector service on each
supported Python version, retains the coverage gate, and tests migrations/persistence
from the installed wheel. pytest and driver typing stubs stay development-only.
