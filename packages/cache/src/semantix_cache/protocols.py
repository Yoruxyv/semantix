from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol, TypeAlias

from .models import CacheEntry, CacheMatch, EmbeddingSpace

GenerationCallable: TypeAlias = Callable[[str], Awaitable[str]]


class EmbeddingAdapter(Protocol):
    @property
    def embedding_space(self) -> EmbeddingSpace: ...

    async def embed(self, text: str) -> Sequence[float]: ...


class CacheStore(Protocol):
    @property
    def embedding_space(self) -> EmbeddingSpace: ...

    @property
    def default_ttl_seconds(self) -> float | None: ...

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None: ...

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool: ...

    async def put(
        self, entry: CacheEntry, *, ttl_seconds: float | None = None
    ) -> None: ...

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool: ...

    async def clear(self, *, namespace: str) -> int: ...

    async def aclose(self) -> None: ...
