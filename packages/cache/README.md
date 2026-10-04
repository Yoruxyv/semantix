# semantix-cache

Async semantic caching in your Python process. No Semantix server is required.
The runtime supports Python 3.11–3.14 and depends on NumPy and Pydantic.

Install a built local wheel with `python -m pip install dist/semantix_cache-0.1.0-py3-none-any.whl`.
The distribution name is **semantix-cache** and its import is **semantix_cache**.
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
not block the event loop. No automatic retry or miss coalescing is provided.

Lookup and write failures raise; generation followed by write failure does not return
a successful resolution. Expected integration failures use safe embedded errors;
programming bugs propagate. Package error messages and model repr omit payloads.
Explicit model serialization contains its documented data and must be handled by the
application with appropriate care.

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
