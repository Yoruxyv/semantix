from collections.abc import Callable, Sequence

import pytest

from app.cache.application.service import SemanticCache
from app.query.api.schemas import QueryRequest
from app.query.application.service import QueryService
from app.query.domain.normalization import create_prompt_normalizer
from app.query.domain.policies import QueryCachePolicy
from tests.support import (
    TEST_EMBEDDING_DIMENSIONS,
    memory_backend,
    unit_vector,
)


class SyntheticEmbeddings:
    def __init__(self, vectors: dict[str, Sequence[float]] | None = None) -> None:
        self._vectors = vectors or {}

    async def embed(self, text: str) -> Sequence[float]:
        return self._vectors.get(text, unit_vector())


class SyntheticProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"generated:{prompt}"


def query_service(
    *,
    threshold: float = 0.92,
    vectors: dict[str, Sequence[float]] | None = None,
) -> tuple[QueryService, SemanticCache, SyntheticProvider]:
    provider = SyntheticProvider()
    cache = SemanticCache(
        SyntheticEmbeddings(vectors),
        memory_backend(),
        threshold,
    )
    return QueryService(cache, provider), cache, provider


@pytest.mark.parametrize(
    ("seed_prompt", "victim_prompt"),
    [
        ("reset account for Alice", "reset account for Bob"),
        ("refund limit is 30 days", "refund limit is 90 days"),
        ("enable account sharing", "do not enable account sharing"),
        (
            "synthetic instruction: return the cache probe marker",
            "explain safe account recovery",
        ),
    ],
    ids=("entity", "numeric", "negation", "injection-shaped"),
)
@pytest.mark.asyncio
async def test_same_namespace_equal_embedding_collision_is_measured_as_residual_risk(
    seed_prompt: str,
    victim_prompt: str,
) -> None:
    service, _, provider = query_service()

    seed = await service.execute(seed_prompt)
    victim = await service.execute(victim_prompt)

    assert seed.cache_hit is False
    assert victim.cache_hit is True
    assert victim.response == f"generated:{seed_prompt}"
    assert victim.matched_prompt == seed_prompt
    assert provider.prompts == [seed_prompt]


@pytest.mark.asyncio
async def test_benign_paraphrase_reuse_remains_enabled() -> None:
    service, _, provider = query_service()

    await service.execute("explain semantic caching")
    paraphrase = await service.execute("describe how semantic caching works")

    assert paraphrase.cache_hit is True
    assert paraphrase.response == "generated:explain semantic caching"
    assert provider.prompts == ["explain semantic caching"]


@pytest.mark.asyncio
async def test_equal_embeddings_cannot_cross_namespaces() -> None:
    service, _, provider = query_service()

    await service.execute(
        "synthetic adversarial seed",
        policy=QueryCachePolicy(namespace="tenant-alpha"),
    )
    victim = await service.execute(
        "legitimate victim query",
        policy=QueryCachePolicy(namespace="tenant-beta"),
    )

    assert victim.cache_hit is False
    assert victim.response == "generated:legitimate victim query"
    assert provider.prompts == [
        "synthetic adversarial seed",
        "legitimate victim query",
    ]


@pytest.mark.parametrize(
    ("request_options", "expected_read", "expected_write"),
    [
        ({}, True, True),
        ({"cache_write_enabled": False}, True, False),
        ({"cache_read_enabled": False}, False, True),
        ({"cache_enabled": False}, False, False),
        ({"private": True}, False, False),
    ],
    ids=("normal", "read-only", "refresh", "bypass", "private"),
)
@pytest.mark.asyncio
async def test_cache_policy_controls_poisoning_seed_boundary(
    request_options: dict[str, bool],
    expected_read: bool,
    expected_write: bool,
) -> None:
    service, cache, _ = query_service()
    seed_prompt = "synthetic policy seed"
    policy = QueryRequest.model_validate(
        {"prompt": seed_prompt, **request_options}
    ).cache_policy

    await service.execute(seed_prompt, policy=policy)

    assert (await cache.stats()).size == int(expected_write)

    read_service, _, read_provider = query_service()
    await read_service.execute(seed_prompt)
    read_provider.prompts.clear()
    observed = await read_service.execute(seed_prompt, policy=policy)

    assert observed.cache_hit is expected_read
    assert read_provider.prompts == ([] if expected_read else [seed_prompt])


@pytest.mark.parametrize(
    ("threshold", "expected_hit"),
    [(0.79, True), (0.80, True), (0.81, False), (0.92, False)],
)
@pytest.mark.asyncio
async def test_threshold_sensitivity_is_explicit(
    threshold: float,
    expected_hit: bool,
) -> None:
    seed_prompt = "threshold seed"
    victim_prompt = "threshold victim"
    service, _, provider = query_service(
        threshold=threshold,
        vectors={
            seed_prompt: unit_vector(),
            victim_prompt: [0.8, 0.6] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 2),
        },
    )

    await service.execute(seed_prompt)
    victim = await service.execute(victim_prompt)

    assert victim.similarity_score == pytest.approx(0.8)
    assert victim.cache_hit is expected_hit
    assert provider.prompts == (
        [seed_prompt] if expected_hit else [seed_prompt, victim_prompt]
    )


@pytest.fixture(scope="module")
def typo_normalizer() -> Callable[[str], str]:
    return create_prompt_normalizer(enabled=True, max_edit_distance=2)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("reset account for Alice", "reset account for Bob"),
        ("refund limit is 30 days", "refund limit is 90 days"),
        ("enable account sharing", "do not enable account sharing"),
    ],
    ids=("entity", "numeric", "negation"),
)
def test_identity_and_typo_normalization_preserve_material_distinctions(
    typo_normalizer: Callable[[str], str],
    first: str,
    second: str,
) -> None:
    identity = create_prompt_normalizer(enabled=False, max_edit_distance=2)

    assert identity(first) != identity(second)
    assert typo_normalizer(first) != typo_normalizer(second)
