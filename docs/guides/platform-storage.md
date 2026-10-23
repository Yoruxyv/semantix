# Server storage configuration

The optional server/workbench selects the same official stores as the embedded
package. `CACHE_BACKEND` accepts `memory`, `pgvector`, `redis`, `sqlite` or `mysql`. Qdrant is not
selectable. Monitor queries and Cache Inspector use the active official store;
the server keeps no parallel cache entries, vectors, revisions, expiry or LRU
index. Evaluations create a separate run-local MemoryStore and never use this live
store. Similarity matching is unchanged; see [accuracy limitations](../reference/semantic-accuracy-limitations.md).

## Choose and configure

| Selection | Required configuration | Setup and lifecycle |
| --- | --- | --- |
| `memory` | No storage credentials | Process-local MemoryStore; entries disappear when the process stops |
| `pgvector` | `DATABASE_URL`; optional `CACHE_PGVECTOR_SCHEMA` and `CACHE_PGVECTOR_TABLE_PREFIX` | Explicit operator setup; one shared server PostgreSQL pool, borrowed by PgVectorStore |
| `mysql` | `CACHE_MYSQL_*` endpoint, TLS, database and runtime credentials | Install the server `mysql` extra; separate explicit operator setup; one owned connection/worker per store |
| `sqlite` | Absolute `CACHE_SQLITE_PATH`; optional `CACHE_SQLITE_*_TIMEOUT_SECONDS` | Explicit local setup; one native server process on trusted local disk |
| `redis` | `REDIS_URL`; optional `REDIS_KEY_PREFIX` | Install the server `redis` extra and explicitly initialize the binding; server owns and closes the Redis client/pool |

`MAX_CACHE_SIZE` and `CACHE_TTL_SECONDS` retain their existing semantics. Memory, SQLite, MySQL
and Redis support at most 5,000 entries; SQLite, MySQL and Redis additionally limit the vector
projection to 64 MiB (`max_size × dimensions × 8`). PostgreSQL uses the package's
persisted binding capacity rules. Changing SQLite, MySQL or Redis capacity/default TTL for an
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

## SQLite: explicit local setup and bounded shutdown

SQLite uses the existing package-owned store, inspection and administration APIs.
It is supported only for one native server process on trusted local disk. The
bundled development Compose launcher rejects it; the hardened multi-replica
Compose deployment remains PostgreSQL-based and does not configure SQLite.
Do not use network mounts, multiple workers, reload mode or ephemeral container
storage. Arbitrary ASGI launchers cannot be certified from application settings.

Configure the same resolved embedding identity/dimensions, capacity and TTL for
setup and runtime. Use an absolute filename under an existing operator-owned
private directory, for example `C:/private/semantix/cache.db` or
`/private/semantix/cache.db`. Set `CACHE_BACKEND=sqlite` and `CACHE_SQLITE_PATH`,
then run from `apps/server` with the same server configuration:

```text
python -m app.cache.infrastructure.sqlite_setup
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Setup resolves provider metadata without constructing providers or calling them.
Custom registrations can call `initialize_sqlite(settings, metadata=resolved_metadata)`
from application-owned operator tooling. Normal startup calls only `connect()`;
it never creates, adopts, repairs or reinitializes a file. No migration between
backends occurs. Missing/incompatible storage fails startup rather than falling
back. Changes to an existing binding's capacity/TTL must not be silently adopted.

The [package runtime and filesystem restrictions](../embedded/storage.md#sqlite-local-file-persistence)
remain authoritative. SQLite requires a supported linked library, not merely a
supported Python version. Capacity is at most 5,000, dimensions at most 16,000 and
`capacity × dimensions × 8 <= 64 MiB`; response/payload memory and disk costs are
additional. The package checks path form, parents, symlinks/reparse points and
binding integrity. It does not certify POSIX permissions or Windows ACL privacy.
Operators must protect the database and WAL/SHM files. Paths stay out of public
errors and diagnostics; clear is not secure erase.

Connect, operation and close timeout defaults are 10, 30 and 30 seconds. Values
must be positive finite seconds at most 86,400. The operator setup command uses
the public package's operation timeout for its setup and owned cleanup; runtime
connect/close settings are separate. SQLite shutdown starts after the existing
QueryService drain. `CACHE_SQLITE_CLOSE_TIMEOUT_SECONDS` is one total application
await budget covering pre-close busy waiting and subsequent public `aclose()`;
it is not two consecutive full budgets. Only pre-close `CacheBusyError` is retried.
Mutations and native-close errors are never retried.

Budget expiry raises a sanitized terminal shutdown error. Cancellation propagates.
Neither outcome establishes resource disposal. If native close has started, its
existing package-owned shielded cleanup may outlive the application await budget;
no server retry task is detached. If work remains busy, the connection/worker may
remain alive without cleanup having started. Operator-controlled process
disposition may be required, and a supervisor may need to force termination.
This does not guarantee bounded process exit. The separately documented exceptional
native-close terminal limitation is unchanged.

Inspector operations retain exact totals or fail under the operation deadline;
Unicode prompt search streams payloads and occupies the single SQLite worker.
Bounded memory is not a maximum-scale completion-time guarantee. Lists and detail
are observational; global clear affects only the active embedding binding.
Hit/miss telemetry is process-local, including when independent PostgreSQL features
are enabled. Entry hit/revision/TTL state remains package-owned and persistent.
SQLite does not disable PostgreSQL coordination, datasets or run history.

Readiness and diagnostics identify the backend as `sqlite` with unchanged response
shapes. Older SDKs/frontends may reject this new enum value; use versions that
recognize it. Real-browser, packaged-install and additional deployment certification
are separate from the HTTP integration tests.

## MySQL: explicit setup and owned connections

Install with `uv sync --locked --extra mysql` from `apps/server`. Server Docker
images include the extra, but this does not certify a MySQL Compose topology.
The bundled development launcher rejects MySQL rather than claiming setup validation;
use explicit operator setup and native server startup for this integration.
Use a dedicated single-primary MySQL Community 8.4.x database with InnoDB and
verified TLS; the [package compatibility boundary and grants](../embedded/mysql.md)
remain authoritative. No MariaDB, managed variants, replicas/failover, DNS dialing
or new server-version claims are implied. The hardened deployment stays PostgreSQL.

Set `CACHE_BACKEND=mysql`, canonical numeric IPv4 `CACHE_MYSQL_ADDRESS`, port
(default 3306), separately verified `CACHE_MYSQL_TLS_HOSTNAME`, absolute trusted
`CACHE_MYSQL_CA_FILE`, dedicated lowercase-ASCII `CACHE_MYSQL_DATABASE` and explicit
runtime `CACHE_MYSQL_USER` / `CACHE_MYSQL_PASSWORD`. Do not reuse `DATABASE_URL`.
Endpoints, CA paths and credentials are secret settings and stay out of diagnostics.
Provision the database, locked verifier account and privileges using the package
guide. Runtime has table DML and verifier EXECUTE, without DDL authority.

For setup only, supply independent `CACHE_MYSQL_SETUP_USER` and
`CACHE_MYSQL_SETUP_PASSWORD`, then run:

```text
python -m app.cache.infrastructure.mysql_setup
```

Remove setup credentials before launching the server. There is no runtime-credential
fallback. Setup resolves embedding metadata without inference/provider construction;
custom operator tooling can call `initialize_mysql(settings, metadata=..., setup_user=...,
setup_password=...)`. Keep embedding identity/dimensions, capacity and TTL identical
at setup and runtime. Startup only connects and validates; missing/incompatible
storage fails closed without initialization, migration, repair or memory fallback.

Connect, operation and close budgets default to 10, 30 and 30 positive finite seconds
(at most 86,400). Setup uses the public package's operation budget for construction
and disposal. After QueryService draining, the server gives public `aclose()` one
total application-await budget (`CACHE_MYSQL_CLOSE_TIMEOUT_SECONDS`), retrying only
documented pre-close busy rejection. Cancellation propagates; expiry is an observable
terminal shutdown error, never successful cleanup. No mutations, uncertain COMMITs
or native-close failures are retried. Package-owned shielded cleanup can outlive the
await budget; no server retry task is detached. Operator-controlled process disposition
may be needed; this is not a bound on native completion or whole-process termination.
Failed construction retains the package's existing bounded cleanup diagnostics and
explicit recovery contract; the server does not automatically retry setup or recovery.

Each store owns a thread-affine synchronous connection/worker; no new pool is added.
Cancelled/expired read transactions can retire the connection; later independent calls
may reopen it under the package contract. Uncertain mutations fault the store rather
than replaying them. Hit/miss telemetry and cold-miss coalescing remain process-local.
Independent PostgreSQL coordination, datasets and history remain configurable.

Inspector uses package-owned read-only consistent snapshots, exact totals, Unicode
casefold search and selected-page decoding. Prompt search streams one payload at a
time but occupies the worker and can require a full bounded-capacity scan. Bounded
memory is not a maximum-scale latency guarantee. Global clear is active-binding-scoped.
Readiness and diagnostics add only the `mysql` identifier; use SDK/frontend versions
that recognize it. Browser, deployment and installed-artifact certification remain
separate from these HTTP integration tests.

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

See [PostgreSQL setup](pgvector.md) and [embedded storage](../embedded/storage.md)
for ownership and maintenance details.

## Redis: setup, permissions and recovery

Use a directly addressed writable standalone primary with `noeviction`: either
a server from the [tested Redis version matrix](../embedded/redis.md#supported-versions)
or [exact Valkey 9.1.2](../embedded/redis.md#valkey-912). Both use
`CACHE_BACKEND=redis`, the server `redis` extra and package-owned RedisStore.
Hosted/cluster/replica support is not inferred from a URL. Read the
[Redis store contract](../embedded/redis.md) for the exact scan ceiling and ACL
commands. The [application validation record](../operations/valkey-validation.md)
separates tested Valkey behavior from unverified deployment claims.

Configure the same provider metadata, dimensions, prefix, capacity and TTL as the
runtime. Supply `REDIS_INITIALIZATION_URL` separately to the operator command:

```bash
python -m app.cache.infrastructure.setup
```

The command resolves **built-in** provider registry metadata without constructing
providers or doing inference. It creates the binding explicitly using
initialization authority, then closes its client.
Remove the initialization URL from the runtime environment. Ordinary server
startup uses `REDIS_URL`, validates the descriptor and performs no initialization.
Wrong capacity, TTL or unowned binding keys fail rather than falling back to memory.
Server product/version, primary role, noeviction and required-command probes belong
to explicit operator setup; runtime binding validation does not repeat them.
`REDIS_OPERATION_TIMEOUT_SECONDS` and `REDIS_CLOSE_TIMEOUT_SECONDS` bound network
operations and cleanup. The server propagates cancellation; caller-supplied package
clients remain borrowed and must be closed by their owner.

For a [custom registered provider](provider-extensions.md), the built-in setup CLI
does not load the deployment's registry. Use a deployment-owned operator bootstrap:
resolve the selected capabilities with `ProviderRegistry.resolve()`, construct an
`EmbeddingSpace` from the resolved identity/dimensions, and call public
`RedisStore.initialize_schema(initialization_client=...)` with separate setup
authority. Match runtime endpoint/database, prefix, capacity and TTL, close owned
setup resources, and pass the corresponding registry to `create_app()` at runtime.
Metadata resolution needs no inference. Keep registry identity and dimension
validation intact; dimensions and the 64-MiB vector projection are checked by
RedisStore before network resources open.

Redis persistence is operator-managed. AOF/RDB retention, backup, restore, ACLs,
TLS and eviction configuration remain deployment responsibilities. Redis does not
become an authoritative query counter service: its server hit/miss totals are
process-local telemetry; Inspector hit/access metadata comes from the actual store.

### Readiness and failure boundaries

`/ready` probes cache statistics and other enabled application stores; diagnostics
reports that cache-stats observation. OOM, replica/read-only mode or eviction-policy
drift can leave these read-only checks green while writes or hit confirmation fail.
Operators must maintain the setup deployment constraints; readiness is not continuous
proof of write availability or supported server configuration.

A lost acknowledgement can produce HTTP 500 `cache_error` after a put or hit-counter
mutation has committed. An unsuccessful response is not proof of rollback. The
store does not automatically replay these mutations or promise exactly-once effects.
Inspect uncertain outcomes before deciding whether another application operation is safe.

Application shutdown seals and drains shared query work before closing its owned
store. If retained work settles, cleanup can succeed. A numerical scoring worker
still active at the terminal close boundary can instead produce explicit
`CacheStorageError` with Redis resources not fully disposed. There is no automatic
busy-close retry or guarantee of clean termination; operator-controlled process
disposition may be needed. Do not treat that failure as successful cleanup.

## Inspector and diagnostics

The five concrete stores offer optional `inspect_entries` and `inspect_entry`
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
Python Unicode case folding in Memory/SQLite/MySQL/Redis and database `LOWER` in PostgreSQL;
non-ASCII matching depends on the PostgreSQL locale.

Observability eviction/expiry counts are observed process events, not an exact
persistent inventory. Readiness validates access to the selected store. An
unavailable store fails readiness; it is never replaced by an implicit memory cache.

## Local Docker and validation

For newly created project-owned development volumes, the
[development launcher](getting-started.md#recommended-development-launcher)
runs separate explicit setup and then validates storage. Existing volumes and
external URLs are validation-only; partial/incompatible states require operator
review. This does not change ordinary server startup or hardened deployment.

The advanced direct Compose workflow keeps memory as the default. Choose the `pgvector` or `redis`
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
selected integration test skips. Unit runs exclude `pgvector`, `redis` and `mysql`. The MySQL matrix runs server
HTTP/security/lifecycle tests with the repository-owned verified-TLS fixture;
required-test validation rejects missing cases and unexpected skips.
