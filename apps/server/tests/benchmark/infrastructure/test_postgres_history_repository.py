import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import asyncpg
import pytest
from asyncpg.pool import Pool

from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    EvaluationRunHistoryRecord,
    EvaluationRunTerminalState,
)
from app.benchmark.infrastructure.database import apply_migrations
from app.benchmark.infrastructure.postgres_history_repository import (
    PostgresEvaluationRunHistoryRepository,
)
from app.core.exceptions import EvaluationRunHistoryStorageError

pytestmark = pytest.mark.pgvector


@pytest.fixture
async def history_pool() -> AsyncIterator[Pool]:
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=4,
    )

    async with pool.acquire() as connection:
        await connection.execute("DROP SCHEMA IF EXISTS semantix CASCADE")

    try:
        yield pool
    finally:
        await pool.close()


def _history_record(
    *,
    run_id: str | None = None,
    namespace: str = "tenant-a",
    dataset_source: Literal["builtin", "persisted"] = "builtin",
    source_dataset_id: UUID | None = None,
    source_dataset_expires_at: datetime | None = None,
    terminal_state: EvaluationRunTerminalState = "completed",
    completed_at: datetime | None = None,
) -> EvaluationRunHistoryRecord:
    completed = completed_at or datetime.now(UTC)
    started = completed - timedelta(seconds=1)
    accepted = started - timedelta(seconds=1)

    dataset_id = (
        str(source_dataset_id)
        if dataset_source == "persisted" and source_dataset_id is not None
        else "quick"
    )
    schema_version = 1 if dataset_source == "persisted" else None
    dataset_version = "1" if dataset_source == "persisted" else "builtin-1"
    dataset_digest = "a" * 64

    dataset = BenchmarkDatasetSummary(
        dataset_id=dataset_id,
        dataset_source=dataset_source,
        schema_version=schema_version,
        version=dataset_version,
        digest=dataset_digest,
        name="History synthetic dataset",
        description="Aggregate-only run history evidence.",
        query_count=2,
        expected_hits=1,
        expected_misses=1,
        categories=["storage"],
    )

    reproducibility = BenchmarkReproducibilityMetadata(
        application_version="0.1.0",
        dataset_id=dataset_id,
        dataset_source=dataset_source,
        dataset_schema_version=schema_version,
        dataset_version=dataset_version,
        dataset_digest=dataset_digest,
        embedding_provider_category="mock",
        generation_provider_category="mock",
        generation_configuration_fingerprint="b" * 64,
        comparison_contract_version=1,
        embedding_dimensions=384,
        embedding_space_fingerprint="c" * 64,
        normalization_mode="identity",
        normalization_fingerprint="d" * 64,
        measured_threshold=0.92,
        evaluation_thresholds=[0.80, 0.92],
        repetitions=1,
        reset_cache_before_run=True,
        estimated_cost_per_request_usd=0.001,
        estimated_cost_per_1k_tokens_usd=0.002,
        evaluation_timeout_seconds=30.0,
        configuration_fingerprint="e" * 64,
    )

    context = AcceptedEvaluationRunContext(
        run_id=run_id or uuid4().hex,
        accepted_at=accepted,
        dataset=dataset,
        history_namespace=namespace,
        source_dataset_expires_at=source_dataset_expires_at,
    )

    thresholds: tuple[ThresholdEvaluation, ...]

    if terminal_state == "completed":
        metrics = BenchmarkMetrics(
            total_queries=2,
            cache_hits=1,
            cache_misses=1,
            provider_calls=1,
            provider_calls_avoided=1,
            hit_rate=0.5,
            average_latency_ms=10.0,
            median_latency_ms=9.0,
            p95_latency_ms=15.0,
            average_cache_hit_latency_ms=2.0,
            average_cache_miss_latency_ms=18.0,
            estimated_latency_saved_ms=16.0,
            estimated_provider_cost_saved_usd=0.001,
            estimated_tokens_saved=25,
            true_positive_hits=1,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=0,
            precision=1.0,
            recall=1.0,
            f1_score=1.0,
        )
        thresholds = (
            ThresholdEvaluation(
                threshold=0.80,
                result_kind="projected",
                hit_rate=0.5,
                precision=1.0,
                recall=1.0,
                f1_score=1.0,
                average_latency_ms=10.0,
                provider_calls_avoided=1,
                true_positive_hits=1,
                true_negative_misses=1,
                false_positive_hits=0,
                false_negative_misses=0,
            ),
            ThresholdEvaluation(
                threshold=0.92,
                result_kind="measured",
                hit_rate=0.5,
                precision=1.0,
                recall=1.0,
                f1_score=1.0,
                average_latency_ms=10.0,
                provider_calls_avoided=1,
                true_positive_hits=1,
                true_negative_misses=1,
                false_positive_hits=0,
                false_negative_misses=0,
            ),
        )
        failure_code = None
        failure_detail = None
    else:
        metrics = None
        thresholds = ()
        failure_code = (
            "evaluation_timeout"
            if terminal_state == "timed_out"
            else "evaluation_failed"
        )
        failure_detail = "Synthetic safe terminal failure evidence."

    return EvaluationRunHistoryRecord(
        context=context,
        terminal_state=terminal_state,
        started_at=started,
        completed_at=completed,
        reproducibility=reproducibility,
        metrics=metrics,
        threshold_evaluation_mode="frozen_candidate_projection",
        threshold_evaluations=thresholds,
        failure_code=failure_code,
        safe_failure_detail=failure_detail,
    )


async def _insert_source_dataset(
    pool: Pool,
    *,
    dataset_id: UUID,
    namespace: str,
    expires_at: datetime,
) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO semantix.evaluation_datasets (
                dataset_id,
                namespace,
                name,
                description,
                source_type,
                schema_version,
                digest,
                case_count,
                decoded_bytes,
                created_at,
                expires_at
            )
            VALUES (
                $1,
                $2,
                'History source dataset',
                'Synthetic persisted dataset for history FK evidence.',
                'imported',
                1,
                $3,
                2,
                64,
                $4,
                $5
            )
            """,
            dataset_id,
            namespace,
            "f" * 64,
            expires_at - timedelta(days=1),
            expires_at,
        )


@pytest.mark.asyncio
async def test_repository_persists_completed_aggregate_history(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    record = _history_record()

    await repository.persist_terminal_run(record)
    await repository.readiness()

    async with history_pool.acquire() as connection:
        run = await connection.fetchrow(
            """
            SELECT
                run_id,
                namespace,
                terminal_state,
                expires_at,
                dataset_source,
                total_queries,
                cache_hits,
                cache_misses,
                provider_calls,
                provider_calls_avoided,
                generation_configuration_fingerprint,
                comparison_contract_version,
                failure_code,
                safe_failure_detail
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )
        thresholds = await connection.fetch(
            """
            SELECT
                sequence,
                threshold,
                result_kind,
                provider_calls_avoided
            FROM semantix.evaluation_run_thresholds
            WHERE run_id = $1
            ORDER BY sequence
            """,
            UUID(record.context.run_id),
        )

    assert run is not None
    assert run["namespace"] == "tenant-a"
    assert run["terminal_state"] == "completed"
    assert run["dataset_source"] == "builtin"
    assert run["total_queries"] == 2
    assert run["cache_hits"] == 1
    assert run["cache_misses"] == 1
    assert run["provider_calls"] == 1
    assert run["provider_calls_avoided"] == 1
    assert run["generation_configuration_fingerprint"] == "b" * 64
    assert run["comparison_contract_version"] == 1
    assert run["failure_code"] is None
    assert run["safe_failure_detail"] is None
    assert run["expires_at"] == record.completed_at + timedelta(days=30)

    assert [
        (
            row["sequence"],
            row["threshold"],
            row["result_kind"],
            row["provider_calls_avoided"],
        )
        for row in thresholds
    ] == [
        (1, 0.80, "projected", 1),
        (2, 0.92, "measured", 1),
    ]


@pytest.mark.asyncio
async def test_repository_persists_failed_terminal_history_without_metrics(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    record = _history_record(terminal_state="failed")

    await repository.persist_terminal_run(record)

    async with history_pool.acquire() as connection:
        run = await connection.fetchrow(
            """
            SELECT
                terminal_state,
                total_queries,
                hit_rate,
                failure_code,
                safe_failure_detail
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )
        threshold_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_run_thresholds
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )

    assert run is not None
    assert run["terminal_state"] == "failed"
    assert run["total_queries"] is None
    assert run["hit_rate"] is None
    assert run["failure_code"] == "evaluation_failed"
    assert run["safe_failure_detail"] == ("Synthetic safe terminal failure evidence.")
    assert threshold_count == 0


@pytest.mark.asyncio
async def test_persisted_source_caps_retention_and_dataset_delete_cascades(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)

    completed_at = datetime.now(UTC)
    source_dataset_id = uuid4()
    source_expires_at = completed_at + timedelta(days=2)

    await _insert_source_dataset(
        history_pool,
        dataset_id=source_dataset_id,
        namespace="tenant-persisted",
        expires_at=source_expires_at,
    )

    repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    record = _history_record(
        namespace="tenant-persisted",
        dataset_source="persisted",
        source_dataset_id=source_dataset_id,
        source_dataset_expires_at=source_expires_at,
        completed_at=completed_at,
    )

    await repository.persist_terminal_run(record)

    async with history_pool.acquire() as connection:
        retained = await connection.fetchrow(
            """
            SELECT source_dataset_id, source_dataset_expires_at, expires_at
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )

        assert retained is not None
        assert retained["source_dataset_id"] == source_dataset_id
        assert retained["source_dataset_expires_at"] == source_expires_at
        assert retained["expires_at"] == source_expires_at

        await connection.execute(
            """
            DELETE FROM semantix.evaluation_datasets
            WHERE dataset_id = $1
            """,
            source_dataset_id,
        )

        run_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )
        threshold_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_run_thresholds
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )

    assert run_count == 0
    assert threshold_count == 0


@pytest.mark.asyncio
async def test_repository_prunes_oldest_active_history_deterministically(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)

    namespace = "tenant-rolling"
    base_completed = datetime.now(UTC)
    seed_repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    records = [
        _history_record(
            run_id=f"{value:032x}",
            namespace=namespace,
            completed_at=(
                base_completed
                if value in {1, 2}
                else base_completed + timedelta(seconds=value - 1)
            ),
        )
        for value in range(1, 5)
    ]

    for record in records:
        await seed_repository.persist_terminal_run(record)

    rolling_repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=2,
        cleanup_batch_size=10,
    )
    newest = _history_record(
        run_id=f"{5:032x}",
        namespace=namespace,
        completed_at=base_completed + timedelta(seconds=4),
    )
    await rolling_repository.persist_terminal_run(newest)

    async with history_pool.acquire() as connection:
        retained = await connection.fetch(
            """
            SELECT run_id
            FROM semantix.evaluation_runs
            WHERE namespace = $1
            ORDER BY completed_at ASC, run_id ASC
            """,
            namespace,
        )
        pruned_thresholds = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_run_thresholds
            WHERE run_id = ANY($1::uuid[])
            """,
            [UUID(record.context.run_id) for record in records[:3]],
        )

    assert [row["run_id"] for row in retained] == [
        UUID(records[3].context.run_id),
        UUID(newest.context.run_id),
    ]
    assert pruned_thresholds == 0


@pytest.mark.asyncio
async def test_repository_keeps_expiry_cleanup_bounded_and_namespace_scoped(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)

    seed_repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    first = _history_record(
        run_id=f"{1:032x}",
        namespace="tenant-cleanup",
    )
    second = _history_record(
        run_id=f"{2:032x}",
        namespace="tenant-cleanup",
    )
    foreign = _history_record(
        run_id=f"{3:032x}",
        namespace="tenant-other",
    )

    await seed_repository.persist_terminal_run(first)
    await seed_repository.persist_terminal_run(second)
    await seed_repository.persist_terminal_run(foreign)

    expired_completed = datetime.now(UTC) - timedelta(days=3)
    expired_started = expired_completed - timedelta(seconds=1)
    expired_accepted = expired_started - timedelta(seconds=1)
    expired_at = expired_completed + timedelta(days=1)

    async with history_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.evaluation_runs
            SET accepted_at = $1,
                started_at = $2,
                completed_at = $3,
                expires_at = $4
            WHERE run_id = ANY($5::uuid[])
            """,
            expired_accepted,
            expired_started,
            expired_completed,
            expired_at,
            [
                UUID(first.context.run_id),
                UUID(second.context.run_id),
                UUID(foreign.context.run_id),
            ],
        )

    cleanup_repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=1,
    )
    fresh = _history_record(namespace="tenant-cleanup")
    await cleanup_repository.persist_terminal_run(fresh)

    async with history_pool.acquire() as connection:
        target_expired = await connection.fetch(
            """
            SELECT run_id
            FROM semantix.evaluation_runs
            WHERE namespace = 'tenant-cleanup'
              AND expires_at <= CURRENT_TIMESTAMP
            ORDER BY expires_at ASC, run_id ASC
            """
        )
        foreign_expired_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_runs
            WHERE namespace = 'tenant-other'
              AND expires_at <= CURRENT_TIMESTAMP
            """
        )
        fresh_exists = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(fresh.context.run_id),
        )

    assert [row["run_id"] for row in target_expired] == [UUID(second.context.run_id)]
    assert foreign_expired_count == 1
    assert fresh_exists == 1


@pytest.mark.asyncio
async def test_repository_rejects_nonpositive_limits_and_expired_source_window(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)

    with pytest.raises(
        ValueError,
        match="repository limits must be positive",
    ):
        PostgresEvaluationRunHistoryRepository(
            history_pool,
            retention_days=0,
            max_per_namespace=1,
            cleanup_batch_size=1,
        )

    completed_at = datetime.now(UTC)
    source_dataset_id = uuid4()
    source_expires_at = completed_at

    repository = PostgresEvaluationRunHistoryRepository(
        history_pool,
        retention_days=30,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )
    record = _history_record(
        namespace="tenant-expired-source",
        dataset_source="persisted",
        source_dataset_id=source_dataset_id,
        source_dataset_expires_at=source_expires_at,
        completed_at=completed_at,
    )

    with pytest.raises(
        EvaluationRunHistoryStorageError,
        match="retention window has already expired",
    ):
        await repository.persist_terminal_run(record)
