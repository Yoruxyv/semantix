"""Async semantic caching independent of the Semantix HTTP server."""

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
