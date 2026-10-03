from datetime import UTC, datetime

import pytest

from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    EvaluationRunHistoryRecord,
)


def dataset() -> BenchmarkDatasetSummary:
    return BenchmarkDatasetSummary(
        dataset_id="quick",
        dataset_source="builtin",
        schema_version=None,
        version="1.0.0",
        digest="d" * 64,
        name="Quick",
        description="Synthetic history contract dataset.",
        query_count=1,
        expected_hits=0,
        expected_misses=1,
        categories=["seed"],
    )


def reproducibility() -> BenchmarkReproducibilityMetadata:
    return BenchmarkReproducibilityMetadata(
        application_version="1.0.0",
        dataset_id="quick",
        dataset_source="builtin",
        dataset_schema_version=None,
        dataset_version="1.0.0",
        dataset_digest="d" * 64,
        embedding_provider_category="mock",
        generation_provider_category="mock",
        generation_configuration_fingerprint="3" * 64,
        comparison_contract_version=1,
        embedding_dimensions=4,
        embedding_space_fingerprint="1" * 64,
        normalization_mode="identity",
        normalization_fingerprint="2" * 64,
        measured_threshold=0.9,
        evaluation_thresholds=[0.8, 0.9],
        repetitions=1,
        reset_cache_before_run=True,
        estimated_cost_per_request_usd=0,
        estimated_cost_per_1k_tokens_usd=0,
        evaluation_timeout_seconds=30,
        configuration_fingerprint="4" * 64,
    )


def metrics() -> BenchmarkMetrics:
    return BenchmarkMetrics(
        total_queries=1,
        cache_hits=0,
        cache_misses=1,
        provider_calls=1,
        provider_calls_avoided=0,
        hit_rate=0,
        average_latency_ms=10,
        median_latency_ms=10,
        p95_latency_ms=10,
        average_cache_hit_latency_ms=None,
        average_cache_miss_latency_ms=10,
        estimated_latency_saved_ms=0,
        estimated_provider_cost_saved_usd=0,
        estimated_tokens_saved=0,
        true_positive_hits=0,
        true_negative_misses=1,
        false_positive_hits=0,
        false_negative_misses=0,
        precision=0,
        recall=0,
        f1_score=0,
    )


def thresholds() -> tuple[ThresholdEvaluation, ...]:
    return (
        ThresholdEvaluation(
            threshold=0.8,
            result_kind="projected",
            hit_rate=0,
            precision=0,
            recall=0,
            f1_score=0,
            average_latency_ms=10,
            provider_calls_avoided=0,
            true_positive_hits=0,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=0,
        ),
        ThresholdEvaluation(
            threshold=0.9,
            result_kind="measured",
            hit_rate=0,
            precision=0,
            recall=0,
            f1_score=0,
            average_latency_ms=10,
            provider_calls_avoided=0,
            true_positive_hits=0,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=0,
        ),
    )


def accepted() -> AcceptedEvaluationRunContext:
    now = datetime.now(UTC)
    return AcceptedEvaluationRunContext(
        run_id="a" * 32,
        accepted_at=now,
        dataset=dataset(),
        history_namespace="tenant-a",
        source_dataset_expires_at=None,
    )


def test_completed_history_requires_metrics_and_projection_evidence() -> None:
    context = accepted()

    record = EvaluationRunHistoryRecord(
        context=context,
        terminal_state="completed",
        started_at=context.accepted_at,
        completed_at=context.accepted_at,
        reproducibility=reproducibility(),
        metrics=metrics(),
        threshold_evaluation_mode="frozen_candidate_projection",
        threshold_evaluations=thresholds(),
    )

    assert record.failure_code is None

    with pytest.raises(ValueError, match="Completed evaluation history"):
        EvaluationRunHistoryRecord(
            context=context,
            terminal_state="completed",
            started_at=context.accepted_at,
            completed_at=context.accepted_at,
            reproducibility=reproducibility(),
            metrics=None,
            threshold_evaluation_mode="frozen_candidate_projection",
            threshold_evaluations=(),
        )


def test_failed_history_requires_safe_failure_code_and_no_completed_metrics() -> None:
    context = accepted()

    failed = EvaluationRunHistoryRecord(
        context=context,
        terminal_state="failed",
        started_at=context.accepted_at,
        completed_at=context.accepted_at,
        reproducibility=reproducibility(),
        metrics=None,
        threshold_evaluation_mode="frozen_candidate_projection",
        threshold_evaluations=(),
        failure_code="upstream_error",
        safe_failure_detail="The AI service could not process the request.",
    )

    assert failed.failure_code == "upstream_error"

    with pytest.raises(ValueError, match="Failed evaluation history"):
        EvaluationRunHistoryRecord(
            context=context,
            terminal_state="timed_out",
            started_at=context.accepted_at,
            completed_at=context.accepted_at,
            reproducibility=reproducibility(),
            metrics=metrics(),
            threshold_evaluation_mode="frozen_candidate_projection",
            threshold_evaluations=thresholds(),
            failure_code="evaluation_timeout",
        )
