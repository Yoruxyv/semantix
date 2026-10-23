# Embedded storage and application databases

`semantix-cache` runs in your Python process. It does not require the Semantix
FastAPI server. Its async engine consumes the structural
[`CacheStore` protocol](../../packages/cache/src/semantix_cache/protocols.py), not SQL.
The maintained stores are `MemoryStore`, file-backed `SQLiteStore`, optional `MySQLStore`, `PgVectorStore` and `RedisStore`.
The separate `semantix_client` package is the optional/reference HTTP client.

The server/workbench delegates to MemoryStore, PgVectorStore and RedisStore. See
[server storage configuration](../guides/platform-storage.md) for selection and setup.

## Optional inspection and administration

MemoryStore, SQLiteStore, MySQLStore, PgVectorStore and RedisStore additionally offer optional `inspect_entries` and
`inspect_entry` observations. They exclude expired entries without purging them,
recording hits, extending TTL or changing LRU. Lists contain prompts, identifiers
and bounded response previews (at most 240 characters), never vectors or complete
long answers. These fields remain sensitive; applications authorize namespace
scope before inspection. Detail reads can return a full answer; pass an explicitly
authorized namespace filter.
The package does not authenticate callers. Results are observations, never leases.

`clear_all` is a separate administrative mutation across namespaces of the active
store binding. Neither inspection nor clearing is required by the mandatory
`CacheStore` protocol. Ordinary hit confirmation does not call inspection.

Pages contain at most 100 entries. Memory scans its bounded binding; PostgreSQL
counts/ranks metadata and limits the page before projecting response previews.
Redis scans scalar metadata and decodes only the selected page. Redis prompt
search must scan its existing payload fields in batches of at most 100, under one
operation deadline and the existing binding capacity ceiling. No new index or
metadata keys are introduced. Concurrent changes can shift live offsets and Redis
search totals. See [server storage](../guides/platform-storage.md#inspector-and-diagnostics)
for authorization, search costs and pagination limitations.

Call these methods on a concrete supported store, not on `AsyncSemanticCache` or
the mandatory `CacheStore` protocol. Result types live in
`semantix_cache.inspection`. MySQL uses read-only snapshots and sequential
primary-key payload fetches; see [MySQL inspection costs](mysql.md#optional-inspection-and-administration).

For an existing MemoryStore populated through your cache, inside an async function:

```python
# Authorize this namespace in the application before issuing either read.
namespace = "support:tenant123"
page = await store.inspect_entries(namespace=namespace, limit=20, sort="newest")
if page.items:
    detail = await store.inspect_entry(
        page.items[0].cache_key, namespaces=(namespace,)
    )
    # detail may be None if the entry expired or was deleted after the list read.
```

The same calls apply to SQLiteStore, MySQLStore, PgVectorStore and RedisStore. List `namespace=None`
(the default) observes all namespaces in the binding. Detail `namespaces=None`
also allows all namespaces, while `namespaces=()` allows none; neither filter
authenticates a caller. Avoid unrestricted scope in tenant-facing code.
`clear_all()` requires separate administrative authorization; ordinary
`cache.clear(namespace=...)` remains scoped. Clearing is not secure erasure of
database files, backups or already-returned snapshots.

## Choose a store

| Store | Persistence | Dependency | Ownership |
| --- | --- | --- | --- |
| `MemoryStore` | Process-local, non-durable | Default NumPy/Pydantic core | Owns its state and workers |
| `SQLiteStore` | Local dedicated WAL file | stdlib sqlite3 with a patched linked runtime | Owns one connection and worker |
| `PgVectorStore` | PostgreSQL/pgvector | `semantix-cache[pgvector]` adds asyncpg | Borrows `pool=`; `connect()` creates an owned pool |
| `RedisStore` | Redis primary; operator-managed persistence | `semantix-cache[redis]` adds redis-py | Borrows `client=`; `connect()` creates an owned client/pool |
| `MySQLStore` | Dedicated MySQL Community 8.4.x; verified 8.4.11/8.4.12 | `[mysql]` adds PyMySQL >=1.2.1,<=1.2.3; exact stable versions enforced | Owns one connection and worker; explicit setup |
| Your `CacheStore` | Your implementation | Your application chooses | Your implementation documents ownership |

MemoryStore is bounded and appropriate for tests, local use and small ephemeral
workloads. The [package quick start](../../packages/cache/README.md) is executable
with a demonstration embedder. The
[custom integration example](../../packages/cache/examples/custom_integration.py)
runs offline and supplies its own async embedding/generation.

**0.1.0 is not yet published to PyPI.** [Build a local wheel](../../packages/cache/README.md#use-in-another-python-project),
then install its `[pgvector]` extra in your application's Python environment:

```bash
python -m pip install './dist/semantix_cache-0.1.0-py3-none-any.whl[pgvector]'
```

This relative wheel path assumes you are in `packages/cache`; adjust it for your
consumer project.
Import the adapter explicitly:

```python
from semantix_cache.stores.pgvector import PgVectorStore
```

Root imports load neither asyncpg nor provider HTTP dependencies. Imports and
exports from `semantix_cache` are unchanged by adding persistent storage.

See [Redis storage](redis.md#verified-driver-combinations) for separate server/driver
certification, resolver policy, exact scan,
explicit setup, TTL/LRU, failure handling and persistence boundary.

See [MySQL storage](mysql.md#verified-compatibility) for tested server/driver/Python/OS
combinations, verified TLS, the locked schema verifier,
explicit least-privileged setup, exact-search costs and failed-construction
recovery. MySQLStore also supplies `inspect_entries()`, `inspect_entry()` and
binding-scoped `clear_all()` outside the mandatory CacheStore protocol. The
official server uses the same store through `CACHE_BACKEND=mysql`; see
[server setup, verified TLS and deployment limits](../guides/platform-storage.md#mysql-explicit-setup-and-owned-connections).

## SQLite: local file persistence

`from semantix_cache.stores.sqlite import SQLiteStore` provides embedded persistence
without a database service or an extra dependency. The official server/dashboard
also supports `CACHE_BACKEND=sqlite` through the same package-owned store and its
optional inspection/administration methods. Server use requires explicit setup,
one native process and trusted local disk; bundled Compose is unsupported. See
[server setup and shutdown limits](../guides/platform-storage.md#sqlite-explicit-local-setup-and-bounded-shutdown).

Check the **linked** runtime, then run the offline example from `packages/cache`:

```text
uv run --no-sync python -c "import sqlite3; print(sqlite3.sqlite_version, sqlite3.threadsafety)"
uv run --no-sync python -m examples.sqlite_cache
```

The example reuses the existing deterministic embedder/generation flow, verifies
miss → generation → write → confirmed hit, closes the store, and verifies reuse
after reopening its disposable file. It exits silently on success. Its embeddings
verify integration behavior, not semantic understanding. No provider calls occur.

SQLiteStore accepts thread-capable SQLite **>=3.51.3, excluding withdrawn 3.52.0**,
plus exactly **3.44.6 and 3.50.7** from their upstream WAL-patched sources.
Prefer a current maintained release in the normal range for new deployments;
the two older versions are compatibility options. All other versions below 3.51.3
remain rejected, including 3.50.4 and 3.51.2. Thread-disabled builds are rejected
regardless of version.

The [WAL-reset advisory](https://sqlite.org/wal.html#walreset) identifies these two
upstream backports. Required Linux CI builds them sequentially from full check-in
identities, verifies archive SHA-256, source VERSION and manifest identity, then
asserts the actual linked version, source ID and thread capability. Each runs the
complete SQLite schema/conformance, fault and multiprocessing suites and an
independent installed-wheel consumer.

| SQLite | Verified environment | Verified source |
| --- | --- | --- |
| 3.44.6 | Linux x86_64, CPython 3.14.7, threadsafety 3 | [863c171b76cd36e0](https://sqlite.org/src/info/863c171b76cd36e0c71662d4a50d84da531cc7fbead893d02459577febdf6396) |
| 3.50.7 | Linux x86_64, CPython 3.14.7, threadsafety 3 | [c7facf7ac58d2cda](https://sqlite.org/src/info/c7facf7ac58d2cdac619a2da838c5fd5c5270f52b3458c7881b5a4fca1ca4791) |
| 3.51.3 | Linux x86_64, stock dynamically linked CPython 3.14 in required CI | Official amalgamation, verified source checksum |

The immutable archive hashes and build commands are in the existing
[SQLite Linux CI job](../../.github/workflows/quality.yml). Windows separately
retains managed CPython 3.11–3.14 conformance and installed-wheel checks.
The two older backports have not been certified on Windows, macOS or other
architectures, nor with arbitrary compiler options or vendor modifications.

The runtime gate checks the linked version tuple and thread capability; it
**does not authenticate a binary or prove its patch contents**. A binary merely
reporting one of these version numbers is not independently verified evidence.
Use a trusted upstream build or validate the vendor's source and WAL fix
provenance. Other vendor backports are not automatically admitted. The same
provenance limitation applies to the normal accepted range.

A supported Python version alone is insufficient, and upgrading Python package
dependencies does not upgrade its linked SQLite library. An ineligible runtime
raises `CacheConfigurationError` before path inspection or file creation. A Python
build without sqlite3 gives an actionable import error for this adapter. Core,
MemoryStore, RedisStore and PgVectorStore imports do not load SQLite.

The adapter has been exercised on Windows and Linux; macOS is not yet verified.
For a fresh checked-out source environment with a managed patched Python, use
`uv sync --locked --extra dev --managed-python --python 3.14`, then repeat the
linked-runtime check above. This changes the project environment, not a system DLL.

For an application-owned embedder, explicit setup and runtime ownership look like:

```python
from pathlib import Path
from semantix_cache import AsyncSemanticCache
from semantix_cache.stores.sqlite import SQLiteStore

# Inside async application startup; use a trusted private directory that exists.
path = Path("cache.db")
await SQLiteStore.initialize_schema(path, embedding_space=embedder.embedding_space)
async with (
    await SQLiteStore.connect(path, embedding_space=embedder.embedding_space) as store,
    AsyncSemanticCache(embedder=embedder, store=store) as cache,
):
    hit = await cache.get("an application-approved query", namespace="support")
```

Initialization exclusively creates an absent dedicated regular file, or validates
an existing Semantix file and registers its binding. It never adopts an empty,
foreign or partially initialized file. Failed new setup preserves its partial
file for diagnosis. `connect()` uses existing-file mode and performs no DDL,
migration or binding registration. Schema v1 has four STRICT tables, a frozen
packaged migration/checksum and checked ownership/structure. All connections to
one identity/dimension binding must agree on capacity and exact default TTL.
Supply matching `max_size`/`default_ttl_seconds` to both setup and connect.

Capacity defaults to 500, permits 1–5,000 entries across namespaces, and dimensions
are 1–16,000. Additionally, `max_size * dimensions * 8 <= 64 MiB`; for example,
500 × 16,000 and 5,000 × 1,536 fit, while 5,000 × 16,000 is rejected. Searches
read **every** eligible normalized float64 vector and use the shared cosine
kernel with revision/key tie ordering. No ANN, top-k truncation or float32
conversion is used. The detached matrix and numerical temporaries make total RSS
substantially larger than 64 MiB. Entry capacity is not a disk quota; large valid
responses, WAL and free pages can dominate file size. Prefer the default capacity
and measure your workload before selecting the upper bounds.

Each store owns one connection and one single-thread worker. One complete
operation occupies that worker through rollback/cleanup, with at most 32 admitted
operations including waiters. Mutations acquire `BEGIN IMMEDIATE`; revision,
payload, expiry, hit counters, LRU and eviction commit together. Binding revision
history survives delete, clear, expiry, eviction and reopen. Confirmation checks
the current binding, namespace, key, exact revision and a fresh statement clock;
false confirmation changes no hit/LRU state. Every confirmed hit is a write.
All bindings in one file share SQLite's single writer, so this suits small,
low-contention local workloads rather than a distributed cache service.

Inspection reads one transaction snapshot without confirming hits, renewing TTL,
changing recency or purging expired rows. Ordinary lists count/sort bounded scalar
metadata and decode only selected-page payloads; detail reads decode one authorized
payload. No inspection call reads vectors. Prompt substring search uses Python
Unicode `casefold`, scanning authorized live payloads sequentially for an exact
filtered total. It retains bounded metadata, one payload and the output page,
rather than all response bodies. Bounded memory does not guarantee fast completion:
search holds this store's worker and retains the existing operation deadline,
returning the complete result or an error. Concurrent writes or expiry can shift
later pages. `clear_all()` atomically removes all namespaces of the active embedding
binding, including expired rows, while reporting only live entries removed. Other
bindings and revision history remain intact. Clearing is not secure erasure.

TTL inherits/caps the configured default, starts from the host UTC wall clock at
write, floors fractional durations to microseconds, and expires inclusively.
Both TTL values `None` permit immortality; hits never slide expiry. Downtime
counts toward TTL. A clock rollback can extend retention or re-expose expired
rows that have not been purged. The confirmation clock is its linearization point,
not a retention lease through COMMIT or subsequent response use.

Operation/connect/close deadlines are finite positive seconds up to 86,400
(default 30/10/30). Lock waits are capped at one second and remaining operation
budget. Cancellation/timeout propagates while underlying work remains owned;
close is busy until it drains. Work near COMMIT can succeed without delivering
its result. **No mutation is automatically replayed.** Uncertain transaction
cleanup faults the store; close and reopen it. Concurrent/repeated close shares
one shielded cleanup task. A timed-out close leaves the wrapper sealed and cleanup
tracked; Python cannot kill a native thread stuck in OS I/O.

An exceptional native close failure is terminal: later operations fail closed and
repeated close observes the same cleanup outcome without retrying. The connection
may remain physically alive until operator-controlled process termination; that
is not successful library disposal. If startup and its observed cleanup both fail,
the original public startup exception remains primary with the safe cleanup error
as its cause. This improves failure visibility, not resource recovery. Cleanup
that exceeds the startup unwind budget remains subject to the existing limitation.

Use a single host and trusted **local disk** with private permissions/ACLs.
Memory databases, borrowed connections, caller-supplied URIs, detectable network
paths and symlink/reparse paths are rejected. Network/cloud-sync filesystems,
live file replacement and hostile filesystem substitution are unsupported.
WAL uses `synchronous=FULL`; durability still depends on correct filesystem and
hardware flushing. Process-termination tests do not certify power-loss safety.
Files, WAL, backups and freed pages may retain plaintext; clear is not secure erase.
Do not copy an active `.db` alone or delete its sidecars. Restoring an older file
requires a **new embedding identity/cache generation** and invalidating old
candidates, because whole-file rollback also rewinds revision history.

## MemoryStore sizing: entries are not a byte budget

MemoryStore defaults to 500 entries, permits at most 5,000, and shares its capacity
across namespaces. These are entry counts, not fixed memory/RSS limits. Response
length is capped at 100,000 **characters**, not bytes; Unicode representation,
prompt length and embedding dimensions also affect memory. No byte-budget eviction
or new runtime limit is implied.

A bounded one-off measurement on 2026-10-07 used source
`75775c6f8dd6bb654e57280516604ec97f92f3f0`, 64-bit CPython 3.14.6 on Windows 11,
NumPy 2.4.6 and Pydantic 2.13.5. Each cell ran in a fresh process with one BLAS
thread, the default 500-entry capacity/3,600-second TTL and one namespace. A
synthetic embedder returned the finite vector `(1.0, 2.0, ..., D)`; public `set`
stored 500 distinct short prompts and distinct ASCII responses of exactly the
listed length. No language model or provider was called. Both response sizes are
valid under the existing bound.

After imports/embedder creation, start `tracemalloc`, collect garbage and record
a baseline. Measure retained traced allocation after seeding, then after two
unchanged public `get` calls and garbage collection. The second lookup retains
the immutable float64 scoring matrix/norms. `sys.getsizeof` on stored response
strings and on embedding tuples plus their float objects separates those
components; snapshot `nbytes` measures its retained native buffers. Internal
inspection here is measurement tooling, not a supported sizing API.

All values below are MiB (2^20 bytes) for **500 entries**; components are included
in the traced totals, not extra amounts to add to them.

| Dimensions | Response chars/entry | Text payload (UTF-8) | Python vector tuples/floats | Retained native snapshot | Traced seeded delta | Traced warm delta | Traced peak delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 384 | 128 | 0.06 | 5.88 | 1.47 | 6.72 | 8.18 | 9.73 |
| 384 | 32768 | 15.62 | 5.88 | 1.47 | 22.28 | 23.75 | 25.30 |
| 1536 | 128 | 0.06 | 23.46 | 5.86 | 24.29 | 30.16 | 36.14 |
| 1536 | 32768 | 15.62 | 23.46 | 5.86 | 39.86 | 45.72 | 51.71 |

ASCII string headers added 20,500 bytes across 500 responses on this interpreter;
the UTF-8 payload column alone omits them. Embeddings are stored as Python tuples
of floats, not just `8 * N * D` packed bytes. After repeated unchanged lookup,
the snapshot adds exactly `8 * N * D + 8 * N` buffer bytes, excluding NumPy array
headers. Entry models, prompts/keys, expiry/revision metadata, LRU bookkeeping,
thread/executor state and temporary allocations account for further overhead.
Scoped mutations invalidate snapshots; an active numerical worker can retain an
old snapshot until it drains.

**RSS was not measured.** Traced allocations (including NumPy's registered buffer
allocations) do not cover every native allocator, library, process or allocator
reservation. Unicode, multiple active namespaces, concurrent work and churn can
change retention/peaks; this synthetic table is not an exact production forecast.
Choose capacity with representative payloads/dimensions, then measure whole-process
RSS and peak/steady-state behavior under your application's load. Do not extrapolate
a fixed RSS budget from entry count or this one-off allocation table.

## Verified PostgreSQL combinations

The required [embedded CI jobs](../../.github/workflows/quality.yml) exercise
these combinations with immutable service-image digests. Each job checks the
actual server major and extension version before running the full embedded suite
and installed-wheel migration/persistence checks.

| PostgreSQL server | pgvector extension | asyncpg driver | Linux CPython |
| --- | --- | --- | --- |
| 16.15 | 0.8.7 | 0.31.0 | 3.11 |
| 17.10 | 0.8.5 | 0.31.0 | 3.12, 3.13 |
| 18.6 | 0.8.7 | 0.31.0 | 3.14 |
| 16.15 | 0.8.7 | 0.32.0 | 3.11, additional sequential certification |
| 18.6 | 0.8.7 | 0.32.0 | 3.14, additional sequential certification |

These are verified targets, not a new PostgreSQL runtime minimum. Other
server/extension/driver combinations are unverified by this CI matrix; do not
infer that every combination across these versions has been tested. The optional
extra admits asyncpg `>=0.31,<=0.32.0`: the existing 0.31.x policy plus the
exact tested 0.32.0 release; later 0.32.x releases require new evidence. Both
project locks and the development extra retain the 0.31.0 baseline. For an
explicit runtime candidate install, use your consumer environment's Python and
the locally built wheel (this path assumes `packages/cache`):

```text
python -m pip install './dist/semantix_cache-0.1.0-py3-none-any.whl[pgvector]' 'asyncpg==0.32.0'
```

Candidate typing is checked separately with asyncpg-stubs 0.32.0; the development
extra keeps its baseline driver/stub constraints.

Windows x86_64 experiments additionally passed PostgreSQL 16.15/0.8.7 on CPython
3.11.15 and 17.10/0.8.5 and 18.6/0.8.7 on CPython 3.14.6 with both exact drivers.
These source checks include all PostgreSQL disconnect/cancellation regressions;
independent wheels are checked separately. This does not certify every permutation.
Use maintained PostgreSQL patches and validate your exact deployment before upgrading.

The table covers Linux service containers and standard CPython builds. It does
not certify managed proxies, database failover, other architectures or
free-threaded Python. Application-owned pool configuration and the existing
migration, transaction and cleanup contracts still apply.

### Verified TLS boundary

Required PostgreSQL 18 CI checks both drivers with disposable CA/hostname-verified
TLS, rejects untrusted CAs and incorrect hostnames, and verifies transport cleanup
on cancelled or timed-out negotiation. Independent wheels exercise real cache
persistence over verified TLS. Local PostgreSQL 16/17/18 experiments also verified
traditional PostgreSQL TLS negotiation with both drivers.

Direct TLS requires PostgreSQL 17+ and the `postgresql` ALPN protocol. asyncpg
0.32.0 sets ALPN on contexts it creates, including a `verify-full` DSN with
`sslnegotiation=direct`. A caller-provided `SSLContext` must set
`set_alpn_protocols(["postgresql"])`; this also enables application-owned direct-TLS
pools with 0.31.0. Automatic direct TLS with 0.31.0 and direct TLS to PostgreSQL 16
are outside this verified boundary. Local direct-TLS checks covered PostgreSQL
17/18; CI repeats them on 18. See the [asyncpg release notes](https://github.com/MagicStack/asyncpg/releases/tag/v0.32.0)
and [PostgreSQL TLS protocol](https://www.postgresql.org/docs/17/protocol-flow.html#PROTOCOL-FLOW-SSL).
Arbitrary CA policies, mutual TLS, proxies and managed TLS endpoints remain unverified.

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
`semantix_cache.stores._backends.postgres.migrations/0001_cache.sql`; it contains quoted-layout
placeholders and is not a standalone unrendered SQL script. The explicit
initializer renders it, applies it transactionally and records its checksum.

The former `semantix_cache.stores.migrations` resource package has been removed.
Deployment tooling that reads the template directly must use the new package
path; `PgVectorStore.initialize_schema()` retains its existing initialization
workflow and database compatibility.

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

The [executable example](../../packages/cache/examples/persistent_support.py) uses
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

`await PgVectorStore.connect(...)` either returns an owned store or raises; a
failed or cancelled attempt provides no usable partial store and terminates any
pool it created. Invalid connection/binding settings raise `CacheConfigurationError`,
startup deadline expiry raises `CacheTimeoutError`, and expected connection/driver
failures raise `CacheStoreError`. Caller cancellation and unexpected programming
errors propagate. A successful connection does not initialize or validate the
cache schema: complete [explicit setup](#new-postgresql-database), then call
`validate_schema()` before cache use.

Semantix does not retry a failed `connect()` call, recover it in the background
or switch to MemoryStore. Applications decide whether to fail startup, attempt a fresh
connection under their own recovery policy, or explicitly select another store.
Handle these failures before accepting cache work; never proceed with a failed
construction attempt.

Startup defaults to a 10-second deadline; cancellation unwinding and cleanup can
finish after that deadline. Operations include acquisition,
commands, transaction completion and release within the default 30-second deadline.
Owned-pool close defaults to 30 seconds. Timeouts must be positive finite numbers
up to 86,400 seconds. Cancellation propagates after connection release finishes
within the remaining operation budget; the store retains cleanup ownership while
unwinding. A connection proven closed is retired before release, without closing
other users of a borrowed pool. Internal driver errors on live connections still
propagate. Failed transactions roll back when the server can establish that outcome;
a disconnect during commit remains uncertain and is never replayed.
Close during an admitted operation raises
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

Historical intermittent startup timeouts observed during local validation remain
unexplained. That evidence neither establishes widespread PostgreSQL startup
failures nor identifies their cause; the failure contract above is not a failure-rate claim.

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
[company-store example](../../packages/cache/examples/custom_store.py) implements
it without wrapping/subclassing either built-in store. It is process-local demo
storage; replace its dictionary with your own infrastructure. Run it with
`uv run --no-sync python -m examples.custom_store`, and inject it into
`AsyncSemanticCache(embedder=my_embedder, store=my_store)`.

For additional backends such as Qdrant, Weaviate, Milvus, SQLite extensions or proprietary services,
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

Only shipped, tested adapters are maintained. MySQLStore has its own verified-TLS,
dedicated-database boundary described above.
A deployment without suitable vector similarity cannot satisfy semantic lookup just
because it supports SQL. Custom embedding adapters and generation callables remain
available for providers/versions whose external APIs change independently.

## Validation and adapter-author evidence

The [developer conformance kit](cache-store-conformance.md) runs against
all five maintained stores and the independent example. MemoryStore, PgVectorStore
and the example use the [shared consumer](../../packages/cache/tests/test_store_conformance.py);
[SQLite](../../packages/cache/tests/test_sqlite_conformance.py),
[MySQL](../../packages/cache/tests/test_mysql_conformance.py) and
[Redis](../../packages/cache/tests/test_redis.py) supply backend-owned consumers. It covers empty/exact/similar
search, threshold misses, isolation, dimensional validation, expiry, revisions, scoped
mutation, LRU, concurrency and close. PostgreSQL-specific
[tests](../../packages/cache/tests/test_pgvector.py) exercise persistence, existing
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
PostgreSQL release. CI runs the full suite against the
[verified combinations](#verified-postgresql-combinations), rejects missing or
skipped required cases, retains the coverage gate, and tests migrations/persistence
from the installed wheel. Only explicitly enumerated optional conformance skips
are permitted. pytest and driver typing stubs stay development-only.
