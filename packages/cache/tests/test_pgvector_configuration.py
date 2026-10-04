"""Constructor and deadline checks do not require a database."""

from typing import cast
from unittest.mock import create_autospec

import asyncpg
import pytest

from semantix_cache import CacheConfigurationError, EmbeddingSpace
from semantix_cache.stores.pgvector import PgVectorStore

SPACE = EmbeddingSpace(identity="configuration-v1", dimensions=2)


@pytest.mark.parametrize(
    "schema",
    [
        "public;DROP TABLE x",
        "a.b",
        "Uppercase",
        "pg_catalog",
        "information_schema",
        "",
        "x" * 64,
        "unicode_é",
    ],
)
def test_schema_identifiers_are_rejected_before_io(schema: str) -> None:
    pool = create_autospec(asyncpg.Pool, instance=True)
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(pool=pool, embedding_space=SPACE, schema=schema)
    pool.acquire.assert_not_called()


@pytest.mark.parametrize(
    "prefix", ["a.b", 'quote"', "Uppercase", "x" * 60, "unicode_é"]
)
def test_prefix_and_complete_identifier_length(prefix: str) -> None:
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(
            pool=create_autospec(asyncpg.Pool, instance=True),
            embedding_space=SPACE,
            table_prefix=prefix,
        )


@pytest.mark.parametrize("capacity", [0, True, 100001, 1.5])
def test_capacity_bounds(capacity: object) -> None:
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(
            pool=create_autospec(asyncpg.Pool, instance=True),
            embedding_space=SPACE,
            max_size=cast(int, capacity),
        )


@pytest.mark.parametrize("timeout", [0, True, float("nan"), float("inf"), -1])
def test_operation_timeout_is_finite_positive(timeout: float) -> None:
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(
            pool=create_autospec(asyncpg.Pool, instance=True),
            embedding_space=SPACE,
            operation_timeout_seconds=timeout,
        )


def test_pool_and_adapter_vector_limits() -> None:
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(pool=cast(asyncpg.Pool, object()), embedding_space=SPACE)
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(
            pool=create_autospec(asyncpg.Pool, instance=True),
            embedding_space=EmbeddingSpace(identity="test", dimensions=16001),
        )
    with pytest.raises(CacheConfigurationError):
        PgVectorStore(
            pool=create_autospec(asyncpg.Pool, instance=True),
            embedding_space=EmbeddingSpace(identity="x" * 1025, dimensions=2),
        )


@pytest.mark.parametrize(("minimum", "maximum"), [(0, 1), (2, 1), (1, 101), (True, 2)])
async def test_connect_pool_bounds_fail_before_network(
    minimum: int, maximum: int
) -> None:
    with pytest.raises(CacheConfigurationError):
        await PgVectorStore.connect(
            dsn="postgresql://configured/example",
            embedding_space=SPACE,
            pool_min_size=minimum,
            pool_max_size=maximum,
        )
