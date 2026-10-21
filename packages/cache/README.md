# semantix-cache

Async semantic caching in your Python process. No Semantix server is required.
The runtime supports Python 3.11–3.14 and depends on NumPy and Pydantic.

The distribution name is **semantix-cache** and its import is **semantix_cache**.
**0.1.0 is not yet published to PyPI.** Use local source or a locally built wheel.
Only `packages/cache` is the intended first public distribution. The optional
backend/dashboard and the separate HTTP client are not required for embedded use.

[Source quick start](#run-from-source) · [Local installation](#use-in-another-python-project) ·
[Optional dependencies](#choose-optional-dependencies) ·
[Storage setup](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#choose-a-store) ·
[Contract](#contract) · [Troubleshooting](#troubleshooting)

## Run from source

Install Git, Python 3.11–3.14 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root, these commands work in Bash and PowerShell:

~~~text
cd packages/cache
uv sync --locked
uv run --no-sync python -m examples.custom_integration
~~~

The maintained [custom integration example](https://github.com/Yoruxyv/semantix/blob/main/packages/cache/examples/custom_integration.py)
uses `AsyncSemanticCache`, `EmbeddingSpace` and `MemoryStore`. It exits silently on
success and raises unless the first resolve generates/writes and the second
confirms a hit and skips generation. No credentials, provider API calls, Docker,
server or database are needed. Setup downloads dependencies; execution is offline.
The deterministic two-dimensional embeddings verify integration behavior, **not
semantic understanding or match quality**. `provider_called` reports execution of
the application's local generation callable here.

## Use in another Python project

Keep the checkout at a reviewed commit (`git checkout <commit-sha>` in a dedicated
clone) and record its SHA with `git rev-parse HEAD`. An editable install uses that
checkout directly, so later edits change what the consumer imports.

From the directory containing the `semantix` checkout, create a separate consumer
environment and install only the local cache package:

Windows PowerShell:

~~~powershell
python -m venv my-app/.venv
./my-app/.venv/Scripts/python.exe -m pip install -e ./semantix/packages/cache
~~~

Bash (Linux/macOS):

~~~bash
python -m venv my-app/.venv
./my-app/.venv/bin/python -m pip install -e ./semantix/packages/cache
~~~

Run your application's scripts with that environment's Python and import from
`semantix_cache`, as below. No backend modules or development extras are required.
Local installation still resolves NumPy/Pydantic from a package index unless
dependencies are already available locally.

For a non-editable wheel, build from `semantix/packages/cache`:

~~~text
uv sync --locked --extra dev
uv run --no-sync python -m build
~~~

Then, from the directory containing the checkout, replace the editable install
command with the corresponding local wheel command:

~~~powershell
./my-app/.venv/Scripts/python.exe -m pip install ./semantix/packages/cache/dist/semantix_cache-0.1.0-py3-none-any.whl
~~~

~~~bash
./my-app/.venv/bin/python -m pip install ./semantix/packages/cache/dist/semantix_cache-0.1.0-py3-none-any.whl
~~~

Use a fresh consumer environment when checking the wheel independently of an
editable install. These paths install local Semantix source/artifacts; they do not
fetch an unpublished Semantix distribution from PyPI. Optional provider/store
extras require their own dependencies and setup; see the [provider](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/providers.md)
and [storage](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md) guides.

## Choose optional dependencies

Choose extras on the same local source or wheel install; the core does not require
a provider SDK, database driver, HTTP client, server or dashboard dependency.

| Capability | Extra | Import / setup guide |
| --- | --- | --- |
| MemoryStore and local SQLiteStore | None | [Storage selection and SQLite runtime requirements](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#choose-a-store) |
| Maintained HTTP embedding/generation adapters | `providers`, or `openai`, `huggingface`, `gemini`, `ollama`, `anthropic` | [Provider modules and configuration](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/providers.md#install-and-import); these extras all add HTTPX |
| PostgreSQL/pgvector | `pgvector` | [Server/extension/asyncpg combinations and setup](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#verified-postgresql-combinations) |
| Redis or the certified Valkey target | `redis` | [RedisStore server/driver boundaries and setup](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/redis.md) |
| MySQL | `mysql` | [MySQLStore server/driver boundaries and setup](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/mysql.md) |

For example, from the directory containing the checkout, use your consumer
environment's Python to install a built wheel with HTTP adapters and PostgreSQL:

~~~text
python -m pip install './semantix/packages/cache/dist/semantix_cache-0.1.0-py3-none-any.whl[providers,pgvector]'
~~~

For editable source, the corresponding target is
`'./semantix/packages/cache[providers,pgvector]'` with `pip install -e`.
Install only the capabilities you use; the `dev` extra is for package development.
Installing a driver does not provision a database or initialize a store. The
linked guides distinguish runtime admission from the exact tested combinations.

## Use your own embedding and generation

~~~python
import asyncio
from collections.abc import Sequence

from semantix_cache import AsyncSemanticCache, EmbeddingSpace, MemoryStore


class DemoEmbedder:
    # Demonstration only: this vector mapping is not a production language model.
    embedding_space = EmbeddingSpace(identity="demo-v1", dimensions=2)

    async def embed(self, text: str) -> Sequence[float]:
        return (1.0, 0.0) if "weather" in text.lower() else (0.0, 1.0)


async def generate(prompt: str) -> str:
    # Replace with your application's existing async generation flow.
    return "Completed answer for: " + prompt


async def main() -> None:
    embedder = DemoEmbedder()
    async with MemoryStore(embedding_space=embedder.embedding_space) as store:
        async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
            first = await cache.resolve(
                "weather today", generate=generate, namespace="demo"
            )
            second = await cache.resolve(
                "weather tomorrow", generate=generate, namespace="demo"
            )
            assert first.provider_called and first.cache_written
            assert second.cache_hit and second.generation_skipped
            hit = await cache.get("weather next week", namespace="demo")
            assert hit is not None
            key = await cache.set(
                "approved final answer",
                "Application-approved text",
                namespace="reviewed",
            )
            assert await cache.delete(key, namespace="reviewed")
            assert await cache.clear(namespace="demo") == 1


asyncio.run(main())
~~~

Create one store/cache and reuse them across requests. MemoryStore is bounded
process memory; recreating it loses the cache. It is not persistent storage.

## Local persistence with SQLite

Use `from semantix_cache.stores.sqlite import SQLiteStore` for a dedicated local
file without a database service or additional dependency. It requires
thread-capable **linked SQLite >=3.51.3, except withdrawn 3.52.0**, or the exact
upstream WAL-patched **3.44.6 / 3.50.7** backports. Prefer a current maintained
release in the normal range for new deployments. Python's version alone does not
establish eligibility or binary provenance. From this directory, the credential-free
example reuses the integration flow above and verifies persistence after closing/reopening:

~~~text
uv run --no-sync python -m examples.sqlite_cache
~~~

Setup is explicit (`initialize_schema`); `connect` never creates/adopts a file or
performs DDL. Each store owns its connection/worker; drain operations before close.
Complete float64 scans are bounded to 5,000 entries, 16,000 dimensions and
`capacity * dimensions * 8 <= 64 MiB`, with larger total RSS. Every confirmed hit
writes under the file-wide writer lock. See [SQLite setup and restrictions](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#sqlite-local-file-persistence)
for runtime/file safety, TTL, cancellation, restore and durability limits.
SQLite also supports the optional single-process official server; see
[local server setup](https://github.com/Yoruxyv/semantix/blob/main/docs/guides/platform-storage.md#sqlite-explicit-local-setup-and-bounded-shutdown).
Concrete `SQLiteStore` instances support optional `inspect_entries()`, scoped
`inspect_entry()` and binding-scoped `clear_all()`. Inspection leaves TTL, hits and
recency unchanged. Lists decode only the selected page; exact Unicode prompt
search streams payloads under the existing deadline, so bounded memory does not
imply bounded latency. An exceptional native-close failure remains terminal and
may leave a connection alive until operator-controlled process termination;
startup error chaining exposes observed cleanup failure without claiming recovery.

## Optional MySQL persistence

`from semantix_cache.stores.mysql import MySQLStore` uses the local wheel's
`[mysql]` extra (PyMySQL >=1.2.1,<=1.2.3; exactly 1.2.1/1.2.2/1.2.3 at runtime),
verified TLS and an owned synchronous worker. Setup is explicit on a dedicated
MySQL Community 8.4.x database (verified patches 8.4.11/8.4.12); runtime uses
restricted table grants plus a fixed locked-definer verifier. The server/dashboard
does not select MySQL. See [MySQL setup, limits and cleanup recovery](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/mysql.md)
before use: full float64 scans are bounded, hits write, slow I/O can time out,
and an uncertain mutation/COMMIT is never automatically replayed.

## Optional cold-miss coalescing

Opt-in cold-miss coalescing can substantially reduce duplicate generation during
compatible concurrent misses while preserving the optimized cache-hit path.
`resolve(..., coalescing_key=None)` is the default and keeps existing behavior.
Only eligible NORMAL cold misses with an explicit key can share generation.
Ordinary confirmed hits do not enter the coalescing registry. Other policies
keep their existing behavior.

Coalescing is in-process, within one cache instance and event loop. It does not
coordinate separate cache instances or processes.

~~~python
# Reuse this exact callable object. The application freezes its relevant inputs
# and rotates the key when model/context/document/permission state changes.
question = "How do I reset my support account?"
result = await cache.resolve(
    prompt=question,
    generate=generate,
    namespace="support:tenant-123:v17",
    coalescing_key="support-rag:tenant-123:v17",
)
~~~

The key is your explicit declaration that concurrent requests have the same
immutable generation-input context and that sharing one invocation is safe.
Semantix cannot infer generation equivalence from the prompt or callable identity.
Rotate or distinguish the key whenever tenant, permissions, conversation state,
retrieved documents, model/tool configuration, ContextVars, closures, application
epoch or any other generation-relevant input changes. Also maintain appropriate
namespace/cache isolation for persisted reuse; changing the coalescing key alone
does not invalidate cached answers. Use no key when callers need independent
stochastic samples or generation side effects. Separately retrieved bound methods
are distinct callable objects; bind once when sharing is intended.

Keys are nonempty plain strings, at most 256 UTF-8 bytes, compared exactly. They
are **not cache partitions or authorization boundaries**: persisted reuse still
requires appropriate namespaces and embedding spaces. Sharing also requires the
same canonical generation prompt, exact normalized float64 query, callable object,
configuration and requested/default/effective TTL. Similar prompts alone never join.

The leader generates and persists inside its request. Followers wait for the entire
operation to succeed, then perform their own lookup and atomic revision/TTL
confirmation using their already-prepared embeddings. Their CacheResult therefore
contains fresh hit evidence. Expiry, replacement or failed confirmation can instead
require the follower's own first generation/write; no leader result is copied.
Generation and persistence failures propagate to waiting followers without retry.

Follower cancellation/deadline affects only that follower. Leader cancellation
fails the flight for waiting followers; leader deadlines propagate CacheTimeoutError.
There is no detached generation task, promotion, global registry or distributed lock.
`aclose()` remains busy while requests or retained participants exist; it neither
cancels work nor closes borrowed dependencies.

Internal admission is bounded to 128 retained records, 256 participants and 4 MiB
of charged identity storage, including completed flights whose callers still drain.
Overflow preserves independent generation. These bounds cover coalescer metadata,
not caller-created tasks or arbitrary callable closures. Embedding calls are still
per caller. Extra leader/follower lookups trade store work for reduced generation;
zero-delay providers and TTL/churn can make sharing less useful.

### Measured provider-work and latency tradeoff

A local cold-burst experiment executed 256 requests with up to 128 concurrent
resolves, two distinct compatible prompts and a 200 ms deterministic generation
delay. Generation calls fell from 256 to 2 in each of three trials per mode for
both stores; duplicate generation calls fell from 254 to 0. Embedding calls stayed
at 256.

The table reports median per-trial burst percentiles from **uninstrumented**
runs with coalescing disabled and enabled. Treatment percentiles are dominated by
followers; they are not isolated follower-only timings.

| Store | Burst P50, disabled -> enabled (ms) | Burst P95, disabled -> enabled (ms) |
|---|---:|---:|
| MemoryStore | 294.095 -> 434.127 | 316.949 -> 458.839 |
| PgVectorStore | 916.670 -> 941.012 | 1366.900 -> 1087.602 |

These development measurements used this coalescing implementation on base revision
`ee915140`, Python 3.14.6, NumPy 2.4.6 and Pydantic 2.13.5 on Windows 11 with a
Ryzen 9 5900HX, 16 logical CPUs and about 32 GiB RAM. The workload used 384-dimensional
vectors, 500 seeded candidates, capacity 5,000, threshold 0.92 and TTL 3,600 seconds.
PostgreSQL 17.10/pgvector 0.8.5 ran locally in a four-CPU/2-GiB Docker container with
an eight-connection pool. Each trial used a fresh Python process; setup, warmup and
cleanup were excluded, and child BLAS threads were fixed at one. All measured requests
completed without errors. See the [experiment methodology](https://github.com/Yoruxyv/semantix/blob/main/packages/cache/benchmarks/COALESCING.md)
for reproduction and source/environment recording.

Followers wait for the leader's successful generation and persistence, then perform
their **own authoritative lookup and atomic TTL/revision confirmation**. Diagnostic
timing found store queueing, rather than identity/registry bookkeeping, dominated
the added cost: MemoryStore's leader recheck and follower searches queued for the
numerical worker; PostgreSQL searches and confirmations queued for pool connections.
This work preserves truthful CacheResult evidence and expiry/revision semantics.
Instrumented diagnosis timings are separate from the ordinary numbers above.

These measurements show a provider-work/latency tradeoff, not a promise that every
workload becomes faster or that coalescing always reduces latency. The 256-to-2
reduction depends on compatible keys/inputs, admission, successful persistence and
confirmation; it is not guaranteed for every application. Provider pricing, token
counts and application behavior determine actual dollar savings, which this
deterministic experiment did not measure.

Optional [numeric coalescing evidence](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/observability.md) uses
`collect_coalescing_metrics=True` and `coalescing_snapshot()`; collection defaults to
False. General logging, metrics and tracing remain application-owned.

## 0.1.x compatibility

Throughout the 0.1.x release line, supported public import paths, classes and
functions, existing call signatures and defaults, result fields, policy values,
documented extension protocols, and documented lifecycle/resource-ownership
behavior remain compatible for valid documented usage. Additive APIs must preserve
existing calls and defaults.

Bug and security corrections may reject behavior that was invalid, unsafe, or
contrary to the documented contract, and must be described in release notes.
A breaking change to valid supported usage requires an explicitly announced
compatibility-policy amendment or version 0.2.0 or later with migration guidance.

Undocumented behavior, private internals and underscore-prefixed modules are not
compatibility surfaces. Maintained provider retirement follows the
[provider deprecation process](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/providers.md#deprecation-path).
Arbitrary third-party providers, external provider availability and provider-side
API behavior remain outside this compatibility promise. Custom integrations remain
available when a provider's API changes.

### PostgreSQL schema compatibility

Semantix-owned cache schemas created or upgraded through supported Semantix
migrations remain supported throughout 0.1.x. Applied migration SQL and checksums
are immutable. Schema evolution requires a new explicit reviewed migration,
separately privileged migration authority, and upgrade guidance.

Runtime operations validate ownership markers, schema version and migration
checksums and perform no DDL. Unsupported, tampered or foreign layouts are rejected
by these checks rather than silently adopted or downgraded. Modified database
layouts are outside the compatibility promise; administrators remain responsible
for preventing out-of-band schema tampering, as described in the
[storage guide](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#existing-application-database).
Downgrades are unsupported unless explicitly documented.

For explicit model/tenant/knowledge/output scopes and safe cache migration, see
the [context identity and migration guide](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/context-identity-and-migration.md).

## Contract

The facade exposes async `resolve`, `get`, `set`, `delete`,
`clear`, `aclose` and async context management. No synchronous facade is
provided. `get` returns immutable `CacheHit | None`; `set` returns the
canonical key after a successful write. `resolve` returns immutable `CacheResult`
with hit/miss, score, threshold, match, generation, latency and write evidence.
Vectors are available in the storage port's `CacheEntry`, not result objects.

Canonical prompts replace control characters with spaces, collapse horizontal
whitespace and trim; length is 1–2,000 characters. Responses must contain non-whitespace
text and fit 100,000 characters. Generation receives the canonical prompt.
An optional prompt normalizer changes embedding text only. Its preprocessing must
be represented in the stable embedding-space identity.

Namespaces are 1–64 ASCII characters matching
`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`. Keys hash namespace, a NUL separator and
canonical prompt. Delete/clear affect only their concrete namespace and bound space.
Namespace separation is a data boundary; applications own authorization.

Use explicit `CachePolicy` members; strings are rejected:

| Policy | Search | Generate | Write |
|---|---|---|---|
| NORMAL | Yes | On miss | On generated miss |
| READ_ONLY | Yes | On miss | Never |
| REFRESH | No | Always | Yes |
| BYPASS | No | Always | Never |
| PRIVATE | No | Always | Never |

TTL with a write-disabled policy is invalid before callback/store work. PRIVATE
does not control developer callback logging or external provider data handling;
the package emits no payload traces.

MemoryStore defaults to 500 entries (maximum 5,000) and a 3,600-second TTL. Capacity
and confirmed-hit LRU are shared across its namespaces. Exact cosine ties use
ascending created_at and cache_key, independently of LRU. Scores are clamped to
[-1,1]; the inclusive facade threshold defaults to 0.92. Evaluate this threshold
against your workload; semantic matches can be wrong.

Per-write TTL is a finite positive number up to 31,536,000 seconds. None inherits the
store default, including a no-expiry default of None. A requested TTL cannot extend
a finite default retention cap. TTL starts at the write, resets on replacement,
does not extend on hits, and expires at the exact monotonic deadline in MemoryStore.
Persistent stores use their documented authoritative clocks and precision; see the
[storage guide](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md).
Metadata timestamps are aware UTC. Candidate confirmation rechecks revision and expiry.

### Matching-text preprocessing

`AsyncSemanticCache` accepts the existing optional synchronous
`prompt_normalizer: Callable[[str], str]` constructor argument. It transforms the
canonical prompt for embedding-based lookup and newly computed write embeddings;
generation, stored prompt text and key derivation keep the canonical application
prompt. Return valid text and use deterministic behavior across reads and writes.

Installing this package does not install SymSpell or enable typo correction. The
optional server separately provides startup-configured SymSpell correction through
`PROMPT_TYPO_CORRECTION_ENABLED` and `PROMPT_TYPO_MAX_EDIT_DISTANCE`; those variables
do not configure this standalone facade. See the
[server normalization guide](https://github.com/Yoruxyv/semantix/blob/main/docs/guides/prompt-typo-normalization.md).

Applications can supply evaluated vocabulary, whitespace or casing transformations;
these are custom implementations, not built-in presets. Preserve meaning-bearing
content and application context. Represent preprocessing in `EmbeddingSpace.identity`
and isolate incompatible stored vectors when changing it; the facade does not derive
that identity from your callable. Normalization does not replace threshold, namespace,
expiry or revision checks, or verify that an answer is appropriate. See
[context identity and migration](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/context-identity-and-migration.md).

## Extension and ownership

An EmbeddingAdapter structurally supplies `embedding_space: EmbeddingSpace`
and `async embed(text) -> Sequence[float]`. No subclass or registry is needed.
Space identity must distinguish model/revision/dimensions/preprocessing, remain
stable and contain no secrets. Matching dimensions alone do not make spaces compatible.
Vectors reject malformed types, boolean components, non-finite values, wrong lengths,
and zero or invalid magnitudes; the engine normalizes valid vectors.

Generation is an application-owned async callable accepting canonical text and
returning completed text. Generator exceptions propagate unchanged. Invalid output
raises GenerationError and is never written. Streaming, RAG, tools and moderation
can use get/set around the application's final approved output.

A custom CacheStore supplies embedding_space, default_ttl_seconds, find_nearest,
record_hit, put, delete_entry, clear and aclose as described by the typed protocol.
It must filter namespace/space/dimension/expiry, return immutable validated CacheMatch
snapshots, confirm the expected created_at revision atomically without extending TTL,
and complete bounded-capacity writes truthfully. Entries have no embedded space tag:
direct put callers must supply entries from the store's declared space. A facade checks
its adapter and store metadata at construction and during operations. Use the
[developer conformance kit](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/cache-store-conformance.md) to verify a custom store.

AsyncSemanticCache borrows all injected resources and closes only its facade.
MemoryStore owns its state and numerical workers. Double close is harmless; operations
on closed objects raise CacheClosedError. Close during admitted operations or owned
workers raises CacheBusyError and leaves the resource open; callers must drain or
cancel their tasks before closing.

The facade's total operation deadline defaults to 30 seconds. Deadline expiry raises
CacheTimeoutError; cancellation propagates. A cancelled numerical search retains its
bounded worker slot until the thread completes, so aclose can remain busy meanwhile.
Python cannot forcibly interrupt a numerical thread. Custom async integrations must
not block the event loop. No automatic retry is provided; miss coalescing requires
an explicit key as described above.

Lookup and write failures raise; generation followed by write failure does not return
a successful resolution. Expected integration failures use safe embedded errors;
programming bugs propagate. Package error messages and model repr omit payloads.
Explicit model serialization contains its documented data and must be handled by the
application with appropriate care.

## Provider verification

Hosted provider examples are optional, require your own credentials and may incur
charges. The source quick start above makes no provider API calls.

The maintained OpenAI, Gemini, and Hugging Face adapters and independent custom
integrations passed live MemoryStore miss → generate → write → confirmed-hit
checks on **2026-10-05**. See the [provider guide](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/providers.md#010-verification)
for the tested models and scope. Ollama was previously exercised locally, but
current release-verification evidence is incomplete.

Anthropic generation is **contract verified; first-party live verification
pending** for 0.1.0. Its deterministic contract/regression tests pass; it has no
native embedding API, so pair it with any supported embedding adapter. First-party
verification and evidence-backed fixes with regression coverage are welcome;
never share credentials or raw provider responses.

## Separate products

**semantix-client**, imported as **semantix_client**, remains the independent HTTP
client for a Semantix service. It has no embedded/local-mode switch.

Optional [provider adapters and custom integrations](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/providers.md)
use borrowed HTTP clients; install only the HTTP extra you need. The default core
keeps its NumPy/Pydantic dependency boundary. Optional
[PostgreSQL/pgvector storage and custom databases](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md)
use `semantix_cache.stores.pgvector.PgVectorStore` with the `[pgvector]` extra.
Schema initialization is explicit; normal cache use performs no DDL. See
[PostgreSQL connection failures and recovery](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#connections-cancellation-and-failures)
for typed startup errors and application-owned recovery decisions.
Optional [Redis storage](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/redis.md)
uses `semantix_cache.stores.redis.RedisStore` with `[redis]`, direct redis-py
(7.4.1, 8.0.1 or stable 8.1.x; locks retain 8.1.0),
asyncio and bounded exact float64 scans. Setup is explicit; supported server
families and verified patches, plus exact Valkey 9.1.2 through the same RedisStore,
are listed in the Redis guide. A directly addressed writable standalone primary with noeviction is required.
See the [source layout](https://github.com/Yoruxyv/semantix/blob/main/packages/cache/src/README.md) for package boundaries.

## Troubleshooting

A cache miss is an ordinary result; configuration, provider and storage failures
are errors. Do not turn those failures into invented miss/write evidence.

| Symptom | Check / next step |
| --- | --- |
| Package or optional driver cannot be imported | Use the application's actual Python environment and the local source/wheel install above. Import persistent stores and provider adapters from their explicit modules. No PyPI release is available yet. |
| SQLite raises `CacheConfigurationError` | Check `sqlite3.sqlite_version` and `sqlite3.threadsafety` in that same interpreter. Follow the [linked-runtime and WAL safety requirements](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#sqlite-local-file-persistence); installing a Python extra cannot patch SQLite. |
| A persistent store rejects its schema or binding | Complete its explicit operator setup with the documented authority; check identity, dimensions, capacity and TTL settings. Preserve existing data and migrations. Never repair a checksum error by editing the migration or adopting foreign tables. |
| `EmbeddingSpaceError` or invalid vectors | Keep embedder/store metadata identical; verify actual output dimensions, finite nonzero values and stable model/preprocessing identity. Use a new matching binding when the embedding space changes. |
| Unexpected hit or miss | Check namespace, response-context revision, expiry, capacity eviction and threshold. Even hits require embedding/lookup. Similarity does not prove answer compatibility; review the [accuracy limits](https://github.com/Yoruxyv/semantix/blob/main/docs/reference/semantic-accuracy-limitations.md). |
| `CacheBusyError` during shutdown | Stop admitting work and drain/cancel application tasks, then allow retained workers/cleanup to finish before closing owned resources. Closing the facade does not close borrowed dependencies. Follow the store-specific recovery guide if cleanup fails. |
| `CacheTimeoutError` / `CacheStoreError` after generation or a write | A timeout does not prove rollback. Reconcile an uncertain mutation before an application-requested retry; see [generation succeeds but persistence fails](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/context-identity-and-migration.md#generation-succeeds-but-persistence-fails). Semantix does not replay the operation automatically. |

Provider wrappers report expected failures as `EmbeddingError`/`GenerationError`;
exceptions from your own generation callable propagate unchanged. Keep credentials,
prompts, answers and raw driver/provider diagnostics out of public logs.

For application-owned inspection, see [optional inspection and administration](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/storage.md#optional-inspection-and-administration).
Its preview/detail results remain sensitive and require application authorization.

## Contributor checks

For environment setup and reviewed evidence validation, see the
[cache contributor workflow](https://github.com/Yoruxyv/semantix/blob/main/docs/guides/development.md#embedded-cache-contributors).

From this directory, contributor checks are below. Supply
`PGVECTOR_TEST_DATABASE_URL` for an explicitly disposable database to execute the
PostgreSQL cases; without it those cases skip. Set `REDIS_TEST_URL` only to
a disposable supported Redis server for Redis conformance/fault tests; required CI rejects
skipped Redis cases. MySQL tests require an owned receipt generated by
`uv run --no-sync python ../../ops/ci/mysql_fixture.py -- uv run --no-sync pytest -m mysql`
with Docker and OpenSSL; never use an ordinary database. The fixture pins MySQL
8.4.12 by default; `--server-version 8.4.11` selects the other verified immutable
image. It removes only its verified owned containers and retains diagnostic volumes
and sanitized logs. Passwords pass through child environments; connection receipts
contain no credentials. See the [fixture security boundary](https://github.com/Yoruxyv/semantix/blob/main/docs/embedded/mysql.md#disposable-verification)
before retaining or sharing diagnostic evidence.
mypy also checks deprecated APIs.

~~~text
uv sync --locked --extra dev
uv run --no-sync ruff check --config ../../ruff.toml .
uv run --no-sync ruff format --config ../../ruff.toml --check .
uv run --no-sync mypy src tests examples
uv run --no-sync pytest --cov=semantix_cache
uv run --no-sync python examples/custom_integration.py
uv run --no-sync python -m examples.custom_store
uv run --no-sync python -m build
uv run --no-sync python -m twine check dist/*
uv run --no-sync python tests/check_artifacts.py
~~~

### Standalone source-distribution tests

The sdist includes runtime sources, examples/conformance tooling, test helpers
and all package test modules **except** these checkout-only tests:

- `tests/test_benchmark_harness.py`
- `tests/test_coalescing_benchmark.py`
- `tests/test_reuse_quality.py`
- `tests/test_reuse_quality_contracts.py`
- `tests/test_provider_live_verify.py`

Those five need repository benchmark/script/evidence trees and still run in the
checkout/CI suite. They are excluded from the archive, not skipped in checkout
pytest. `MANIFEST.in` defines this boundary; `tests/check_artifacts.py` enforces
that the remaining test/helper set is included exactly. Benchmarks and repository
scripts are not shipped to satisfy test imports.

In a fresh development environment, install the built cache wheel with its
`[dev]` extra, unpack the matching sdist, then run from its root:

~~~text
python -B -m pytest tests
~~~

This is the standalone sdist test contract, not the full repository quality gate
or minimal-install promise. Tests require development dependencies; the runtime
still needs only NumPy/Pydantic. PostgreSQL integration cases skip without a
**disposable** `PGVECTOR_TEST_DATABASE_URL`; a skip is not database verification.
Use the checkout for benchmark evidence validation and provider-verifier tests.
