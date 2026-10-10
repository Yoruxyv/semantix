"""Persistence value builders and row mappers for evaluation run history.

Keep positional builders synchronized with RUN_COLUMNS and INSERT_THRESHOLD in
``app.benchmark.infrastructure.postgres_history_queries``. Read mappers use named
columns and validate schema/domain consistency, not authenticity, authorization,
arbitrary text privacy or reproducibility of historical evidence. Driver datetime
values are carried through, and stored UUIDs become public UUID-hex run identities.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from asyncpg import Record

from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
    ThresholdEvaluationMode,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    EvaluationRunHistoryRecord,
    EvaluationRunTerminalState,
    RetainedEvaluationRun,
    RetainedEvaluationRunSummary,
)
from app.benchmark.infrastructure.postgres_history_queries import RUN_COLUMN_COUNT
from app.core.exceptions import EvaluationRunHistoryStorageError


def _metrics_values(metrics: BenchmarkMetrics | None) -> tuple[object, ...]:
    """Supply twenty-one aggregate positions, all NULL when metrics are absent."""
    if metrics is None:
        return (None,) * 21

    return (
        metrics.total_queries,
        metrics.cache_hits,
        metrics.cache_misses,
        metrics.provider_calls,
        metrics.provider_calls_avoided,
        metrics.hit_rate,
        metrics.average_latency_ms,
        metrics.median_latency_ms,
        metrics.p95_latency_ms,
        metrics.average_cache_hit_latency_ms,
        metrics.average_cache_miss_latency_ms,
        metrics.estimated_latency_saved_ms,
        metrics.estimated_provider_cost_saved_usd,
        metrics.estimated_tokens_saved,
        metrics.true_positive_hits,
        metrics.true_negative_misses,
        metrics.false_positive_hits,
        metrics.false_negative_misses,
        metrics.precision,
        metrics.recall,
        metrics.f1_score,
    )


def build_run_values(
    record: EvaluationRunHistoryRecord,
    *,
    run_id: UUID,
    source_dataset_id: UUID | None,
    expires_at: datetime,
) -> tuple[object, ...]:
    """Build values matching the durable ``evaluation_runs`` column order.

    Include dataset/reproducibility snapshots, terminal fields and the fixed metrics
    block; failures contribute NULL metrics. The length guard checks shape, not
    semantic column order, which must stay synchronized with RUN_COLUMNS.

    Args:
        record: Validated terminal record whose snapshot values will be stored.
        run_id: Validated PostgreSQL UUID for the accepted run.
        source_dataset_id: Persisted-source UUID, or None for a built-in source.
        expires_at: Repository-computed retention expiry.

    Returns:
        Bind tuple for INSERT_RUN in the declared column order.

    Raises:
        EvaluationRunHistoryStorageError: Tuple length differs from RUN_COLUMN_COUNT.
    """

    context = record.context
    dataset = context.dataset
    reproducibility = record.reproducibility

    values = (
        run_id,
        context.history_namespace,
        source_dataset_id,
        context.source_dataset_expires_at,
        record.terminal_state,
        context.accepted_at,
        record.started_at,
        record.completed_at,
        expires_at,
        dataset.dataset_id,
        dataset.dataset_source,
        dataset.schema_version,
        dataset.version,
        dataset.digest,
        dataset.name,
        dataset.description,
        dataset.query_count,
        dataset.expected_hits,
        dataset.expected_misses,
        dataset.categories,
        reproducibility.application_version,
        reproducibility.embedding_provider_category,
        reproducibility.generation_provider_category,
        reproducibility.generation_configuration_fingerprint,
        reproducibility.comparison_contract_version,
        reproducibility.embedding_dimensions,
        reproducibility.embedding_space_fingerprint,
        reproducibility.normalization_mode,
        reproducibility.normalization_fingerprint,
        reproducibility.measured_threshold,
        reproducibility.evaluation_thresholds,
        reproducibility.repetitions,
        reproducibility.reset_cache_before_run,
        reproducibility.estimated_cost_per_request_usd,
        reproducibility.estimated_cost_per_1k_tokens_usd,
        reproducibility.evaluation_timeout_seconds,
        reproducibility.configuration_fingerprint,
        record.threshold_evaluation_mode,
        *_metrics_values(record.metrics),
        record.failure_code,
        record.safe_failure_detail,
    )

    if len(values) != RUN_COLUMN_COUNT:
        raise EvaluationRunHistoryStorageError(
            "Evaluation run history persistence mapping is inconsistent"
        )

    return values


def build_threshold_values(
    run_id: UUID,
    evaluations: tuple[ThresholdEvaluation, ...],
) -> list[tuple[object, ...]]:
    """Build ordered threshold rows for ``evaluation_run_thresholds``.

    Args:
        run_id: Parent run UUID.
        evaluations: Retained threshold evidence in its supplied order.

    Returns:
        Fourteen-value bind rows matching INSERT_THRESHOLD, with one-based
        sequence numbers and each measured/projected kind preserved. No rerun.
    """

    return [
        (
            run_id,
            sequence,
            evaluation.threshold,
            evaluation.result_kind,
            evaluation.hit_rate,
            evaluation.precision,
            evaluation.recall,
            evaluation.f1_score,
            evaluation.average_latency_ms,
            evaluation.provider_calls_avoided,
            evaluation.true_positive_hits,
            evaluation.true_negative_misses,
            evaluation.false_positive_hits,
            evaluation.false_negative_misses,
        )
        for sequence, evaluation in enumerate(evaluations, start=1)
    ]


def _dataset_summary_from_record(row: Record) -> BenchmarkDatasetSummary:
    return BenchmarkDatasetSummary.model_validate(
        {
            "dataset_id": row["dataset_id"],
            "dataset_source": row["dataset_source"],
            "schema_version": row["dataset_schema_version"],
            "version": row["dataset_version"],
            "digest": row["dataset_digest"],
            "name": row["dataset_name"],
            "description": row["dataset_description"],
            "query_count": row["dataset_query_count"],
            "expected_hits": row["dataset_expected_hits"],
            "expected_misses": row["dataset_expected_misses"],
            "categories": row["dataset_categories"],
        }
    )


def _reproducibility_from_record(
    row: Record,
) -> BenchmarkReproducibilityMetadata:
    return BenchmarkReproducibilityMetadata.model_validate(
        {
            "application_version": row["application_version"],
            "dataset_id": row["dataset_id"],
            "dataset_source": row["dataset_source"],
            "dataset_schema_version": row["dataset_schema_version"],
            "dataset_version": row["dataset_version"],
            "dataset_digest": row["dataset_digest"],
            "embedding_provider_category": row["embedding_provider_category"],
            "generation_provider_category": row["generation_provider_category"],
            "generation_configuration_fingerprint": row[
                "generation_configuration_fingerprint"
            ],
            "comparison_contract_version": row["comparison_contract_version"],
            "embedding_dimensions": row["embedding_dimensions"],
            "embedding_space_fingerprint": row["embedding_space_fingerprint"],
            "normalization_mode": row["normalization_mode"],
            "normalization_fingerprint": row["normalization_fingerprint"],
            "measured_threshold": row["measured_threshold"],
            "evaluation_thresholds": row["evaluation_thresholds"],
            "repetitions": row["repetitions"],
            "reset_cache_before_run": row["reset_cache_before_run"],
            "estimated_cost_per_request_usd": row["estimated_cost_per_request_usd"],
            "estimated_cost_per_1k_tokens_usd": row["estimated_cost_per_1k_tokens_usd"],
            "evaluation_timeout_seconds": row["evaluation_timeout_seconds"],
            "configuration_fingerprint": row["configuration_fingerprint"],
        }
    )


def _metrics_from_record(row: Record) -> BenchmarkMetrics | None:
    """Treat NULL total_queries as absent metrics; otherwise validate aggregates."""
    if row["total_queries"] is None:
        return None

    return BenchmarkMetrics.model_validate(
        {
            "total_queries": row["total_queries"],
            "cache_hits": row["cache_hits"],
            "cache_misses": row["cache_misses"],
            "provider_calls": row["provider_calls"],
            "provider_calls_avoided": row["provider_calls_avoided"],
            "hit_rate": row["hit_rate"],
            "average_latency_ms": row["average_latency_ms"],
            "median_latency_ms": row["median_latency_ms"],
            "p95_latency_ms": row["p95_latency_ms"],
            "average_cache_hit_latency_ms": row["average_cache_hit_latency_ms"],
            "average_cache_miss_latency_ms": row["average_cache_miss_latency_ms"],
            "estimated_latency_saved_ms": row["estimated_latency_saved_ms"],
            "estimated_provider_cost_saved_usd": row[
                "estimated_provider_cost_saved_usd"
            ],
            "estimated_tokens_saved": row["estimated_tokens_saved"],
            "true_positive_hits": row["true_positive_hits"],
            "true_negative_misses": row["true_negative_misses"],
            "false_positive_hits": row["false_positive_hits"],
            "false_negative_misses": row["false_negative_misses"],
            "precision": row["precision"],
            "recall": row["recall"],
            "f1_score": row["f1_score"],
        }
    )


def summary_from_record(row: Record) -> RetainedEvaluationRunSummary:
    """Reconstruct one aggregate retained-run summary from a database row.

    Convert the driver UUID to hex, carry datetime values and validate nested
    dataset/configuration/metrics plus retained terminal/time invariants. This
    does not verify the recorded fingerprints or sanitize arbitrary stored text.

    Args:
        row: Driver record containing named RUN_COLUMNS values, without thresholds.

    Returns:
        Retained aggregate summary describing the historical execution.

    Raises:
        EvaluationRunHistoryStorageError: KeyError, TypeError or ValueError occurs
            during mapping, including nested schema/domain validation.
    """

    try:
        context = AcceptedEvaluationRunContext(
            run_id=cast(UUID, row["run_id"]).hex,
            accepted_at=cast(datetime, row["accepted_at"]),
            dataset=_dataset_summary_from_record(row),
            history_namespace=str(row["namespace"]),
            source_dataset_expires_at=cast(
                datetime | None,
                row["source_dataset_expires_at"],
            ),
        )
        return RetainedEvaluationRunSummary(
            context=context,
            terminal_state=cast(
                EvaluationRunTerminalState,
                str(row["terminal_state"]),
            ),
            started_at=cast(datetime, row["started_at"]),
            completed_at=cast(datetime, row["completed_at"]),
            expires_at=cast(datetime, row["expires_at"]),
            reproducibility=_reproducibility_from_record(row),
            metrics=_metrics_from_record(row),
            failure_code=(
                None if row["failure_code"] is None else str(row["failure_code"])
            ),
            safe_failure_detail=(
                None
                if row["safe_failure_detail"] is None
                else str(row["safe_failure_detail"])
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationRunHistoryStorageError(
            "Persistent evaluation run history row is inconsistent"
        ) from error


def _threshold_from_record(row: Record) -> ThresholdEvaluation:
    return ThresholdEvaluation.model_validate(
        {
            "threshold": row["threshold"],
            "result_kind": row["result_kind"],
            "hit_rate": row["hit_rate"],
            "precision": row["precision"],
            "recall": row["recall"],
            "f1_score": row["f1_score"],
            "average_latency_ms": row["average_latency_ms"],
            "provider_calls_avoided": row["provider_calls_avoided"],
            "true_positive_hits": row["true_positive_hits"],
            "true_negative_misses": row["true_negative_misses"],
            "false_positive_hits": row["false_positive_hits"],
            "false_negative_misses": row["false_negative_misses"],
        }
    )


def retained_run_from_records(
    row: Record,
    threshold_rows: list[Record],
) -> RetainedEvaluationRun:
    """Reconstruct a retained-run detail and its ordered threshold evidence.

    Preserve caller-supplied row order; the repository's query orders by sequence.
    Individual threshold schemas and terminal-record/expiry invariants validate
    consistency without recomputing metrics or authenticating evidence.

    Args:
        row: Named aggregate run columns, including threshold projection mode.
        threshold_rows: Threshold records already ordered by stored sequence.

    Returns:
        Retained aggregate and expiry with threshold rows, without per-query history.

    Raises:
        EvaluationRunHistoryStorageError: Summary mapping fails or KeyError,
            TypeError or ValueError occurs while reconstructing detail.
    """

    summary = summary_from_record(row)
    try:
        record = EvaluationRunHistoryRecord(
            context=summary.context,
            terminal_state=summary.terminal_state,
            started_at=summary.started_at,
            completed_at=summary.completed_at,
            reproducibility=summary.reproducibility,
            metrics=summary.metrics,
            threshold_evaluation_mode=cast(
                ThresholdEvaluationMode,
                str(row["threshold_evaluation_mode"]),
            ),
            threshold_evaluations=tuple(
                _threshold_from_record(threshold) for threshold in threshold_rows
            ),
            failure_code=summary.failure_code,
            safe_failure_detail=summary.safe_failure_detail,
        )
        return RetainedEvaluationRun(
            record=record,
            expires_at=summary.expires_at,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationRunHistoryStorageError(
            "Persistent evaluation run history detail is inconsistent"
        ) from error
