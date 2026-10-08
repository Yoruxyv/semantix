# Server storage configuration

The optional server/workbench selects the same official stores as the embedded
package. `CACHE_BACKEND` accepts `memory`, `pgvector` or `redis`. Qdrant is not
selectable. Monitor queries and Cache Inspector use the active official store;
the server keeps no parallel cache entries, vectors, revisions, expiry or LRU
index. Evaluations create a separate run-local MemoryStore and never use this live
store. Similarity matching is unchanged; see [accuracy limitations](../semantic-accuracy-limitations.md).

## Choose and configure

| Selection | Required configuration | Setup and lifecycle |
| --- | --- | --- |
| `memory` | No storage credentials | Process-local MemoryStore; entries disappear when the process stops |
| `pgvector` | `DATABASE_URL`; optional `CACHE_PGVECTOR_SCHEMA` and `CACHE_PGVECTOR_TABLE_PREFIX` | Explicit operator setup; one shared server PostgreSQL pool, borrowed by PgVectorStore |
| `redis` | `REDIS_URL`; optional `REDIS_KEY_PREFIX` | Install the server `redis` extra and explicitly initialize the binding; server owns and closes the Redis client/pool |

`MAX_CACHE_SIZE` and `CACHE_TTL_SECONDS` retain their existing semantics. Memory
and Redis support at most 5,000 entries; Redis additionally limits the vector
projection to 64 MiB (`max_size × dimensions × 8`). PostgreSQL uses the package's
persisted binding capacity rules. Changing Redis capacity/default TTL for an
existing binding fails validation rather than silently adopting new settings.
Namespaces, embedding identities/dimensions, policy flags and final atomic
revision/expiry confirmation remain authoritative in storage. Hits never renew TTL.

Copy the maintained [server environment example](../../apps/server/.env.example).
Storage placeholders deliberately use `.invalid` hosts and replacement credentials;
they are not working connections. Supply actual credentials through server-side
environment or secret handling. Do not compile them into `VITE_*`, browser assets,
diagnostics, logs or exception messages. Readiness and diagnostics disclose the
store kind only, never its URL, credentials or private model identity.

From `apps/server`, `uv sync --locked --extra redis` installs Redis support for
local server use. Container server images include it. The embedded core still
does not import redis-py or asyncpg; the HTTP client gains no database dependency.

## PostgreSQL: setup and legacy transition

Normal startup validates the package-owned schema; it never initializes or adopts
cache tables, even with `DATABASE_MIGRATION_MODE=auto`. That setting still controls
other enabled PostgreSQL features. Use the explicit migration job with a migration
role and a separately named runtime role:

```bash
python -m app.infrastructure.migrate
```

Run from `apps/server` after securely configuring `MIGRATION_DATABASE_URL`,
`DATABASE_RUNTIME_ROLE`, `CACHE_BACKEND=pgvector` and matching schema/prefix options.
The job enables pgvector, preserves the existing server migration ledger and
creates marked package-owned tables. Runtime receives read-only ledger access
and data privileges, not migration authority. Hardened Compose already runs this
one-shot job before starting its two backends; its topology remains unchanged.

Defaults are schema `semantix_cache`, prefix `workbench_`:

- `semantix_cache.workbench_schema_migrations`: package version/checksum ledger;
- `semantix_cache.workbench_binding_state`: embedding-space capacity/access clock;
- `semantix_cache.workbench_cache_entries`: authoritative cache entries and metadata.

The old `semantix.cache_entries` table is a different layout. Setup leaves its
rows untouched, does not copy or reinterpret embeddings/expiry/revisions, and
does not serve its answers. The new binding starts empty. Back up the database
before changing binaries; allow responses to repopulate the new cache. No safe
automatic data conversion has been demonstrated. Do not rename old tables into
the new layout or point the package prefix at unmarked legacy tables. Missing,
unowned or checksum-incompatible package tables stop startup with a safe error.

`semantix.cache_namespace_counters` remains server telemetry only, scoped to the
active space/dimensions/schema/prefix. Existing legacy counters are preserved;
new official bindings start fresh counters. Counters never decide eligibility,
expiry, revisions or answer reuse. Rolling back binaries returns to the preserved
legacy cache and can expose older answers; review freshness/context before rollback.
Do not delete the legacy table as part of this transition.

See [PostgreSQL setup](pgvector.md) and [embedded storage](../embedded-storage.md)
for ownership and maintenance details.

## Redis: setup, permissions and recovery

Use direct standalone Redis 8.10.2 with `noeviction`; hosted/cluster/replica
support is not inferred from a URL. Read the [Redis store contract](../embedded-redis.md)
for the supported version range, exact scan ceiling and ACL commands.

Configure the same provider metadata, dimensions, prefix, capacity and TTL as the
runtime. Supply `REDIS_INITIALIZATION_URL` separately to the operator command:

```bash
python -m app.cache.infrastructure.setup
```

It resolves configured embedding metadata without calling a provider. It creates
the binding explicitly using initialization authority, then closes its client.
Remove the initialization URL from the runtime environment. Ordinary server
startup uses `REDIS_URL`, validates the descriptor and performs no initialization.
Wrong capacity, TTL, version or unowned keys fail rather than falling back to memory.
`REDIS_OPERATION_TIMEOUT_SECONDS` and `REDIS_CLOSE_TIMEOUT_SECONDS` bound network
operations and cleanup. The server propagates cancellation; caller-supplied package
clients remain borrowed and must be closed by their owner.

Redis persistence is operator-managed. AOF/RDB retention, backup, restore, ACLs,
TLS and eviction configuration remain deployment responsibilities. Redis does not
become an authoritative query counter service: its server hit/miss totals are
process-local telemetry; Inspector hit/access metadata comes from the actual store.

## Inspector and diagnostics

The three concrete stores offer optional `inspect_entries` and `inspect_entry`
observations. The mandatory `CacheStore` protocol is unchanged. These methods
exclude expired entries without purging them, recording hits, renewing TTL or
changing LRU. Redis may independently expire hash fields through its native TTL;
inspection does not issue writes. Normal hit confirmation calls the store's
namespace/revision-aware `record_hit` directly, without inspection queries.

Lists expose prompts, cache identifiers and at most 240 response characters,
without vectors or complete long answers. Treat previews as sensitive data. The
server retains its truncated-answer placeholder; an authorized detail request
returns one complete answer. Authentication, roles and namespace access are server
responsibilities. Foreign and missing identifiers receive the same 404 response.
Package callers must enforce authorization before using these optional methods;
namespace strings alone do not authenticate anyone.

`clear_all` is a separate administrative mutation across namespaces in the active
store binding, not an inspection operation. Existing server role and namespace
rules govern clearing and deletion. No parallel entry inventory is maintained.

Memory scans its bounded in-process binding. PostgreSQL counts/ranks scalar
metadata in a read-only repeatable-read transaction, then applies `OFFSET`/`LIMIT`
before projecting previews or a detail answer. Vectors are not selected. Counts,
ranking, prompt search and deep offsets can still scan/sort the active binding;
the page limit does not make those operations constant time.

Redis validates and scans scalar metadata for at most 5,000 binding members. A
normal page decodes at most 100 selected payloads in one read-only Lua call; no
vectors or complete list answers leave Redis. Prompt search requires scanning
payloads because prompts and answers share the existing JSON field. It processes
at most 100 payloads per read-only call, up to the configured binding capacity,
under one operation deadline. Each batch repeats the bounded metadata scan, so
search can cost more than an ordinary page; no separate prompt index is created.

Ordering is deterministic for an unchanged binding. Separate pages are live
observations rather than a shared snapshot: insertion, deletion, hits and expiry
can shift offsets. Redis search batches also observe separate snapshots, so
concurrent changes can affect totals or repeat/omit entries. Refresh after mutations;
do not use Inspector pages as a correctness or authorization lease. Search uses
Python Unicode case folding in Memory/Redis and database `LOWER` in PostgreSQL;
non-ASCII matching depends on the PostgreSQL locale.

Observability eviction/expiry counts are observed process events, not an exact
persistent inventory. Readiness validates access to the selected store. An
unavailable store fails readiness; it is never replaced by an implicit memory cache.

## Local Docker and validation

The development stack keeps memory as the default. Choose the `pgvector` or `redis`
profile only when its corresponding backend is configured. Start that service,
run explicit setup using separately supplied operator configuration, then start
backend/frontend. Development ports and credentials are local conveniences, not
a hardened deployment. The Redis profile enables AOF and `noeviction`; production
Compose remains the existing PostgreSQL topology.

Integration tests use only `PGVECTOR_TEST_DATABASE_URL` and `REDIS_TEST_URL`, never
implicitly a developer's runtime URL. Both must identify disposable services:

```bash
uv run --locked --extra dev --extra redis pytest -m "pgvector or redis"
```

Required CI integration jobs assert that both store parameters run and that no
selected integration test skips. Unit runs exclude those two integration markers.
