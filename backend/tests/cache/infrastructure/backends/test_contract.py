import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import uuid4

import pytest

from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.metadata import TRUNCATED_RESPONSE_PREVIEW_MESSAGE
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE
from app.cache.domain.protocols import CacheBackend
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.cache.infrastructure.factory import cache_backend_lifespan
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from tests.cache.infrastructure.backends.support import cache_entry
from tests.support import TEST_EMBEDDING_DIMENSIONS, unit_vector

BackendBuilder = Callable[
    [int, float | None],
    AbstractAsyncContextManager[CacheBackend],
]


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "pgvector",
            marks=pytest.mark.pgvector,
        ),
    ]
)
def backend_builder(
    request: pytest.FixtureRequest,
) -> BackendBuilder:
    backend_name = str(request.param)
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if backend_name == "pgvector" and not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    @asynccontextmanager
    async def build(
        max_size: int,
        ttl_seconds: float | None,
    ) -> AsyncIterator[CacheBackend]:
        settings = Settings(
            cache_backend=backend_name,
            database_url=database_url,
            max_cache_size=max_size,
            cache_ttl_seconds=ttl_seconds,
            hf_api_key="test-only-placeholder",
            hf_embedding_model=f"phase7-contract-{uuid4().hex}",
            hf_embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
            allowed_origins=["http://localhost:5173"],
        )
        async with cache_backend_lifespan(
            settings,
            dimensions=TEST_EMBEDDING_DIMENSIONS,
            embedding_space=settings.embedding_space,
        ) as backend:
            try:
                yield backend
            finally:
                await backend.clear(None)

    return build


@pytest.mark.asyncio
async def test_similarity_and_entry_metadata(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, 60) as backend:
        alpha = cache_entry(
            "alpha prompt",
            "a" * 300,
            vector_index=0,
        )
        beta = cache_entry(
            "beta prompt",
            "beta response",
            vector_index=1,
        )
        await backend.put(alpha)
        await asyncio.sleep(0.002)
        await backend.put(beta)

        nearest = await backend.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert nearest is not None
        assert nearest.entry.prompt == "alpha prompt"
        assert nearest.similarity_score == pytest.approx(1.0)
        assert await backend.record_hit(
            alpha.cache_key,
            expected_created_at=alpha.created_at,
        )

        listing = await backend.list_entries(
            offset=0,
            limit=10,
            namespace=None,
            search=" ALPHA ",
            sort="most_hit",
        )
        assert listing.total == 1
        metadata = listing.items[0]
        assert metadata.hit_count == 1
        assert metadata.last_accessed_at is not None
        assert metadata.recency_rank == 1
        assert metadata.response_preview == TRUNCATED_RESPONSE_PREVIEW_MESSAGE
        assert metadata.response_preview_truncated is True
        assert metadata.response is None
        assert metadata.expires_at is not None
        assert metadata.remaining_ttl_seconds is not None
        assert metadata.remaining_ttl_seconds > 0
        assert "embedding" not in metadata.model_dump()

        detail = await backend.get_entry(
            alpha.cache_key,
            authorized_namespaces=None,
        )
        assert detail is not None
        assert detail.response == "a" * 300
        assert detail.response_preview == TRUNCATED_RESPONSE_PREVIEW_MESSAGE
        assert detail.response_preview_truncated is True


@pytest.mark.asyncio
async def test_sort_pagination_delete_and_clear(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, None) as backend:
        prompts = ("alpha", "beta", "gamma")
        for index, prompt in enumerate(prompts):
            await backend.put(
                cache_entry(
                    prompt,
                    f"{prompt} response",
                    vector_index=index,
                )
            )
            await asyncio.sleep(0.002)

        newest = await backend.list_entries(
            offset=0,
            limit=2,
            namespace=None,
            search=None,
            sort="newest",
        )
        assert [item.prompt for item in newest.items] == [
            "gamma",
            "beta",
        ]
        assert newest.has_more

        oldest = await backend.list_entries(
            offset=0,
            limit=10,
            namespace=None,
            search=None,
            sort="oldest",
        )
        assert [item.prompt for item in oldest.items] == list(prompts)

        alpha_key = prompt_cache_key("alpha")
        alpha = await backend.get_entry(
            alpha_key,
            authorized_namespaces=None,
        )
        assert alpha is not None
        assert alpha.expires_at is None
        assert await backend.delete_entry(
            alpha_key,
            authorized_namespaces=None,
        )
        assert (
            await backend.get_entry(
                alpha_key,
                authorized_namespaces=None,
            )
            is None
        )

        await backend.clear(None)
        assert (
            await backend.list_entries(
                offset=0,
                limit=10,
                namespace=None,
                search=None,
                sort="newest",
            )
        ).total == 0


@pytest.mark.asyncio
async def test_expiry_and_lru_capacity(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(1, 1) as backend:
        expiring = cache_entry(
            "expiring",
            "response",
            vector_index=0,
        )
        await backend.put(expiring)
        await asyncio.sleep(1.05)
        assert (
            await backend.get_entry(
                expiring.cache_key,
                authorized_namespaces=None,
            )
            is None
        )

    async with backend_builder(1, None) as backend:
        alpha = cache_entry(
            "alpha",
            "alpha response",
            vector_index=0,
        )
        beta = cache_entry(
            "beta",
            "beta response",
            vector_index=1,
        ).model_copy(
            update={
                "created_at": alpha.created_at,
            }
        )
        await backend.put(alpha)
        await backend.put(beta)
        assert (
            await backend.get_entry(
                alpha.cache_key,
                authorized_namespaces=None,
            )
            is None
        )
        assert (
            await backend.get_entry(
                beta.cache_key,
                authorized_namespaces=None,
            )
            is not None
        )


@pytest.mark.asyncio
async def test_per_write_ttl_overrides_default_and_replacement(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, 60) as backend:
        original = cache_entry("ttl override", "original", vector_index=0)
        await backend.put(original, ttl_seconds=30)
        first = await backend.get_entry(
            original.cache_key,
            authorized_namespaces=None,
        )
        assert first is not None
        assert first.remaining_ttl_seconds == pytest.approx(30, abs=2)

        replacement = original.model_copy(update={"response": "replacement"})
        await backend.put(replacement, ttl_seconds=10)
        current = await backend.get_entry(
            original.cache_key,
            authorized_namespaces=None,
        )
        assert current is not None
        assert current.response == "replacement"
        assert current.remaining_ttl_seconds == pytest.approx(10, abs=2)

    async with backend_builder(10, None) as backend:
        requested = cache_entry("requested ttl", "response", vector_index=0)
        await backend.put(requested, ttl_seconds=30)
        metadata = await backend.get_entry(
            requested.cache_key,
            authorized_namespaces=None,
        )
        assert metadata is not None
        assert metadata.remaining_ttl_seconds == pytest.approx(30, abs=2)


@pytest.mark.asyncio
async def test_cache_hit_does_not_extend_entry_ttl(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, 60) as backend:
        entry = cache_entry("fixed ttl", "response", vector_index=0)
        await backend.put(entry, ttl_seconds=30)
        before = await backend.get_entry(
            entry.cache_key,
            authorized_namespaces=None,
        )
        candidate = await backend.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert before is not None
        assert candidate is not None
        assert await backend.record_hit(
            candidate.entry.cache_key,
            expected_created_at=candidate.entry.created_at,
        )
        after = await backend.get_entry(
            entry.cache_key,
            authorized_namespaces=None,
        )

        assert after is not None
        assert after.expires_at == before.expires_at


@pytest.mark.asyncio
async def test_memory_ttl_expiry_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(
        "app.cache.infrastructure.backends.memory.time.monotonic", lambda: now
    )
    backend = InMemoryCacheBackend(
        10,
        60,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
    )
    entry = cache_entry("deterministic ttl", "response", vector_index=0)

    await backend.put(entry, ttl_seconds=10)
    now = 109.0
    assert await backend.get_entry(entry.cache_key, authorized_namespaces=None)
    now = 110.0
    assert not await backend.get_entry(entry.cache_key, authorized_namespaces=None)

    now = 200.0
    await backend.put(entry)
    now = 259.0
    assert await backend.get_entry(entry.cache_key, authorized_namespaces=None)
    now = 260.0
    assert not await backend.get_entry(entry.cache_key, authorized_namespaces=None)

    no_expiry = InMemoryCacheBackend(
        10,
        None,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
    )
    now = 300.0
    await no_expiry.put(entry)
    now = 1_000_000.0
    assert await no_expiry.get_entry(entry.cache_key, authorized_namespaces=None)


@pytest.mark.asyncio
async def test_entry_operations_enforce_namespace_scope(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, None) as backend:
        alpha = cache_entry(
            "alpha prompt",
            "alpha response",
            namespace="tenant-alpha",
            vector_index=0,
        )
        beta = cache_entry(
            "beta prompt",
            "beta response",
            namespace="tenant-beta",
            vector_index=1,
        )
        await backend.put(alpha)
        await backend.put(beta)

        alpha_scope = frozenset({"tenant-alpha"})
        assert (
            await backend.get_entry(
                beta.cache_key,
                authorized_namespaces=alpha_scope,
            )
            is None
        )
        assert not await backend.delete_entry(
            beta.cache_key,
            authorized_namespaces=alpha_scope,
        )
        assert (
            await backend.get_entry(
                beta.cache_key,
                authorized_namespaces=None,
            )
            is not None
        )

        assert await backend.delete_entry(
            beta.cache_key,
            authorized_namespaces=None,
        )
        assert (
            await backend.get_entry(
                alpha.cache_key,
                authorized_namespaces=alpha_scope,
            )
            is not None
        )


@pytest.mark.asyncio
async def test_namespace_filtering_stats_and_clear(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, None) as backend:
        alpha = cache_entry(
            "shared prompt",
            "alpha response",
            namespace="tenant-alpha",
            vector_index=0,
        )
        beta = cache_entry(
            "shared prompt",
            "beta response",
            namespace="tenant-beta",
            vector_index=0,
        )
        await backend.put(alpha)
        assert (
            await backend.find_nearest(
                unit_vector(),
                namespace="tenant-beta",
            )
            is None
        )
        await backend.put(beta)

        nearest = await backend.find_nearest(
            unit_vector(),
            namespace="tenant-alpha",
        )
        assert nearest is not None
        assert nearest.entry.response == "alpha response"
        assert await backend.record_hit(
            alpha.cache_key,
            expected_created_at=alpha.created_at,
        )
        await backend.record_miss("tenant-alpha")
        await backend.record_miss("tenant-beta")

        global_stats = await backend.stats(None)
        alpha_stats = await backend.stats("tenant-alpha")
        beta_stats = await backend.stats("tenant-beta")
        assert global_stats.model_dump() == {
            "size": 2,
            "hits": 1,
            "misses": 2,
            "hit_rate": pytest.approx(1 / 3),
        }
        assert alpha_stats.model_dump() == {
            "size": 1,
            "hits": 1,
            "misses": 1,
            "hit_rate": 0.5,
        }
        assert beta_stats.model_dump() == {
            "size": 1,
            "hits": 0,
            "misses": 1,
            "hit_rate": 0.0,
        }

        listing = await backend.list_entries(
            offset=0,
            limit=10,
            namespace="tenant-alpha",
            search=None,
            sort="newest",
        )
        assert [item.namespace for item in listing.items] == ["tenant-alpha"]

        await backend.clear("tenant-alpha")
        assert (await backend.stats("tenant-alpha")).model_dump() == {
            "size": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
        }
        assert (await backend.stats(None)).model_dump() == {
            "size": 1,
            "hits": 0,
            "misses": 1,
            "hit_rate": 0.0,
        }


@pytest.mark.asyncio
async def test_invalid_vectors_are_rejected_consistently(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, None) as backend:
        with pytest.raises(CacheStorageError, match="Zero magnitude"):
            await backend.find_nearest(
                [0.0] * TEST_EMBEDDING_DIMENSIONS,
                namespace=DEFAULT_CACHE_NAMESPACE,
            )


@pytest.mark.asyncio
async def test_record_hit_rejects_an_overwritten_candidate(
    backend_builder: BackendBuilder,
) -> None:
    async with backend_builder(10, None) as backend:
        original = cache_entry(
            "same key",
            "old response",
            vector_index=0,
        )
        replacement = original.model_copy(
            update={
                "response": "new response",
            }
        )
        await backend.put(original)
        candidate = await backend.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert candidate is not None
        await backend.put(replacement)
        current_candidate = await backend.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert current_candidate is not None
        assert current_candidate.entry.response == "new response"

        assert not await backend.record_hit(
            candidate.entry.cache_key,
            expected_created_at=candidate.entry.created_at,
        )
        assert await backend.record_hit(
            current_candidate.entry.cache_key,
            expected_created_at=current_candidate.entry.created_at,
        )
