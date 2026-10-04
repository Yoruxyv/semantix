"""Semantic caching inside an asynchronous Python application.

Semantix reuses a previously generated response when a new prompt's embedding is
sufficiently similar to an unexpired entry in the same namespace and embedding
space. A hit skips generation; the embedding and lookup still happen. Applications
choose the similarity threshold and which responses are appropriate to reuse.

The ``semantix-cache`` distribution imports as ``semantix_cache``. It runs in your
process without a Semantix FastAPI server. Version 0.1.0 exposes an async-only
engine and is the primary intended first public PyPI package. For an existing
server's HTTP API, use the separate ``semantix_client`` package.

Public components
-----------------
AsyncSemanticCache
    Reusable facade over an embedder and store. ``get()`` returns a ``CacheHit`` or
    ``None``; ``set()`` stores approved response text; ``resolve()`` performs
    lookup, generation on a miss, and a policy-permitted write.
CachePolicy
    ``NORMAL`` reads and writes; ``READ_ONLY`` reads and generates on a miss
    without writing; ``REFRESH`` generates and writes without reading.
    ``BYPASS`` and ``PRIVATE`` neither read nor write the cache.
CacheHit, CacheResult
    Immutable response and decision evidence. ``CacheResult`` includes hit status,
    similarity/threshold, generation-call evidence, latency and write status.
    ``CacheEntry`` and ``CacheMatch`` describe the lower-level store boundary.
EmbeddingAdapter, EmbeddingSpace
    A structural async ``embed(text)`` integration and its immutable vector-space
    identity/dimensions. Identity must distinguish model/revision, preprocessing
    and pooling; equal dimensions alone do not imply compatible embeddings.
GenerationCallable
    An async prompt-to-text function, or an object with async ``__call__``.
    Supply it as ``generate=`` to ``resolve()``. A maintained generation adapter's
    bound ``generate`` method is also suitable. The application owns generation
    context, credentials and approval of the completed response.
CacheStore, MemoryStore
    The structural storage protocol and bounded in-memory implementation.
    Custom stores need no inheritance, registry or database driver.

Matching and retention
----------------------
Search is scoped to one concrete namespace and embedding space, uses cosine
similarity, and accepts scores at or above the configured threshold. Namespaces
isolate entries; they do not authenticate callers. Version a namespace when
response context or generation configuration changes. A prompt normalizer affects
embedding/matching text; it does not replace the prompt sent to generation.

A missing ``cache_ttl_seconds`` uses the store default. A requested TTL may shorten
but cannot extend a finite default; ``default_ttl_seconds=None`` permits entries
without expiry. Hits do not extend TTL. TTL overrides require a write-enabled
policy. Stores have bounded capacity, so an unexpired entry can still be evicted.

Lifecycle and extensions
------------------------
Reuse the cache, embedder and store across requests. The cache borrows its
embedder, store and generation callable and does not close them. Use async context
managers or ``aclose()`` for resources you own; drain/cancel active work before
closing. Built-in cache/store/adapter wrappers raise ``CacheBusyError`` when
closed during active work; a closed cache cannot reopen. Operations have a finite
configured deadline and cancellation propagates.

``semantix_cache.adapters`` contains explicit provider modules; import the adapter
from its module with the appropriate optional extra. HTTP clients remain
application-owned. ``semantix_cache.stores.pgvector.PgVectorStore`` supplies optional
PostgreSQL persistence with ``semantix-cache[pgvector]``. A supplied pool is borrowed;
``await PgVectorStore.connect(...)`` owns its pool. Schema initialization is
explicit, requires migration authority, and is separate from ordinary cache use.

The root package needs NumPy and Pydantic, but does not load HTTPX, asyncpg,
FastAPI or provider SDKs. Custom ``EmbeddingAdapter``, ``GenerationCallable`` and
``CacheStore`` integrations remain available for unsupported providers or stores.

Errors derive from ``SemantixCacheError``: configuration/validation/space errors
identify invalid inputs; ``EmbeddingError``, ``GenerationError`` and
``CacheStoreError`` identify integration failures; ``CacheClosedError``,
``CacheBusyError`` and ``CacheTimeoutError`` identify lifecycle or deadline
failures. Consult the specific error's API and your integration's contract when
deciding how to handle it.

Runnable example
----------------
This deterministic toy embedder returns one fixed vector to demonstrate lifecycle
and repeated-prompt reuse without network access. Replace it with your semantic
embedding integration for application use::

    import asyncio
    from semantix_cache import AsyncSemanticCache, EmbeddingSpace, MemoryStore

    class DemoEmbedding:
        embedding_space = EmbeddingSpace(identity="demo-fixed-v1", dimensions=2)

        async def embed(self, text: str) -> tuple[float, float]:
            return (1.0, 0.0)

    async def generate(prompt: str) -> str:
        return "Open account settings to update your delivery address."

    async def main() -> None:
        embedder = DemoEmbedding()
        async with MemoryStore(embedding_space=embedder.embedding_space) as store:
            async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
                first = await cache.resolve(
                    "How do I update my delivery address?",
                    namespace="support", generate=generate,
                )
                second = await cache.resolve(
                    "How do I update my delivery address?",
                    namespace="support", generate=generate,
                )
                assert first.cache_written and second.cache_hit
                assert first.response == second.response

    asyncio.run(main())

Finding more detail
-------------------
Use ``help(AsyncSemanticCache)`` or inspect ``engine``, ``models``, ``policies`` and
``protocols`` for signatures and typed contracts. Repository guides:

- https://github.com/Yoruxyv/semantix/blob/main/packages/cache/README.md
- https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-providers.md
- https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-storage.md
"""

from .engine import AsyncSemanticCache
from .errors import (
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingError,
    EmbeddingSpaceError,
    GenerationError,
    SemantixCacheError,
)
from .memory import MemoryStore
from .models import CacheEntry, CacheHit, CacheMatch, CacheResult, EmbeddingSpace
from .policies import CachePolicy
from .protocols import CacheStore, EmbeddingAdapter, GenerationCallable

__all__ = [
    "AsyncSemanticCache",
    "CacheBusyError",
    "CacheClosedError",
    "CacheConfigurationError",
    "CacheEntry",
    "CacheHit",
    "CacheMatch",
    "CachePolicy",
    "CacheResult",
    "CacheStore",
    "CacheStoreError",
    "CacheTimeoutError",
    "CacheValidationError",
    "EmbeddingAdapter",
    "EmbeddingError",
    "EmbeddingSpace",
    "EmbeddingSpaceError",
    "GenerationCallable",
    "GenerationError",
    "MemoryStore",
    "SemantixCacheError",
]
