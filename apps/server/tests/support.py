from app.cache.infrastructure.backends.memory import InMemoryCacheBackend

TEST_EMBEDDING_DIMENSIONS = 4


def unit_vector(index: int = 0) -> list[float]:
    result = [0.0] * TEST_EMBEDDING_DIMENSIONS
    result[index] = 1.0
    return result


def memory_backend(
    *,
    ttl_seconds: float | None = 60,
    max_size: int = 10,
) -> InMemoryCacheBackend:
    return InMemoryCacheBackend(
        max_size,
        ttl_seconds,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
    )
