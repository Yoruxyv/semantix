from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.core.limits import (
    MAX_EVALUATION_CASE_ID_LENGTH,
    MAX_EVALUATION_CATEGORY_LENGTH,
    MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    MAX_EVALUATION_DATASET_NAME_LENGTH,
)
from app.providers.configuration import ProviderName

BenchmarkDatasetId = Literal["quick", "extended"]
BenchmarkCategory = str
BenchmarkOutcome = Literal[
    "true_positive",
    "true_negative",
    "false_positive",
    "false_negative",
]
ThresholdEvaluationMode = Literal["frozen_candidate_projection"]
ThresholdResultKind = Literal["measured", "projected"]
ProviderCategory = ProviderName
NormalizationMode = Literal["identity", "typo_correction"]
EvaluationDatasetSourceKind = Literal["builtin", "inline", "persisted"]
EvaluationRunRetentionState = Literal[
    "not_retained",
    "retained",
    "retention_failed",
]
EvaluationComparisonContractVersion = Literal[1]

DEFAULT_EVALUATION_THRESHOLDS = [0.70, 0.80, 0.85, 0.90, 0.92, 0.95, 0.98]
MAX_EVALUATION_THRESHOLDS = 15
MAX_BENCHMARK_REPETITIONS = 5
SHA256_PATTERN = r"^[a-f0-9]{64}$"


class BenchmarkDatasetSummary(StrictModel):
    dataset_id: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    dataset_source: EvaluationDatasetSourceKind = "builtin"
    schema_version: int | None = Field(default=None, ge=1)
    version: str = Field(min_length=1, max_length=50)
    digest: str = Field(pattern=SHA256_PATTERN)
    name: str = Field(min_length=1, max_length=MAX_EVALUATION_DATASET_NAME_LENGTH)
    description: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    )
    query_count: int = Field(ge=1)
    expected_hits: int = Field(ge=0)
    expected_misses: int = Field(ge=0)
    categories: list[BenchmarkCategory] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "BenchmarkDatasetSummary":
        if self.expected_hits + self.expected_misses != self.query_count:
            raise ValueError("Expected classifications must cover every query")
        if any(
            not category or len(category) > MAX_EVALUATION_CATEGORY_LENGTH
            for category in self.categories
        ):
            raise ValueError("Dataset categories are invalid")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("Dataset categories must be unique")
        if self.dataset_source == "builtin" and self.schema_version is not None:
            raise ValueError("Built-in datasets do not use an import schema version")
        if self.dataset_source in {"inline", "persisted"} and self.schema_version != 1:
            raise ValueError("Imported datasets must identify import schema version 1")
        return self


class BenchmarkDatasetListResponse(StrictModel):
    datasets: list[BenchmarkDatasetSummary] = Field(min_length=1)
    default_dataset_id: BenchmarkDatasetId


class BenchmarkMetrics(StrictModel):
    total_queries: int = Field(ge=1)
    cache_hits: int = Field(ge=0)
    cache_misses: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    provider_calls_avoided: int = Field(ge=0)
    hit_rate: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    median_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    average_cache_hit_latency_ms: float | None = Field(default=None, ge=0)
    average_cache_miss_latency_ms: float | None = Field(default=None, ge=0)
    estimated_latency_saved_ms: float = Field(ge=0)
    estimated_provider_cost_saved_usd: float = Field(ge=0)
    estimated_tokens_saved: int = Field(ge=0)
    true_positive_hits: int = Field(ge=0)
    true_negative_misses: int = Field(ge=0)
    false_positive_hits: int = Field(ge=0)
    false_negative_misses: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1_score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_totals(self) -> "BenchmarkMetrics":
        if self.cache_hits + self.cache_misses != self.total_queries:
            raise ValueError("Cache classifications must cover every query")
        if self.provider_calls + self.provider_calls_avoided != self.total_queries:
            raise ValueError("Provider-call totals must cover every query")
        confusion_total = (
            self.true_positive_hits
            + self.true_negative_misses
            + self.false_positive_hits
            + self.false_negative_misses
        )
        if confusion_total != self.total_queries:
            raise ValueError("Confusion-matrix totals must cover every query")
        if self.true_positive_hits + self.false_positive_hits != self.cache_hits:
            raise ValueError("Positive classifications must equal cache hits")
        if self.true_negative_misses + self.false_negative_misses != self.cache_misses:
            raise ValueError("Negative classifications must equal cache misses")
        if (
            self.provider_calls != self.cache_misses
            or self.provider_calls_avoided != self.cache_hits
        ):
            raise ValueError("Provider-call totals must match cache decisions")
        return self


class ThresholdEvaluation(StrictModel):
    threshold: float = Field(ge=0, le=1)
    result_kind: ThresholdResultKind
    hit_rate: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1_score: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    provider_calls_avoided: int = Field(ge=0)
    true_positive_hits: int = Field(ge=0)
    true_negative_misses: int = Field(ge=0)
    false_positive_hits: int = Field(ge=0)
    false_negative_misses: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_totals(self) -> "ThresholdEvaluation":
        projected_hits = self.true_positive_hits + self.false_positive_hits
        if projected_hits != self.provider_calls_avoided:
            raise ValueError(
                "Projected hits must equal projected provider calls avoided"
            )
        return self


class BenchmarkReproducibilityMetadata(StrictModel):
    application_version: str = Field(min_length=1, max_length=50)
    dataset_id: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
    )
    dataset_source: EvaluationDatasetSourceKind
    dataset_schema_version: int | None = Field(default=None, ge=1)
    dataset_version: str = Field(min_length=1, max_length=50)
    dataset_digest: str = Field(pattern=SHA256_PATTERN)
    embedding_provider_category: ProviderCategory
    generation_provider_category: ProviderCategory
    generation_configuration_fingerprint: str = Field(pattern=SHA256_PATTERN)
    comparison_contract_version: EvaluationComparisonContractVersion = 1
    embedding_dimensions: int = Field(gt=0)
    embedding_space_fingerprint: str = Field(pattern=SHA256_PATTERN)
    normalization_mode: NormalizationMode
    normalization_fingerprint: str = Field(pattern=SHA256_PATTERN)
    measured_threshold: float = Field(ge=0, le=1)
    evaluation_thresholds: list[float] = Field(
        min_length=2,
        max_length=MAX_EVALUATION_THRESHOLDS,
    )
    repetitions: int = Field(ge=1, le=MAX_BENCHMARK_REPETITIONS)
    reset_cache_before_run: bool
    estimated_cost_per_request_usd: float = Field(ge=0, le=100)
    estimated_cost_per_1k_tokens_usd: float = Field(ge=0, le=100)
    evaluation_timeout_seconds: float = Field(gt=0, le=3_600)
    configuration_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @field_validator("evaluation_thresholds")
    @classmethod
    def validate_thresholds(cls, value: list[float]) -> list[float]:
        if any(threshold < 0 or threshold > 1 for threshold in value):
            raise ValueError("Evaluation thresholds must be between 0 and 1")
        if value != sorted(set(value)):
            raise ValueError("Evaluation thresholds must be ordered and unique")
        return value
