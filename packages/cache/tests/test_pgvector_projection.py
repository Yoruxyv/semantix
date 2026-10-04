"""Real production-query equivalence, including native-vector winner payloads."""

from datetime import UTC, datetime

import numpy as np
import pytest

from semantix_cache import CacheStoreError, EmbeddingSpace
from semantix_cache._semantics import normalized_vector
from semantix_cache.stores.pgvector import PgVectorStore

from . import test_pgvector
from .test_memory import entry

pg_store = test_pgvector.pg_store  # Reuse the disposable-schema fixture.

pytestmark = pytest.mark.pgvector


def _original_query(layout: dict[str, str]) -> str:
    # The complete pre-optimization query is an equivalence oracle, not a store API.
    return f"""
        WITH eligible AS MATERIALIZED (
            SELECT * FROM {layout["entries"]}
            WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3
              AND (expires_at IS NULL OR expires_at>clock_timestamp())
        )
        SELECT cache_key, namespace, prompt, response, embedding::text AS embedding,
               created_at, expires_at, 1-(embedding {layout["cosine"]} $4::{layout["vector"]}) AS score
        FROM eligible ORDER BY embedding {layout["cosine"]} $4::{layout["vector"]}, created_at, cache_key LIMIT 1
    """  # noqa: S608 -- store-owned quoted layout; workload values remain parameters


@pytest.mark.parametrize("dimensions", [2, 384, 1536, 3072])
async def test_winner_payload_scores_and_ties_equal_original_query(
    pg_store: PgVectorStore, dimensions: int
) -> None:
    rng = np.random.default_rng(2301)
    vectors = rng.normal(size=(32, dimensions))
    vectors[1] = vectors[0]
    async with PgVectorStore(
        pool=pg_store._pool,
        embedding_space=EmbeddingSpace(identity="projection", dimensions=dimensions),
        schema=pg_store._config.schema,
        table_prefix="projection_",
    ) as store:
        await store.initialize_schema(migration_pool=pg_store._pool)
        for index, vector in enumerate(vectors):
            await store.put(entry(str(index), vector=tuple(float(v) for v in vector)))
        # Equal scores and equal revisions require the key tie breaker. An expired
        # earlier revision must remain ineligible, even when its score is maximal.
        expired = entry("expired", vector=tuple(float(v) for v in vectors[0]))
        await store.put(expired)
        async with pg_store._pool.acquire() as connection:
            layout = await store._layout(connection, require_schema=True)
            await connection.execute(
                f"UPDATE {layout['entries']} SET created_at=$1 WHERE cache_key=ANY($2::text[])",  # noqa: S608 -- validated quoted table; bound values
                datetime(2020, 1, 1, tzinfo=UTC),
                [entry(str(i)).cache_key for i in [0, 1]],
            )
            await connection.execute(
                f"UPDATE {layout['entries']} SET created_at=$1, expires_at=$2 WHERE cache_key=$3",  # noqa: S608 -- validated quoted table; bound values
                datetime(2000, 1, 1, tzinfo=UTC),
                datetime(2001, 1, 1, tzinfo=UTC),
                expired.cache_key,
            )
        for raw in [*vectors[:3], *rng.normal(size=(6, dimensions))]:
            values = tuple(float(v) for v in raw)
            normalized = normalized_vector(values, dimensions=dimensions)
            literal = "[" + ",".join(str(float(v)) for v in normalized) + "]"
            async with pg_store._pool.acquire() as connection:
                expected = await connection.fetchrow(
                    _original_query(layout),
                    "projection",
                    dimensions,
                    "default",
                    literal,
                )
            actual = await store.find_nearest(values, namespace="default")
            assert expected is not None
            assert actual is not None
            assert actual.entry.cache_key == expected["cache_key"]
            assert actual.entry.namespace == expected["namespace"]
            assert actual.entry.prompt == expected["prompt"]
            assert actual.entry.response == expected["response"]
            assert actual.entry.embedding == tuple(
                float(v) for v in expected["embedding"][1:-1].split(",")
            )
            assert actual.entry.created_at == expected["created_at"]
            assert actual.expires_at == expected["expires_at"]
            assert actual.similarity_score == max(-1.0, min(1.0, expected["score"]))
        tie = await store.find_nearest(
            tuple(float(v) for v in vectors[0]), namespace="default"
        )
        assert tie is not None
        assert tie.entry.cache_key == min(entry("0").cache_key, entry("1").cache_key)
        assert await store.record_hit(
            tie.entry.cache_key,
            namespace="default",
            expected_created_at=tie.entry.created_at,
        )
        await store.put(
            entry(tie.entry.prompt, vector=tuple(float(v) for v in vectors[2]))
        )
        assert not await store.record_hit(
            tie.entry.cache_key,
            namespace="default",
            expected_created_at=tie.entry.created_at,
        )


@pytest.mark.parametrize("tamper", ["checksum", "ownership"])
async def test_optimized_search_rechecks_live_schema_on_every_call(
    pg_store: PgVectorStore, tamper: str
) -> None:
    await pg_store.put(entry("warm"))
    assert await pg_store.find_nearest((1, 0), namespace="default") is not None
    async with pg_store._pool.acquire() as connection:
        layout = await pg_store._layout(connection, require_schema=True)
        if tamper == "checksum":
            await connection.execute(
                f"UPDATE {layout['ledger']} SET checksum=$1",  # noqa: S608 -- validated quoted table; bound value
                "tampered",
            )
        else:
            await connection.execute(
                f"COMMENT ON TABLE {layout['entries']} IS 'application-owned'"
            )
    with pytest.raises(CacheStoreError):
        await pg_store.find_nearest((1, 0), namespace="default")
