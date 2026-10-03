import logging
import math

import pytest

from app.cache.application.service import SemanticCache
from app.embedding.service import EmbeddingService
from app.providers.adapters.mock import (
    MOCK_GENERATION_PREFIX,
    MockEmbeddingProvider,
    MockGenerationProvider,
    MockProvider,
)
from app.query.application.service import QueryService
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend


@pytest.mark.asyncio
async def test_embedding_is_deterministic_normalized_and_dimensioned() -> None:
    provider = MockEmbeddingProvider(TEST_EMBEDDING_DIMENSIONS)

    first = list(await provider.create_embedding("semantic caching"))
    second = list(await provider.create_embedding("semantic caching"))

    assert first == second
    assert len(first) == TEST_EMBEDDING_DIMENSIONS
    assert math.sqrt(sum(component * component for component in first)) == (
        pytest.approx(1.0)
    )


@pytest.mark.asyncio
async def test_generation_is_deterministic_and_identifies_provider() -> None:
    provider = MockGenerationProvider()

    first = await provider.generate("Explain caching")
    second = await provider.generate("Explain caching")

    assert first == second
    assert first == f"{MOCK_GENERATION_PREFIX} Explain caching"


@pytest.mark.asyncio
async def test_delayed_mock_generation_records_both_edges(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider = MockProvider(TEST_EMBEDDING_DIMENSIONS, delay_seconds=0.001)

    assert await provider.generate("one") == f"{MOCK_GENERATION_PREFIX} one"
    assert [record.message for record in caplog.records] == [
        "Mock generation started",
        "Mock generation finished",
    ]


@pytest.mark.asyncio
async def test_mock_providers_support_query_cache_without_network() -> None:
    dimensions = TEST_EMBEDDING_DIMENSIONS
    service = QueryService(
        SemanticCache(
            EmbeddingService(
                MockEmbeddingProvider(dimensions),
                dimensions=dimensions,
            ),
            memory_backend(),
            0.92,
        ),
        MockGenerationProvider(),
    )

    miss = await service.execute("semantic caching")
    hit = await service.execute("semantic caching")

    assert miss.cache_hit is False
    assert miss.provider_called is True
    assert miss.response.startswith(MOCK_GENERATION_PREFIX)
    assert hit.cache_hit is True
    assert hit.provider_called is False
    assert hit.response == miss.response
