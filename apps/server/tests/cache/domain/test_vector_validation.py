import numpy as np
import pytest

from app.cache.domain.vector_validation import (
    parse_vector_literal,
    validated_cache_vector,
    vector_literal,
)
from app.core.exceptions import CacheStorageError


def test_cache_vector_literal_round_trip() -> None:
    vector = validated_cache_vector(
        [1.0, 0.5, -0.25, 0.0],
        dimensions=4,
        description="Test",
    )

    assert parse_vector_literal(
        vector_literal(vector),
        dimensions=4,
    ) == pytest.approx(vector.tolist())


@pytest.mark.parametrize(
    "vector",
    [
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 2.0],
        [1.0, np.inf, 0.0, 0.0],
    ],
)
def test_cache_vector_validation_rejects_invalid_values(
    vector: list[float],
) -> None:
    with pytest.raises(CacheStorageError):
        validated_cache_vector(
            vector,
            dimensions=4,
            description="Test",
        )
