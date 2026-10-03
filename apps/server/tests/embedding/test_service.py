from collections.abc import Sequence

import pytest

from app.core.exceptions import EmbeddingError
from app.embedding.service import EmbeddingService
from tests.support import TEST_EMBEDDING_DIMENSIONS


class Provider:
    def __init__(self, value: Sequence[float]) -> None:
        self.value = value

    async def create_embedding(self, text: str) -> Sequence[float]:
        return self.value


@pytest.mark.asyncio
async def test_normalizes_embedding() -> None:
    result = await EmbeddingService(
        Provider([2.0] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 1)),
        dimensions=TEST_EMBEDDING_DIMENSIONS,
    ).embed("hello")
    assert result[0] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rejects_wrong_dimensions() -> None:
    with pytest.raises(EmbeddingError):
        await EmbeddingService(
            Provider([1.0]),
            dimensions=TEST_EMBEDDING_DIMENSIONS,
        ).embed("hello")


@pytest.mark.asyncio
async def test_rejects_zero_vector() -> None:
    with pytest.raises(EmbeddingError):
        await EmbeddingService(
            Provider([0.0] * TEST_EMBEDDING_DIMENSIONS),
            dimensions=TEST_EMBEDDING_DIMENSIONS,
        ).embed("hello")
