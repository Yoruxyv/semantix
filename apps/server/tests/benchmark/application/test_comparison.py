from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.benchmark.api.comparison_schemas import EvaluationRunComparisonRequest
from app.benchmark.api.history_schemas import EvaluationRunHistoryDetail
from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
)
from app.benchmark.application.comparison import compare_evaluation_runs
from app.benchmark.application.comparison_compatibility import comparison_blockers
from app.benchmark.application.history_catalog import EvaluationRunHistoryCatalog
from app.benchmark.domain.models import (
    EvaluationRunHistoryRecord,
    RetainedEvaluationRun,
)
from app.core.exceptions import EvaluationRunHistoryNotFoundError
from tests.benchmark.history_support import (
    InMemoryEvaluationRunHistoryRepository,
    make_history_record,
)


def detail_from_record(
    record: EvaluationRunHistoryRecord,
) -> EvaluationRunHistoryDetail:
    source_expiry = record.context.source_dataset_expires_at
    expires_at = record.completed_at + timedelta(days=30)
    if source_expiry is not None:
        expires_at = min(expires_at, source_expiry)

    retained = RetainedEvaluationRun(record=record, expires_at=expires_at)
    summary = retained.summary
    namespace = summary.context.history_namespace
    assert namespace is not None

    return EvaluationRunHistoryDetail(
        run_id=summary.context.run_id,
        namespace=namespace,
        terminal_state=summary.terminal_state,
        accepted_at=summary.context.accepted_at,
        started_at=summary.started_at,
        completed_at=summary.completed_at,
        expires_at=summary.expires_at,
        source_dataset_expires_at=summary.context.source_dataset_expires_at,
        dataset=summary.context.dataset,
        reproducibility=summary.reproducibility,
        metrics=summary.metrics,
        failure_code=summary.failure_code,
        safe_failure_detail=summary.safe_failure_detail,
        threshold_evaluation_mode=record.threshold_evaluation_mode,
        threshold_evaluations=list(record.threshold_evaluations),
    )


def rebuilt_detail(
    detail: EvaluationRunHistoryDetail,
    *,
    top: dict[str, object] | None = None,
    dataset: dict[str, object] | None = None,
    reproducibility: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    thresholds: list[dict[str, object]] | None = None,
) -> EvaluationRunHistoryDetail:
    payload = detail.model_dump()
    if top:
        payload.update(top)
    if dataset:
        payload["dataset"].update(dataset)
    if reproducibility:
        payload["reproducibility"].update(reproducibility)
    if metrics:
        assert payload["metrics"] is not None
        payload["metrics"].update(metrics)
    if thresholds is not None:
        payload["threshold_evaluations"] = thresholds
    return EvaluationRunHistoryDetail.model_validate(payload)


def persisted_detail(
    *,
    run_id: str,
    dataset_id: str,
    version: str,
    namespace: str = "tenant-history",
) -> EvaluationRunHistoryDetail:
    record = make_history_record(run_id=run_id, namespace=namespace)
    source_expiry = record.completed_at + timedelta(days=10)
    dataset = BenchmarkDatasetSummary(
        dataset_id=dataset_id,
        dataset_source="persisted",
        schema_version=1,
        version=version,
        digest=record.context.dataset.digest,
        name=record.context.dataset.name,
        description=record.context.dataset.description,
        query_count=record.context.dataset.query_count,
        expected_hits=record.context.dataset.expected_hits,
        expected_misses=record.context.dataset.expected_misses,
        categories=record.context.dataset.categories,
    )
    reproducibility = BenchmarkReproducibilityMetadata(
        **{
            **record.reproducibility.model_dump(),
            "dataset_id": dataset.dataset_id,
            "dataset_source": dataset.dataset_source,
            "dataset_schema_version": dataset.schema_version,
            "dataset_version": dataset.version,
            "dataset_digest": dataset.digest,
        }
    )
    return detail_from_record(
        replace(
            record,
            context=replace(
                record.context,
                dataset=dataset,
                source_dataset_expires_at=source_expiry,
            ),
            reproducibility=reproducibility,
        )
    )


def test_threshold_change_is_compatible_and_deltas_are_candidate_minus_baseline() -> (
    None
):
    baseline = detail_from_record(make_history_record(run_id=f"{1:032x}"))
    candidate = detail_from_record(make_history_record(run_id=f"{2:032x}"))

    candidate_metrics = BenchmarkMetrics(
        total_queries=2,
        cache_hits=0,
        cache_misses=2,
        provider_calls=2,
        provider_calls_avoided=0,
        hit_rate=0,
        average_latency_ms=12,
        median_latency_ms=11,
        p95_latency_ms=18,
        average_cache_hit_latency_ms=None,
        average_cache_miss_latency_ms=12,
        estimated_latency_saved_ms=0,
        estimated_provider_cost_saved_usd=0,
        estimated_tokens_saved=0,
        true_positive_hits=0,
        true_negative_misses=1,
        false_positive_hits=0,
        false_negative_misses=1,
        precision=0,
        recall=0,
        f1_score=0,
    )
    threshold_values = [
        ThresholdEvaluation(
            threshold=0.80,
            result_kind="measured",
            hit_rate=0,
            precision=0,
            recall=0,
            f1_score=0,
            average_latency_ms=12,
            provider_calls_avoided=0,
            true_positive_hits=0,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=1,
        ),
        ThresholdEvaluation(
            threshold=0.92,
            result_kind="projected",
            hit_rate=0,
            precision=0,
            recall=0,
            f1_score=0,
            average_latency_ms=12,
            provider_calls_avoided=0,
            true_positive_hits=0,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=1,
        ),
    ]
    candidate = rebuilt_detail(
        candidate,
        reproducibility={
            "measured_threshold": 0.80,
            "configuration_fingerprint": "9" * 64,
        },
        metrics=candidate_metrics.model_dump(),
        thresholds=[value.model_dump() for value in threshold_values],
    )

    comparison = compare_evaluation_runs(baseline, candidate)

    assert comparison.compatibility.status == "compatible"
    assert comparison.compatibility.can_compare is True
    assert comparison.compatibility.incompatibilities == []
    assert comparison.compatibility.warnings == []
    assert comparison.compatibility.case_evidence == "not_retained"
    assert comparison.compatibility.opaque_configuration_fingerprint_matches is False

    deltas = comparison.metric_deltas
    assert deltas is not None
    assert deltas.measured_threshold == pytest.approx(-0.12)
    assert deltas.cache_hits == -1
    assert deltas.cache_misses == 1
    assert deltas.provider_calls == 1
    assert deltas.provider_calls_avoided == -1
    assert deltas.hit_rate == pytest.approx(-0.5)
    assert deltas.average_latency_ms == pytest.approx(2)
    assert deltas.estimated_tokens_saved == -25
    assert deltas.true_positive_hits == -1
    assert deltas.false_negative_misses == 1
    assert deltas.precision == pytest.approx(-1)
    assert deltas.recall == pytest.approx(-1)
    assert deltas.f1_score == pytest.approx(-1)
    assert deltas.average_cache_hit_latency_ms is None
    assert len(comparison.threshold_deltas) == 2
    assert comparison.threshold_deltas[0].threshold == pytest.approx(
        0.80, rel=0.0, abs=1e-12
    )
    assert comparison.threshold_deltas[0].baseline_result_kind == "projected"
    assert comparison.threshold_deltas[0].candidate_result_kind == "measured"


def test_required_dataset_scope_and_terminal_mismatches_block_deltas() -> None:
    baseline = detail_from_record(make_history_record(run_id=f"{1:032x}"))
    failed_candidate = detail_from_record(
        make_history_record(
            run_id=f"{2:032x}",
            namespace="tenant-other",
            terminal_state="failed",
        )
    )
    failed_candidate = rebuilt_detail(
        failed_candidate,
        dataset={"digest": "f" * 64},
        reproducibility={"dataset_digest": "f" * 64},
    )

    comparison = compare_evaluation_runs(baseline, failed_candidate)
    codes = {issue.code for issue in comparison.compatibility.incompatibilities}

    assert comparison.compatibility.status == "incompatible"
    assert comparison.compatibility.can_compare is False
    assert {
        "namespace_mismatch",
        "candidate_not_completed",
        "dataset_digest_mismatch",
    }.issubset(codes)
    assert comparison.metric_deltas is None
    assert comparison.threshold_deltas == []


def test_embedding_normalization_and_run_policy_mismatches_are_hard_gates() -> None:
    baseline = detail_from_record(make_history_record(run_id=f"{1:032x}"))
    candidate = detail_from_record(make_history_record(run_id=f"{2:032x}"))

    # model_copy deliberately simulates future retained contracts that the current
    # Literal[1]/single projection-mode API cannot yet produce.
    candidate_metadata = candidate.reproducibility.model_copy(
        update={
            "embedding_dimensions": baseline.reproducibility.embedding_dimensions + 1,
            "embedding_space_fingerprint": "1" * 64,
            "normalization_mode": "typo_correction",
            "normalization_fingerprint": "2" * 64,
            "repetitions": 2,
            "reset_cache_before_run": False,
            "comparison_contract_version": 2,
        }
    )
    candidate = candidate.model_copy(
        update={
            "reproducibility": candidate_metadata,
            "threshold_evaluation_mode": "future_projection_contract",
        }
    )

    codes = {issue.code for issue in comparison_blockers(baseline, candidate)}

    assert {
        "embedding_dimensions_mismatch",
        "embedding_space_mismatch",
        "normalization_mode_mismatch",
        "normalization_fingerprint_mismatch",
        "repetitions_mismatch",
        "reset_policy_mismatch",
        "comparison_contract_version_mismatch",
        "threshold_evaluation_mode_mismatch",
    } == codes


def test_dataset_schema_mismatch_is_a_hard_gate() -> None:
    baseline = detail_from_record(make_history_record(run_id=f"{1:032x}"))
    candidate = persisted_detail(
        run_id=f"{2:032x}",
        dataset_id=str(uuid4()),
        version="1",
    )

    comparison = compare_evaluation_runs(baseline, candidate)

    assert {issue.code for issue in comparison.compatibility.incompatibilities} == {
        "dataset_schema_mismatch"
    }
    assert comparison.metric_deltas is None


def test_generation_runtime_and_projection_changes_are_explicit_warnings() -> None:
    baseline = detail_from_record(make_history_record(run_id=f"{1:032x}"))
    candidate = detail_from_record(make_history_record(run_id=f"{2:032x}"))
    projected = candidate.threshold_evaluations[0].model_copy(
        update={"threshold": 0.75}
    )
    candidate = rebuilt_detail(
        candidate,
        reproducibility={
            "generation_provider_category": "openai",
            "generation_configuration_fingerprint": "1" * 64,
            "application_version": "2.0.0",
            "estimated_cost_per_request_usd": 0.01,
            "estimated_cost_per_1k_tokens_usd": 0.02,
            "evaluation_timeout_seconds": 60,
            "evaluation_thresholds": [0.75, 0.80, 0.92],
            "configuration_fingerprint": "9" * 64,
        },
        thresholds=[
            projected.model_dump(),
            *[value.model_dump() for value in candidate.threshold_evaluations],
        ],
    )

    comparison = compare_evaluation_runs(baseline, candidate)
    warning_codes = {warning.code for warning in comparison.compatibility.warnings}

    assert comparison.compatibility.status == "warning"
    assert comparison.compatibility.can_compare is True
    assert comparison.compatibility.incompatibilities == []
    assert warning_codes == {
        "generation_provider_changed",
        "generation_configuration_changed",
        "application_version_changed",
        "cost_assumptions_changed",
        "evaluation_timeout_changed",
        "projection_list_changed",
    }
    assert comparison.metric_deltas is not None
    assert [item.threshold for item in comparison.threshold_deltas] == [0.80, 0.92]
    assert comparison.compatibility.opaque_configuration_fingerprint_matches is False


def test_same_digest_with_different_persisted_identity_warns_but_remains_comparable() -> (
    None
):
    baseline = persisted_detail(
        run_id=f"{1:032x}",
        dataset_id=str(uuid4()),
        version="1",
    )
    candidate = persisted_detail(
        run_id=f"{2:032x}",
        dataset_id=str(uuid4()),
        version="2",
    )

    comparison = compare_evaluation_runs(baseline, candidate)

    assert comparison.compatibility.status == "warning"
    assert comparison.compatibility.can_compare is True
    assert [warning.code for warning in comparison.compatibility.warnings] == [
        "persisted_dataset_identity_changed"
    ]
    assert comparison.metric_deltas is not None


@pytest.mark.asyncio
async def test_catalog_comparison_preserves_non_disclosing_namespace_scope() -> None:
    repository = InMemoryEvaluationRunHistoryRepository()
    baseline = make_history_record(
        run_id=f"{1:032x}",
        namespace="tenant-a",
    )
    foreign = make_history_record(
        run_id=f"{2:032x}",
        namespace="tenant-b",
    )
    await repository.persist_terminal_run(baseline)
    await repository.persist_terminal_run(foreign)
    catalog = EvaluationRunHistoryCatalog(repository, storage_mode="postgres")

    with pytest.raises(EvaluationRunHistoryNotFoundError):
        await catalog.compare_runs(
            EvaluationRunComparisonRequest(
                baseline_run_id=baseline.context.run_id,
                candidate_run_id=foreign.context.run_id,
            ),
            authorized_namespaces=frozenset({"tenant-a"}),
        )
