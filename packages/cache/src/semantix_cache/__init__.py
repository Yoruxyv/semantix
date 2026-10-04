"""In-process semantic caching for asynchronous Python applications.

The semantix-cache distribution imports as semantix_cache and runs inside your
Python process; no Semantix FastAPI server is required. Version 0.1.0 is async-only.
It is the primary intended first public PyPI package. The separate semantix_client
package provides the optional/reference HTTP client for a running Semantix server.

Public surface
--------------
AsyncSemanticCache is the high-level entry point: lookup() returns a CacheHit or
None, and resolve() returns a CacheResult describing the response, cache decision
and generation evidence. CachePolicy controls permitted reads and writes.
MemoryStore is the supplied bounded, process-local CacheStore. Optional persistent
PostgreSQL/pgvector storage lives in semantix_cache.stores.pgvector.PgVectorStore;
install the pgvector extra and initialize its owned schema explicitly. Root imports
do not load asyncpg. Supplied pools are borrowed; connect() creates an owned pool.

EmbeddingAdapter describes a custom async embedder. Its immutable EmbeddingSpace
identifies compatible vectors and their dimensions. GenerationCallable is an async
prompt-to-text callable. CacheStore is the structural store protocol; CacheEntry
and CacheMatch support store implementations. Custom EmbeddingAdapter,
GenerationCallable and CacheStore implementations need no provider registry or
inheritance from library classes.

SemantixCacheError is the typed error-family base. Configuration, validation and
embedding-space errors distinguish invalid inputs; EmbeddingError,
GenerationError and CacheStoreError describe integration failures. CacheClosedError,
CacheBusyError and CacheTimeoutError describe lifecycle and deadline failures.

Quick start
-----------
Given your existing embedder and async generation callable::

    from semantix_cache import AsyncSemanticCache, MemoryStore

    async def answer(my_embedder, my_generation_callable):
        async with MemoryStore(
            embedding_space=my_embedder.embedding_space
        ) as store:
            async with AsyncSemanticCache(
                embedder=my_embedder,
                store=store,
            ) as cache:
                result = await cache.resolve(
                    prompt="How do I update my delivery address?",
                    namespace="support",
                    generate=my_generation_callable,
                )
                return result

Use async context managers or await aclose() for resources you own. The cache
borrows its embedder, store and generation callable and does not close them.
Drain or cancel active work before closing; the nested example closes the cache
before its application-owned store.

Maintained provider adapters live under semantix_cache.adapters. Import their
provider modules explicitly with the appropriate optional HTTP dependencies;
provider modules and optional dependencies are not imported by this minimal root
package. Provider HTTP clients remain application-owned. See the package README
and provider guide for integration configuration and safety details.
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
