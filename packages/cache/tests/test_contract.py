import inspect
from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

import semantix_cache
from semantix_cache import (
    AsyncSemanticCache,
    CacheEntry,
    CacheHit,
    CacheMatch,
    CachePolicy,
    CacheResult,
    EmbeddingSpace,
    MemoryStore,
    SemantixCacheError,
)
from semantix_cache._semantics import normalized_vector, prompt_cache_key

from .conftest import Adapter
from .test_memory import entry


def test_public_exports_and_signatures() -> None:
    expected = {
        "AsyncSemanticCache",
        "CachePolicy",
        "CacheResult",
        "CacheHit",
        "CacheEntry",
        "CacheMatch",
        "EmbeddingSpace",
        "EmbeddingAdapter",
        "GenerationCallable",
        "CacheStore",
        "MemoryStore",
        "SemantixCacheError",
        "CacheConfigurationError",
        "CacheValidationError",
        "EmbeddingError",
        "EmbeddingSpaceError",
        "GenerationError",
        "CacheStoreError",
        "CacheTimeoutError",
        "CacheClosedError",
        "CacheBusyError",
    }
    assert set(semantix_cache.__all__) == expected
    assert not hasattr(semantix_cache, "SemanticCache")
    for name in expected:
        exported = getattr(semantix_cache, name)
        if name.endswith("Error"):
            assert issubclass(exported, SemantixCacheError)
    assert {member.name: member.value for member in CachePolicy} == {
        "NORMAL": "normal",
        "READ_ONLY": "read_only",
        "REFRESH": "refresh",
        "BYPASS": "bypass",
        "PRIVATE": "private",
    }
    constructor = inspect.signature(AsyncSemanticCache)
    assert list(constructor.parameters) == [
        "embedder",
        "store",
        "similarity_threshold",
        "prompt_normalizer",
        "operation_timeout_seconds",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in constructor.parameters.values()
    )
    assert constructor.parameters["similarity_threshold"].default == pytest.approx(0.92)
    assert constructor.parameters["operation_timeout_seconds"].default == pytest.approx(
        30.0
    )
    methods = {
        "get": ["self", "prompt", "namespace"],
        "set": ["self", "prompt", "response", "namespace", "cache_ttl_seconds"],
        "resolve": [
            "self",
            "prompt",
            "generate",
            "namespace",
            "policy",
            "cache_ttl_seconds",
        ],
        "delete": ["self", "cache_key", "namespace"],
        "clear": ["self", "namespace"],
        "aclose": ["self"],
    }
    for name, parameters in methods.items():
        method = getattr(AsyncSemanticCache, name)
        assert inspect.iscoroutinefunction(method)
        signature = inspect.signature(method)
        assert list(signature.parameters) == parameters
        if "namespace" in signature.parameters:
            assert signature.parameters["namespace"].default == "default"
    assert set(CacheEntry.model_fields) == {
        "cache_key",
        "namespace",
        "prompt",
        "response",
        "embedding",
        "created_at",
    }
    assert set(CacheMatch.model_fields) == {"entry", "similarity_score", "expires_at"}
    assert set(CacheHit.model_fields) == {
        "response",
        "similarity_score",
        "similarity_threshold",
        "matched_prompt",
        "matched_cache_key",
        "cache_entry_created_at",
        "cache_entry_age_seconds",
        "expires_at",
    }
    assert set(CacheResult.model_fields) == {
        "response",
        "cache_hit",
        "similarity_score",
        "similarity_threshold",
        "matched_prompt",
        "matched_cache_key",
        "cache_entry_created_at",
        "cache_entry_age_seconds",
        "generation_skipped",
        "provider_called",
        "latency_ms",
        "cache_written",
    }


def test_models_immutable_and_safe_repr() -> None:
    payload = "sensitive payload"
    value = entry(payload)
    assert payload not in repr(value)
    match = CacheMatch(entry=value, similarity_score=1.0, expires_at=None)
    assert payload not in repr(match)
    assign = value.__setattr__
    with pytest.raises(ValidationError):
        assign("prompt", "changed")
    with pytest.raises(TypeError):
        cast(list[float], value.embedding)[0] = 9.0
    with pytest.raises(ValidationError):
        EmbeddingSpace.model_validate(
            {"identity": "test", "dimensions": 2, "unexpected": True}
        )
    assert value.created_at.tzinfo == UTC


@pytest.mark.parametrize("identity", ["", " ", 2])
def test_identity_validation(identity: object) -> None:
    with pytest.raises(ValidationError):
        EmbeddingSpace(identity=cast(str, identity), dimensions=2)


@pytest.mark.parametrize("dimensions", [0, -1, True, 1.5])
def test_dimensions_validation(dimensions: object) -> None:
    with pytest.raises(ValidationError):
        EmbeddingSpace(identity="test", dimensions=cast(int, dimensions))


def test_timestamp_key_and_vector_validation() -> None:
    value = entry("prompt")
    invalid_updates: list[dict[str, object]] = [
        {"created_at": datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None)},
        {"cache_key": "a" * 64},
        {"embedding": ()},
        {"embedding": [True, 0]},
    ]
    for updates in invalid_updates:
        with pytest.raises(ValidationError):
            CacheEntry.model_validate(value.model_dump() | updates)
    vector = normalized_vector([3.0, 4.0], dimensions=2)
    assert list(vector) == pytest.approx([0.6, 0.8])
    assert prompt_cache_key("same", namespace="a") != prompt_cache_key(
        "same", namespace="b"
    )


async def test_result_model_checks(adapter: Adapter) -> None:
    cache = AsyncSemanticCache(
        embedder=adapter, store=MemoryStore(embedding_space=adapter.embedding_space)
    )
    await cache.set("seed", "cached")
    hit = await cache.get("question")
    assert hit is not None
    with pytest.raises(ValidationError):
        CacheHit.model_validate(hit.model_dump() | {"similarity_score": 0.1})

    async def generation(prompt: str) -> str:
        return "generated"

    result = await cache.resolve("question", generate=generation)
    invalid_updates: list[dict[str, object]] = [
        {"cache_written": True},
        {"provider_called": True},
        {"similarity_score": None},
        {"matched_prompt": None},
        {"similarity_score": 0.1},
        {"latency_ms": True},
        {"latency_ms": float("inf")},
    ]
    for updates in invalid_updates:
        with pytest.raises(ValidationError):
            CacheResult.model_validate(result.model_dump() | updates)
    miss = await cache.resolve(
        "question", generate=generation, policy=CachePolicy.BYPASS
    )
    invalid_miss_updates: list[dict[str, object]] = [
        {"matched_prompt": "leak"},
        {"provider_called": False},
        {"generation_skipped": True},
    ]
    for updates in invalid_miss_updates:
        with pytest.raises(ValidationError):
            CacheResult.model_validate(miss.model_dump() | updates)
