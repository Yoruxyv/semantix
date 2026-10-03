import math
import statistics
from collections.abc import Sequence
from dataclasses import replace

from app.benchmark.api.schemas import BenchmarkMetrics, ThresholdEvaluation
from app.benchmark.domain.models import BenchmarkObservation


def _safe_ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _quality_metrics(
    observations: Sequence[BenchmarkObservation],
) -> tuple[int, int, int, int, float, float, float]:
    false_positives = sum(
        result.actual_cache_hit and not result.expected_cache_hit
        for result in observations
    )
    false_negatives = sum(
        not result.actual_cache_hit and result.expected_cache_hit
        for result in observations
    )
    true_positives = sum(
        result.actual_cache_hit and result.expected_cache_hit for result in observations
    )
    true_negatives = sum(
        not result.actual_cache_hit and not result.expected_cache_hit
        for result in observations
    )
    precision = _safe_ratio(true_positives, true_positives + false_positives)
    recall = _safe_ratio(true_positives, true_positives + false_negatives)
    f1_score = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return (
        true_positives,
        true_negatives,
        false_positives,
        false_negatives,
        precision,
        recall,
        f1_score,
    )


def calculate_metrics(
    observations: Sequence[BenchmarkObservation],
    *,
    estimated_cost_per_request_usd: float,
    estimated_cost_per_1k_tokens_usd: float,
) -> BenchmarkMetrics:
    if not observations:
        raise ValueError("At least one benchmark observation is required")

    latencies = [result.latency_ms for result in observations]
    hit_latencies = [
        result.latency_ms for result in observations if result.actual_cache_hit
    ]
    miss_latencies = [
        result.latency_ms for result in observations if not result.actual_cache_hit
    ]
    cache_hits = len(hit_latencies)
    provider_calls = sum(result.provider_called for result in observations)
    provider_calls_avoided = len(observations) - provider_calls
    average_hit_latency = statistics.fmean(hit_latencies) if hit_latencies else None
    average_miss_latency = statistics.fmean(miss_latencies) if miss_latencies else None
    estimated_latency_saved = (
        0.0
        if average_miss_latency is None
        else max(
            0.0,
            average_miss_latency * cache_hits - sum(hit_latencies),
        )
    )
    estimated_tokens_saved = sum(
        result.estimated_tokens_saved
        for result in observations
        if result.actual_cache_hit
    )
    estimated_cost_saved = (
        provider_calls_avoided * estimated_cost_per_request_usd
        + estimated_tokens_saved / 1_000 * estimated_cost_per_1k_tokens_usd
    )
    (
        true_positives,
        true_negatives,
        false_positives,
        false_negatives,
        precision,
        recall,
        f1_score,
    ) = _quality_metrics(observations)

    return BenchmarkMetrics(
        total_queries=len(observations),
        cache_hits=cache_hits,
        cache_misses=len(miss_latencies),
        provider_calls=provider_calls,
        provider_calls_avoided=provider_calls_avoided,
        hit_rate=_safe_ratio(cache_hits, len(observations)),
        average_latency_ms=statistics.fmean(latencies),
        median_latency_ms=statistics.median(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        average_cache_hit_latency_ms=average_hit_latency,
        average_cache_miss_latency_ms=average_miss_latency,
        estimated_latency_saved_ms=estimated_latency_saved,
        estimated_provider_cost_saved_usd=estimated_cost_saved,
        estimated_tokens_saved=estimated_tokens_saved,
        true_positive_hits=true_positives,
        true_negative_misses=true_negatives,
        false_positive_hits=false_positives,
        false_negative_misses=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
    )


def evaluate_frozen_candidate_thresholds(
    observations: Sequence[BenchmarkObservation],
    thresholds: Sequence[float],
    *,
    measured_threshold: float,
) -> list[ThresholdEvaluation]:
    if not observations:
        raise ValueError("At least one benchmark observation is required")

    all_latencies = [observation.latency_ms for observation in observations]
    measured_hit_latencies = [
        observation.latency_ms
        for observation in observations
        if observation.actual_cache_hit
    ]
    measured_miss_latencies = [
        observation.latency_ms
        for observation in observations
        if not observation.actual_cache_hit
    ]
    average_latency = statistics.fmean(all_latencies)
    hit_latency = (
        statistics.fmean(measured_hit_latencies)
        if measured_hit_latencies
        else average_latency
    )
    miss_latency = (
        statistics.fmean(measured_miss_latencies)
        if measured_miss_latencies
        else average_latency
    )

    evaluations: list[ThresholdEvaluation] = []
    for threshold in sorted(set(thresholds)):
        projected = [
            replace(
                observation,
                actual_cache_hit=(
                    observation.similarity_score is not None
                    and observation.similarity_score >= threshold
                ),
            )
            for observation in observations
        ]
        projected_hits = sum(result.actual_cache_hit for result in projected)
        (
            true_positives,
            true_negatives,
            false_positives,
            false_negatives,
            precision,
            recall,
            f1_score,
        ) = _quality_metrics(projected)
        projected_average_latency = (
            projected_hits * hit_latency
            + (len(projected) - projected_hits) * miss_latency
        ) / len(projected)
        evaluations.append(
            ThresholdEvaluation(
                threshold=threshold,
                result_kind=(
                    "measured" if threshold == measured_threshold else "projected"
                ),
                hit_rate=_safe_ratio(projected_hits, len(projected)),
                precision=precision,
                recall=recall,
                f1_score=f1_score,
                average_latency_ms=projected_average_latency,
                provider_calls_avoided=projected_hits,
                true_positive_hits=true_positives,
                true_negative_misses=true_negatives,
                false_positive_hits=false_positives,
                false_negative_misses=false_negatives,
            )
        )
    return evaluations
