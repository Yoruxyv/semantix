# semantix-cache

Async semantic caching in your Python process. No Semantix server is required.
The runtime supports Python 3.11–3.14 and depends on NumPy and Pydantic.

The distribution name is **semantix-cache** and its import is **semantix_cache**.
**0.1.0 is not yet published.** After publication, install the minimal package with:

~~~bash
python -m pip install semantix-cache
~~~

Before publication, install a built local wheel with
`python -m pip install dist/semantix_cache-0.1.0-py3-none-any.whl`.
See the contributor commands below to build it from this directory.
Publication is a separate release action.

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
completed without errors. See the [experiment methodology](benchmarks/COALESCING.md)
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
[provider deprecation process](../../docs/embedded-providers.md#deprecation-path).
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
[storage guide](../../docs/embedded-storage.md#existing-application-database).
Downgrades are unsupported unless explicitly documented.

For explicit model/tenant/knowledge/output scopes and safe cache migration, see
the [context identity and migration guide](../../docs/context-identity-and-migration.md).

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
does not extend on hits, and expires at the exact monotonic deadline. Metadata
timestamps are aware UTC. Candidate confirmation rechecks revision and expiry.

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
its adapter and store metadata at construction and during operations.

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

The maintained OpenAI, Gemini, and Hugging Face adapters and independent custom
integrations passed live MemoryStore miss → generate → write → confirmed-hit
checks on **2026-10-05**. See the [provider guide](../../docs/embedded-providers.md#010-verification)
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

Optional [provider adapters and custom integrations](../../docs/embedded-providers.md)
use borrowed HTTP clients; install only the HTTP extra you need. The default core
keeps its NumPy/Pydantic dependency boundary. Optional
[PostgreSQL/pgvector storage and custom databases](../../docs/embedded-storage.md)
use `semantix_cache.stores.pgvector.PgVectorStore` with the `[pgvector]` extra.
Schema initialization is explicit; normal cache use performs no DDL.
See the [source layout](src/README.md) for package boundaries.

From this directory, contributor checks are below. Supply
`PGVECTOR_TEST_DATABASE_URL` for an explicitly disposable database to execute the
PostgreSQL cases; without it those cases skip. mypy also checks deprecated APIs.

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
