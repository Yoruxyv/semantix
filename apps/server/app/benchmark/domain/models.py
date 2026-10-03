from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.benchmark.api.schemas import (
    BenchmarkCategory,
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    NormalizationMode,
    ProviderCategory,
    ThresholdEvaluation,
    ThresholdEvaluationMode,
)
from app.core.config import (
    EvaluationDatasetStorageMode,
    EvaluationRunHistoryStorageMode,
)
from app.core.limits import (
    DEFAULT_EVALUATION_DATASET_CLEANUP_BATCH_SIZE,
    DEFAULT_EVALUATION_DATASET_DEFAULT_RETENTION_DAYS,
    DEFAULT_EVALUATION_DATASET_MAX_CASES,
    DEFAULT_EVALUATION_DATASET_MAX_DECODED_BYTES,
    DEFAULT_EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE,
    DEFAULT_EVALUATION_DATASET_MAX_RETENTION_DAYS,
    DEFAULT_EVALUATION_MAX_WORKLOAD_QUERIES,
)

EvaluationRunTerminalState = Literal["completed", "failed", "timed_out"]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    category: BenchmarkCategory
    prompt: str
    expected_cache_hit: bool
    expected_match_case_id: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkDataset:
    summary: BenchmarkDatasetSummary
    cases: tuple[BenchmarkCase, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    expected_cache_hit: bool
    actual_cache_hit: bool
    latency_ms: float
    provider_called: bool
    similarity_score: float | None
    estimated_tokens_saved: int = 0


@dataclass(frozen=True, slots=True)
class BenchmarkRuntimeConfiguration:
    application_version: str
    embedding_provider_category: ProviderCategory
    generation_provider_category: ProviderCategory
    embedding_dimensions: int
    embedding_space_fingerprint: str
    generation_configuration_fingerprint: str
    normalization_mode: NormalizationMode
    normalization_fingerprint: str
    evaluation_timeout_seconds: float
    evaluation_dataset_max_cases: int = DEFAULT_EVALUATION_DATASET_MAX_CASES
    evaluation_dataset_max_decoded_bytes: int = (
        DEFAULT_EVALUATION_DATASET_MAX_DECODED_BYTES
    )
    evaluation_max_workload_queries: int = DEFAULT_EVALUATION_MAX_WORKLOAD_QUERIES
    evaluation_dataset_storage: EvaluationDatasetStorageMode = "session"
    evaluation_dataset_max_persisted_per_namespace: int = (
        DEFAULT_EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE
    )
    evaluation_dataset_default_retention_days: int = (
        DEFAULT_EVALUATION_DATASET_DEFAULT_RETENTION_DAYS
    )
    evaluation_dataset_max_retention_days: int = (
        DEFAULT_EVALUATION_DATASET_MAX_RETENTION_DAYS
    )
    evaluation_dataset_cleanup_batch_size: int = (
        DEFAULT_EVALUATION_DATASET_CLEANUP_BATCH_SIZE
    )
    evaluation_run_history_storage: EvaluationRunHistoryStorageMode = "disabled"
    evaluation_run_history_retention_days: int | None = None
    evaluation_run_history_max_per_namespace: int | None = None
    evaluation_run_history_cleanup_batch_size: int | None = None


@dataclass(frozen=True, slots=True)
class AcceptedEvaluationRunContext:
    run_id: str
    accepted_at: datetime
    dataset: BenchmarkDatasetSummary
    history_namespace: str | None
    source_dataset_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class EvaluationRunHistoryRecord:
    context: AcceptedEvaluationRunContext
    terminal_state: EvaluationRunTerminalState
    started_at: datetime
    completed_at: datetime
    reproducibility: BenchmarkReproducibilityMetadata
    metrics: BenchmarkMetrics | None
    threshold_evaluation_mode: ThresholdEvaluationMode
    threshold_evaluations: tuple[ThresholdEvaluation, ...]
    failure_code: str | None = None
    safe_failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.context.history_namespace is None:
            raise ValueError("Retained evaluation history requires a namespace")
        if self.completed_at < self.started_at:
            raise ValueError("Evaluation history completion cannot precede its start")
        if self.failure_code is not None and len(self.failure_code) > 100:
            raise ValueError("Evaluation history failure code is too long")
        if self.safe_failure_detail is not None and len(self.safe_failure_detail) > 300:
            raise ValueError("Evaluation history safe failure detail is too long")
        if self.terminal_state == "completed":
            if (
                self.metrics is None
                or not self.threshold_evaluations
                or self.failure_code is not None
                or self.safe_failure_detail is not None
            ):
                raise ValueError("Completed evaluation history is inconsistent")
            return
        if (
            self.metrics is not None
            or self.threshold_evaluations
            or self.failure_code is None
        ):
            raise ValueError("Failed evaluation history is inconsistent")


@dataclass(frozen=True, slots=True)
class RetainedEvaluationRunSummary:
    context: AcceptedEvaluationRunContext
    terminal_state: EvaluationRunTerminalState
    started_at: datetime
    completed_at: datetime
    expires_at: datetime
    reproducibility: BenchmarkReproducibilityMetadata
    metrics: BenchmarkMetrics | None
    failure_code: str | None = None
    safe_failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.context.history_namespace is None:
            raise ValueError("Retained evaluation history requires a namespace")
        if not (
            self.context.accepted_at
            <= self.started_at
            <= self.completed_at
            < self.expires_at
        ):
            raise ValueError("Retained evaluation history timestamps are inconsistent")
        if self.failure_code is not None and len(self.failure_code) > 100:
            raise ValueError("Evaluation history failure code is too long")
        if self.safe_failure_detail is not None and len(self.safe_failure_detail) > 300:
            raise ValueError("Evaluation history safe failure detail is too long")
        if self.terminal_state == "completed":
            if (
                self.metrics is None
                or self.failure_code is not None
                or self.safe_failure_detail is not None
            ):
                raise ValueError("Completed evaluation history summary is inconsistent")
            return
        if self.metrics is not None or self.failure_code is None:
            raise ValueError("Failed evaluation history summary is inconsistent")


@dataclass(frozen=True, slots=True)
class RetainedEvaluationRun:
    record: EvaluationRunHistoryRecord
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.expires_at <= self.record.completed_at:
            raise ValueError("Retained evaluation history expiry is inconsistent")

    @property
    def summary(self) -> RetainedEvaluationRunSummary:
        record = self.record
        return RetainedEvaluationRunSummary(
            context=record.context,
            terminal_state=record.terminal_state,
            started_at=record.started_at,
            completed_at=record.completed_at,
            expires_at=self.expires_at,
            reproducibility=record.reproducibility,
            metrics=record.metrics,
            failure_code=record.failure_code,
            safe_failure_detail=record.safe_failure_detail,
        )


@dataclass(frozen=True, slots=True)
class RetainedEvaluationRunPage:
    items: tuple[RetainedEvaluationRunSummary, ...]
    total: int


@dataclass(frozen=True, slots=True)
class PersistedEvaluationDatasetMetadata:
    dataset_id: str
    namespace: str
    name: str
    description: str | None
    schema_version: int
    digest: str
    case_count: int
    decoded_bytes: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PersistedEvaluationDataset:
    metadata: PersistedEvaluationDatasetMetadata
    dataset: BenchmarkDataset


@dataclass(frozen=True, slots=True)
class PersistedEvaluationDatasetPage:
    items: tuple[PersistedEvaluationDatasetMetadata, ...]
    total: int
