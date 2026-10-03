from app.benchmark.api.comparison_schemas import (
    EvaluationComparisonMetricDeltas,
    EvaluationThresholdComparisonDelta,
)
from app.benchmark.api.history_schemas import EvaluationRunHistoryDetail


def _optional_delta(
    baseline: float | None,
    candidate: float | None,
) -> float | None:
    if baseline is None or candidate is None:
        return None
    return candidate - baseline


def metric_deltas(
    baseline: EvaluationRunHistoryDetail,
    candidate: EvaluationRunHistoryDetail,
) -> EvaluationComparisonMetricDeltas:
    baseline_metrics = baseline.metrics
    candidate_metrics = candidate.metrics
    if baseline_metrics is None or candidate_metrics is None:
        raise ValueError("Completed evaluation comparison requires aggregate metrics")

    return EvaluationComparisonMetricDeltas(
        measured_threshold=(
            candidate.reproducibility.measured_threshold
            - baseline.reproducibility.measured_threshold
        ),
        total_queries=candidate_metrics.total_queries - baseline_metrics.total_queries,
        cache_hits=candidate_metrics.cache_hits - baseline_metrics.cache_hits,
        cache_misses=candidate_metrics.cache_misses - baseline_metrics.cache_misses,
        provider_calls=candidate_metrics.provider_calls
        - baseline_metrics.provider_calls,
        provider_calls_avoided=(
            candidate_metrics.provider_calls_avoided
            - baseline_metrics.provider_calls_avoided
        ),
        hit_rate=candidate_metrics.hit_rate - baseline_metrics.hit_rate,
        average_latency_ms=(
            candidate_metrics.average_latency_ms - baseline_metrics.average_latency_ms
        ),
        median_latency_ms=(
            candidate_metrics.median_latency_ms - baseline_metrics.median_latency_ms
        ),
        p95_latency_ms=(
            candidate_metrics.p95_latency_ms - baseline_metrics.p95_latency_ms
        ),
        average_cache_hit_latency_ms=_optional_delta(
            baseline_metrics.average_cache_hit_latency_ms,
            candidate_metrics.average_cache_hit_latency_ms,
        ),
        average_cache_miss_latency_ms=_optional_delta(
            baseline_metrics.average_cache_miss_latency_ms,
            candidate_metrics.average_cache_miss_latency_ms,
        ),
        estimated_latency_saved_ms=(
            candidate_metrics.estimated_latency_saved_ms
            - baseline_metrics.estimated_latency_saved_ms
        ),
        estimated_provider_cost_saved_usd=(
            candidate_metrics.estimated_provider_cost_saved_usd
            - baseline_metrics.estimated_provider_cost_saved_usd
        ),
        estimated_tokens_saved=(
            candidate_metrics.estimated_tokens_saved
            - baseline_metrics.estimated_tokens_saved
        ),
        true_positive_hits=(
            candidate_metrics.true_positive_hits - baseline_metrics.true_positive_hits
        ),
        true_negative_misses=(
            candidate_metrics.true_negative_misses
            - baseline_metrics.true_negative_misses
        ),
        false_positive_hits=(
            candidate_metrics.false_positive_hits - baseline_metrics.false_positive_hits
        ),
        false_negative_misses=(
            candidate_metrics.false_negative_misses
            - baseline_metrics.false_negative_misses
        ),
        precision=candidate_metrics.precision - baseline_metrics.precision,
        recall=candidate_metrics.recall - baseline_metrics.recall,
        f1_score=candidate_metrics.f1_score - baseline_metrics.f1_score,
    )


def threshold_deltas(
    baseline: EvaluationRunHistoryDetail,
    candidate: EvaluationRunHistoryDetail,
) -> list[EvaluationThresholdComparisonDelta]:
    baseline_by_threshold = {
        evaluation.threshold: evaluation
        for evaluation in baseline.threshold_evaluations
    }
    candidate_by_threshold = {
        evaluation.threshold: evaluation
        for evaluation in candidate.threshold_evaluations
    }

    shared_thresholds = sorted(
        baseline_by_threshold.keys() & candidate_by_threshold.keys()
    )
    deltas: list[EvaluationThresholdComparisonDelta] = []
    for threshold in shared_thresholds:
        baseline_evaluation = baseline_by_threshold[threshold]
        candidate_evaluation = candidate_by_threshold[threshold]
        deltas.append(
            EvaluationThresholdComparisonDelta(
                threshold=threshold,
                baseline_result_kind=baseline_evaluation.result_kind,
                candidate_result_kind=candidate_evaluation.result_kind,
                hit_rate=candidate_evaluation.hit_rate - baseline_evaluation.hit_rate,
                precision=(
                    candidate_evaluation.precision - baseline_evaluation.precision
                ),
                recall=candidate_evaluation.recall - baseline_evaluation.recall,
                f1_score=candidate_evaluation.f1_score - baseline_evaluation.f1_score,
                average_latency_ms=(
                    candidate_evaluation.average_latency_ms
                    - baseline_evaluation.average_latency_ms
                ),
                provider_calls_avoided=(
                    candidate_evaluation.provider_calls_avoided
                    - baseline_evaluation.provider_calls_avoided
                ),
                true_positive_hits=(
                    candidate_evaluation.true_positive_hits
                    - baseline_evaluation.true_positive_hits
                ),
                true_negative_misses=(
                    candidate_evaluation.true_negative_misses
                    - baseline_evaluation.true_negative_misses
                ),
                false_positive_hits=(
                    candidate_evaluation.false_positive_hits
                    - baseline_evaluation.false_positive_hits
                ),
                false_negative_misses=(
                    candidate_evaluation.false_negative_misses
                    - baseline_evaluation.false_negative_misses
                ),
            )
        )
    return deltas
