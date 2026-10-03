from typing import Literal

from pydantic import Field, model_validator

from app.api.schemas import StrictModel
from app.benchmark.api.common_schemas import ThresholdResultKind
from app.benchmark.api.history_schemas import EvaluationRunHistoryDetail

EvaluationComparisonStatus = Literal["compatible", "warning", "incompatible"]
EvaluationComparisonBlockerCode = Literal[
    "namespace_mismatch",
    "baseline_not_completed",
    "candidate_not_completed",
    "dataset_schema_mismatch",
    "dataset_digest_mismatch",
    "embedding_dimensions_mismatch",
    "embedding_space_mismatch",
    "normalization_mode_mismatch",
    "normalization_fingerprint_mismatch",
    "repetitions_mismatch",
    "reset_policy_mismatch",
    "comparison_contract_version_mismatch",
    "threshold_evaluation_mode_mismatch",
]
EvaluationComparisonWarningCode = Literal[
    "generation_provider_changed",
    "generation_configuration_changed",
    "application_version_changed",
    "cost_assumptions_changed",
    "evaluation_timeout_changed",
    "projection_list_changed",
    "persisted_dataset_identity_changed",
]


class EvaluationRunComparisonRequest(StrictModel):
    baseline_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    candidate_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def require_distinct_runs(self) -> "EvaluationRunComparisonRequest":
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("Evaluation comparison requires two distinct runs")
        return self


class EvaluationComparisonBlocker(StrictModel):
    code: EvaluationComparisonBlockerCode
    detail: str = Field(min_length=1, max_length=300)


class EvaluationComparisonWarning(StrictModel):
    code: EvaluationComparisonWarningCode
    detail: str = Field(min_length=1, max_length=300)


class EvaluationComparisonCompatibility(StrictModel):
    status: EvaluationComparisonStatus
    can_compare: bool
    incompatibilities: list[EvaluationComparisonBlocker]
    warnings: list[EvaluationComparisonWarning]
    case_evidence: Literal["not_retained"] = "not_retained"
    opaque_configuration_fingerprint_matches: bool

    @model_validator(mode="after")
    def validate_compatibility(self) -> "EvaluationComparisonCompatibility":
        expected_status: EvaluationComparisonStatus
        if self.incompatibilities:
            expected_status = "incompatible"
        elif self.warnings:
            expected_status = "warning"
        else:
            expected_status = "compatible"

        if self.status != expected_status:
            raise ValueError("Evaluation comparison status is inconsistent")
        if self.can_compare != (not self.incompatibilities):
            raise ValueError("Evaluation comparison capability is inconsistent")
        return self


class EvaluationComparisonMetricDeltas(StrictModel):
    measured_threshold: float
    total_queries: int
    cache_hits: int
    cache_misses: int
    provider_calls: int
    provider_calls_avoided: int
    hit_rate: float
    average_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    average_cache_hit_latency_ms: float | None
    average_cache_miss_latency_ms: float | None
    estimated_latency_saved_ms: float
    estimated_provider_cost_saved_usd: float
    estimated_tokens_saved: int
    true_positive_hits: int
    true_negative_misses: int
    false_positive_hits: int
    false_negative_misses: int
    precision: float
    recall: float
    f1_score: float


class EvaluationThresholdComparisonDelta(StrictModel):
    threshold: float = Field(ge=0, le=1)
    baseline_result_kind: ThresholdResultKind
    candidate_result_kind: ThresholdResultKind
    hit_rate: float
    precision: float
    recall: float
    f1_score: float
    average_latency_ms: float
    provider_calls_avoided: int
    true_positive_hits: int
    true_negative_misses: int
    false_positive_hits: int
    false_negative_misses: int


class EvaluationRunComparisonResponse(StrictModel):
    baseline: EvaluationRunHistoryDetail
    candidate: EvaluationRunHistoryDetail
    compatibility: EvaluationComparisonCompatibility
    metric_deltas: EvaluationComparisonMetricDeltas | None
    threshold_deltas: list[EvaluationThresholdComparisonDelta]

    @model_validator(mode="after")
    def validate_comparison_payload(self) -> "EvaluationRunComparisonResponse":
        if self.compatibility.can_compare:
            if self.metric_deltas is None:
                raise ValueError("Comparable evaluation runs require metric deltas")
        elif self.metric_deltas is not None or self.threshold_deltas:
            raise ValueError("Incompatible evaluation runs cannot expose deltas")
        return self
