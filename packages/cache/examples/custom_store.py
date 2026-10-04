"""Small structural store example, not a maintained storage backend.

Replace this application's dictionary with your company's vector-capable service.
The shared conformance tests exercise this implementation without inheritance from
MemoryStore or CacheStore. This example is process-local and non-durable.
"""

import asyncio
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from time import monotonic

from examples.custom_integration import CustomEmbedding, demo_model
from semantix_cache import (
    AsyncSemanticCache,
    CacheClosedError,
    CacheConfigurationError,
    CacheEntry,
    CacheMatch,
    CacheStoreError,
    CacheValidationError,
    EmbeddingSpace,
)


class CompanyCacheStore:
    def __init__(
        self,
        *,
        embedding_space: EmbeddingSpace,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
    ) -> None:
        if (
            isinstance(max_size, bool)
            or not isinstance(max_size, int)
            or not 1 <= max_size <= 5000
        ):
            raise CacheConfigurationError("Invalid example capacity")
        self.embedding_space = embedding_space
        self.default_ttl_seconds = self._ttl(default_ttl_seconds)
        self.capacity = max_size
        self.rows: dict[str, tuple[CacheEntry, float | None, datetime | None, int]] = {}
        self.revision: datetime | None = None
        self.order = 0
        self.closed = False

    @staticmethod
    def _ttl(value: float | None) -> float | None:
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 0 < value <= 31536000
        ):
            raise CacheStoreError("Invalid TTL")
        return float(value)

    def _scope(self, namespace: str, key: str | None = None) -> None:
        if self.closed:
            raise CacheClosedError("Example store is closed")
        if (
            not isinstance(namespace, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", namespace) is None
        ):
            raise CacheValidationError("Invalid namespace")
        if key is not None and re.fullmatch(r"[a-f0-9]{64}", key) is None:
            raise CacheValidationError("Invalid key")
        for old in [
            k
            for k, (_, deadline, _, _) in self.rows.items()
            if deadline is not None and monotonic() >= deadline
        ]:
            del self.rows[old]

    def _vector(self, values: Sequence[float]) -> tuple[float, ...]:
        if (
            isinstance(values, (str, bytes))
            or len(values) != self.embedding_space.dimensions
            or any(
                isinstance(v, bool)
                or not isinstance(v, (float, int))
                or not math.isfinite(v)
                for v in values
            )
        ):
            raise CacheValidationError("Invalid vector")
        norm = math.sqrt(sum(float(v) ** 2 for v in values))
        if not math.isfinite(norm) or norm <= 2.220446049250313e-16:
            raise CacheValidationError("Invalid vector magnitude")
        return tuple(float(v) / norm for v in values)

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        self._scope(namespace)
        query = self._vector(embedding)
        candidates = [
            item for item in self.rows.values() if item[0].namespace == namespace
        ]
        if not candidates:
            return None

        def score(item: tuple[CacheEntry, float | None, datetime | None, int]) -> float:
            return max(
                -1.0,
                min(
                    1.0,
                    math.fsum(
                        a * b for a, b in zip(query, item[0].embedding, strict=True)
                    ),
                ),
            )

        best = min(
            candidates,
            key=lambda item: (-score(item), item[0].created_at, item[0].cache_key),
        )
        return CacheMatch(
            entry=best[0], similarity_score=score(best), expires_at=best[2]
        )

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        self._scope(namespace, cache_key)
        if expected_created_at.tzinfo is None:
            raise CacheValidationError("Expected aware revision")
        row = self.rows.get(cache_key)
        if (
            row is None
            or row[0].namespace != namespace
            or row[0].created_at != expected_created_at
        ):
            return False
        self.order += 1
        self.rows[cache_key] = (*row[:3], self.order)
        return True

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        if self.closed:
            raise CacheClosedError("Example store is closed")
        if not isinstance(entry, CacheEntry):
            raise CacheStoreError("Invalid stored entry")
        self._scope(entry.namespace)
        try:
            entry = CacheEntry.model_validate(entry.model_dump())
            vector = self._vector(entry.embedding)
            requested = self._ttl(ttl_seconds)
        except (ValueError, CacheValidationError):
            raise CacheStoreError("Invalid stored entry") from None
        ttl = self.default_ttl_seconds if requested is None else requested
        if ttl is not None and self.default_ttl_seconds is not None:
            ttl = min(ttl, self.default_ttl_seconds)
        revision = (
            entry.created_at
            if self.revision is None
            else max(entry.created_at, self.revision + timedelta(microseconds=1))
        )
        self.revision = revision
        self.order += 1
        self.rows[entry.cache_key] = (
            entry.model_copy(update={"embedding": vector, "created_at": revision}),
            None if ttl is None else monotonic() + ttl,
            None if ttl is None else datetime.now(UTC) + timedelta(seconds=ttl),
            self.order,
        )
        while len(self.rows) > self.capacity:
            oldest = min(self.rows, key=lambda key: self.rows[key][3])
            del self.rows[oldest]

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        self._scope(namespace, cache_key)
        row = self.rows.get(cache_key)
        if row is None or row[0].namespace != namespace:
            return False
        del self.rows[cache_key]
        return True

    async def clear(self, *, namespace: str) -> int:
        self._scope(namespace)
        keys = [key for key, row in self.rows.items() if row[0].namespace == namespace]
        for key in keys:
            del self.rows[key]
        return len(keys)

    async def aclose(self) -> None:
        self.closed = True
        self.rows.clear()


async def main() -> None:
    embedder = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="example-company-v1", dimensions=2),
        embed_text=demo_model,
    )
    store = CompanyCacheStore(embedding_space=embedder.embedding_space)

    async def generate(prompt: str) -> str:
        return "Application-owned response for: " + prompt

    try:
        async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
            first = await cache.resolve("support question", generate=generate)
            second = await cache.resolve("support question", generate=generate)
            if not first.cache_written or not second.cache_hit:
                raise RuntimeError("Custom store example did not reuse its response")
    finally:
        await store.aclose()


if __name__ == "__main__":
    asyncio.run(main())
