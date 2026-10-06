"""Development-only CacheStore 0.1.x contract; never imported by the runtime."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import pytest

from semantix_cache import CacheStore, EmbeddingSpace

CONTRACT_VERSION = "0.1.x"
SPACE = EmbeddingSpace(identity="conformance-v1", dimensions=2)


@dataclass(frozen=True)
class HitMetadata:
    """Optional persisted metadata, outside the CacheStore protocol."""

    count: int
    last_accessed: datetime | None


@dataclass(frozen=True)
class StoreCase:
    """A real store plus backend-owned deterministic test controls.

    expire advances authoritative expiry for finite entries in this binding.
    read_hit_metadata is supplied only by backends that expose persisted counters.
    block_lookup must gate a real nonempty lookup, signal admission, then release
    and drain backend work on exit, including after cancellation or a timeout.
    Factory teardown owns all stores/resources; the kit does not own their pools.
    """

    store: CacheStore
    expire: Callable[[], Awaitable[None]]
    read_hit_metadata: Callable[[str, str], Awaitable[HitMetadata | None]] | None = None
    block_lookup: Callable[[], AbstractAsyncContextManager[asyncio.Event]] | None = None


class StoreFactory(Protocol):
    """Fresh bindings; different spaces share backend tables when applicable."""

    async def __call__(
        self,
        capacity: int = 32,
        ttl: float | None = None,
        *,
        space: EmbeddingSpace = SPACE,
    ) -> StoreCase: ...


# Imported test assertions get pytest's normal explanations for external authors.
pytest.register_assert_rewrite(
    "examples.store_conformance.cases", "examples.store_conformance.interactions"
)
from .interactions import StoreConformance  # noqa: E402

__all__ = [
    "CONTRACT_VERSION",
    "SPACE",
    "HitMetadata",
    "StoreCase",
    "StoreConformance",
    "StoreFactory",
]
