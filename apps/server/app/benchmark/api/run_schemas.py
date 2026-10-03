from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.benchmark.api.common_schemas import (
    DEFAULT_EVALUATION_THRESHOLDS,
    MAX_BENCHMARK_REPETITIONS,
    MAX_EVALUATION_THRESHOLDS,
    SHA256_PATTERN,
    BenchmarkCategory,
    BenchmarkDatasetId,
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkOutcome,
    BenchmarkReproducibilityMetadata,
    EvaluationRunRetentionState,
    ThresholdEvaluation,
    ThresholdEvaluationMode,
)
from app.benchmark.api.dataset_schemas import (
    BuiltinEvaluationDatasetSource,
    EvaluationDatasetSource,
)
from app.cache.domain.namespaces import CacheNamespace
from app.core.limits import (
    MAX_EVALUATION_CASE_ID_LENGTH,
    MAX_EVALUATION_CATEGORY_LENGTH,
    MAX_EVALUATION_NOTE_LENGTH,
    MAX_PROMPT_LENGTH,
)


class EvaluationRunOptions(StrictModel):
    threshold: float = Field(default=0.92, ge=0, le=1)
    evaluation_thresholds: list[float] = Field(
        default_factory=lambda: list(DEFAULT_EVALUATION_THRESHOLDS),
        min_length=2,
        max_length=MAX_EVALUATION_THRESHOLDS,
    )
    repetitions: int = Field(default=1, ge=1, le=MAX_BENCHMARK_REPETITIONS)
    reset_cache_before_run: bool = True
    estimated_cost_per_request_usd: float = Field(default=0, ge=0, le=100)
    estimated_cost_per_1k_tokens_usd: float = Field(default=0, ge=0, le=100)
    allow_external_provider_calls: Literal[True]

    @field_validator("evaluation_thresholds")
    @classmethod
    def validate_evaluation_thresholds(cls, value: list[float]) -> list[float]:
        if any(threshold < 0 or threshold > 1 for threshold in value):
            raise ValueError("Evaluation thresholds must be between 0 and 1")
        unique = sorted(set(value))
        if len(unique) != len(value):
            raise ValueError("Evaluation thresholds must be unique")
        return unique

    @model_validator(mode="after")
    def include_measured_threshold(self) -> "EvaluationRunOptions":
        thresholds = sorted({*self.evaluation_thresholds, self.threshold})
        if len(thresholds) > MAX_EVALUATION_THRESHOLDS:
            raise ValueError(
                "Evaluation thresholds, including the measured threshold, "
                f"cannot exceed {MAX_EVALUATION_THRESHOLDS}"
            )
        self.evaluation_thresholds = thresholds
        return self


class BenchmarkRunRequest(EvaluationRunOptions):
    dataset_id: BenchmarkDatasetId = "quick"


class EvaluationRunRequest(EvaluationRunOptions):
    history_namespace: CacheNamespace | None = None
    dataset_source: EvaluationDatasetSource = Field(
        default_factory=lambda: BuiltinEvaluationDatasetSource(kind="builtin")
    )

    @model_validator(mode="after")
    def validate_history_namespace(self) -> "EvaluationRunRequest":
        if self.history_namespace is not None and not isinstance(
            self.dataset_source, BuiltinEvaluationDatasetSource
        ):
            raise ValueError(
                "history_namespace is supported only for built-in evaluation datasets"
            )
        return self


class BenchmarkQueryResult(StrictModel):
    sequence: int = Field(ge=1)
    repetition: int = Field(ge=1)
    case_id: str = Field(min_length=1, max_length=100)
    category: BenchmarkCategory = Field(
        min_length=1,
        max_length=MAX_EVALUATION_CATEGORY_LENGTH,
    )
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    expected_cache_hit: bool
    expected_match_case_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
    )
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_NOTE_LENGTH,
    )
    actual_cache_hit: bool
    correct: bool
    outcome: BenchmarkOutcome
    similarity_score: float | None = Field(default=None, ge=-1, le=1)
    latency_ms: float = Field(ge=0)
    provider_called: bool
    matched_prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PROMPT_LENGTH,
    )
    matched_cache_key: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_evidence(self) -> "BenchmarkQueryResult":
        expected_outcome: BenchmarkOutcome
        if self.actual_cache_hit:
            expected_outcome = (
                "true_positive" if self.expected_cache_hit else "false_positive"
            )
        else:
            expected_outcome = (
                "false_negative" if self.expected_cache_hit else "true_negative"
            )
        if self.outcome != expected_outcome:
            raise ValueError("Query outcome does not match its cache decisions")
        if self.correct != (self.expected_cache_hit == self.actual_cache_hit):
            raise ValueError("Query correctness does not match its cache decisions")
        if not self.expected_cache_hit and self.expected_match_case_id is not None:
            raise ValueError("Expected misses cannot identify an expected match")
        if self.provider_called == self.actual_cache_hit:
            raise ValueError("Provider-call evidence does not match the cache decision")
        if self.actual_cache_hit and (
            self.matched_prompt is None or self.matched_cache_key is None
        ):
            raise ValueError("Cache-hit evidence must identify the matched entry")
        if not self.actual_cache_hit and (
            self.matched_prompt is not None or self.matched_cache_key is not None
        ):
            raise ValueError("Cache-miss evidence cannot identify a matched entry")
        return self


class EvaluationRunRetentionStatus(StrictModel):
    state: EvaluationRunRetentionState


class BenchmarkRunResponse(StrictModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    started_at: datetime
    completed_at: datetime
    dataset: BenchmarkDatasetSummary
    threshold: float = Field(ge=0, le=1)
    repetitions: int = Field(ge=1, le=MAX_BENCHMARK_REPETITIONS)
    reset_cache_before_run: bool
    estimated_cost_per_request_usd: float = Field(ge=0)
    estimated_cost_per_1k_tokens_usd: float = Field(ge=0)
    reproducibility: BenchmarkReproducibilityMetadata
    history_retention: EvaluationRunRetentionStatus = Field(
        default_factory=lambda: EvaluationRunRetentionStatus(state="not_retained")
    )
    metrics: BenchmarkMetrics
    threshold_evaluation_mode: ThresholdEvaluationMode
    threshold_evaluations: list[ThresholdEvaluation] = Field(
        min_length=2,
        max_length=MAX_EVALUATION_THRESHOLDS,
    )
    query_results: list[BenchmarkQueryResult] = Field(min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Benchmark timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_run(self) -> "BenchmarkRunResponse":
        if self.completed_at < self.started_at:
            raise ValueError("Benchmark completion cannot precede its start")
        if len(self.query_results) != self.dataset.query_count * self.repetitions:
            raise ValueError("Benchmark results do not match the requested workload")
        total_queries = len(self.query_results)
        outcomes = {
            outcome: sum(result.outcome == outcome for result in self.query_results)
            for outcome in (
                "true_positive",
                "true_negative",
                "false_positive",
                "false_negative",
            )
        }
        if (
            self.metrics.total_queries != total_queries
            or self.metrics.true_positive_hits != outcomes["true_positive"]
            or self.metrics.true_negative_misses != outcomes["true_negative"]
            or self.metrics.false_positive_hits != outcomes["false_positive"]
            or self.metrics.false_negative_misses != outcomes["false_negative"]
            or self.metrics.provider_calls
            != sum(result.provider_called for result in self.query_results)
        ):
            raise ValueError("Benchmark metrics do not match query evidence")

        thresholds = [evaluation.threshold for evaluation in self.threshold_evaluations]
        measured = [
            evaluation
            for evaluation in self.threshold_evaluations
            if evaluation.result_kind == "measured"
        ]
        if thresholds != sorted(set(thresholds)):
            raise ValueError("Threshold evaluations must be ordered and unique")
        if len(measured) != 1 or measured[0].threshold != self.threshold:
            raise ValueError("The measured threshold must appear exactly once")
        for evaluation in self.threshold_evaluations:
            confusion_total = (
                evaluation.true_positive_hits
                + evaluation.true_negative_misses
                + evaluation.false_positive_hits
                + evaluation.false_negative_misses
            )
            if confusion_total != total_queries:
                raise ValueError(
                    "Threshold confusion-matrix totals must cover every query"
                )

        metadata = self.reproducibility
        if (
            metadata.dataset_id != self.dataset.dataset_id
            or metadata.dataset_source != self.dataset.dataset_source
            or metadata.dataset_schema_version != self.dataset.schema_version
            or metadata.dataset_version != self.dataset.version
            or metadata.dataset_digest != self.dataset.digest
            or metadata.measured_threshold != self.threshold
            or metadata.evaluation_thresholds != thresholds
            or metadata.repetitions != self.repetitions
            or metadata.reset_cache_before_run != self.reset_cache_before_run
            or metadata.estimated_cost_per_request_usd
            != self.estimated_cost_per_request_usd
            or metadata.estimated_cost_per_1k_tokens_usd
            != self.estimated_cost_per_1k_tokens_usd
        ):
            raise ValueError("Reproducibility metadata does not match the run")
        return self
