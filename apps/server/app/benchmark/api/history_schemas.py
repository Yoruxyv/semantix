from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.benchmark.api.common_schemas import (
    MAX_EVALUATION_THRESHOLDS,
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
    ThresholdEvaluationMode,
)
from app.cache.domain.namespaces import CacheNamespace


class EvaluationRunHistoryItem(StrictModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    namespace: CacheNamespace
    terminal_state: Literal["completed", "failed", "timed_out"]
    accepted_at: datetime
    started_at: datetime
    completed_at: datetime
    expires_at: datetime
    source_dataset_expires_at: datetime | None = None
    dataset: BenchmarkDatasetSummary
    reproducibility: BenchmarkReproducibilityMetadata
    metrics: BenchmarkMetrics | None
    failure_code: str | None = Field(default=None, max_length=100)
    safe_failure_detail: str | None = Field(default=None, max_length=300)

    @field_validator(
        "accepted_at",
        "started_at",
        "completed_at",
        "expires_at",
        "source_dataset_expires_at",
    )
    @classmethod
    def require_history_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Evaluation history timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_history_item(self) -> "EvaluationRunHistoryItem":
        if not (
            self.accepted_at <= self.started_at <= self.completed_at < self.expires_at
        ):
            raise ValueError("Evaluation history timestamps are inconsistent")

        if self.dataset.dataset_source == "inline":
            raise ValueError("Inline evaluations cannot appear in retained history")
        if self.dataset.dataset_source == "persisted":
            if self.source_dataset_expires_at is None:
                raise ValueError(
                    "Persisted evaluation history requires source dataset expiry"
                )
            if self.expires_at > self.source_dataset_expires_at:
                raise ValueError(
                    "Evaluation history cannot outlive its persisted source dataset"
                )
        elif self.source_dataset_expires_at is not None:
            raise ValueError(
                "Built-in evaluation history cannot carry source dataset expiry"
            )

        metadata = self.reproducibility
        if (
            metadata.dataset_id != self.dataset.dataset_id
            or metadata.dataset_source != self.dataset.dataset_source
            or metadata.dataset_schema_version != self.dataset.schema_version
            or metadata.dataset_version != self.dataset.version
            or metadata.dataset_digest != self.dataset.digest
        ):
            raise ValueError(
                "Evaluation history reproducibility metadata is inconsistent"
            )

        if self.terminal_state == "completed":
            if (
                self.metrics is None
                or self.failure_code is not None
                or self.safe_failure_detail is not None
            ):
                raise ValueError("Completed evaluation history item is inconsistent")
        elif self.metrics is not None or self.failure_code is None:
            raise ValueError("Failed evaluation history item is inconsistent")

        return self


class EvaluationRunHistoryDetail(EvaluationRunHistoryItem):
    threshold_evaluation_mode: ThresholdEvaluationMode
    threshold_evaluations: list[ThresholdEvaluation] = Field(
        max_length=MAX_EVALUATION_THRESHOLDS,
    )

    @model_validator(mode="after")
    def validate_history_detail(self) -> "EvaluationRunHistoryDetail":
        if self.terminal_state != "completed":
            if self.threshold_evaluations:
                raise ValueError(
                    "Failed evaluation history cannot contain threshold results"
                )
            return self

        if len(self.threshold_evaluations) < 2:
            raise ValueError("Completed evaluation history requires threshold results")

        thresholds = [evaluation.threshold for evaluation in self.threshold_evaluations]
        measured = [
            evaluation
            for evaluation in self.threshold_evaluations
            if evaluation.result_kind == "measured"
        ]
        if thresholds != self.reproducibility.evaluation_thresholds:
            raise ValueError(
                "Evaluation history thresholds do not match reproducibility metadata"
            )
        if (
            len(measured) != 1
            or measured[0].threshold != self.reproducibility.measured_threshold
        ):
            raise ValueError("Evaluation history measured threshold is inconsistent")
        if (
            self.metrics is None
            or self.metrics.total_queries
            != self.dataset.query_count * self.reproducibility.repetitions
        ):
            raise ValueError("Evaluation history metrics are inconsistent")
        return self


class EvaluationRunHistoryListResponse(StrictModel):
    storage_mode: Literal["disabled", "postgres"]
    retention_enabled: bool
    items: list[EvaluationRunHistoryItem]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool

    @model_validator(mode="after")
    def validate_history_page(self) -> "EvaluationRunHistoryListResponse":
        if self.retention_enabled != (self.storage_mode == "postgres"):
            raise ValueError("Evaluation history capability is inconsistent")
        if len(self.items) > self.limit:
            raise ValueError("Evaluation history page exceeds its requested limit")
        if self.has_more != (self.offset + len(self.items) < self.total):
            raise ValueError("Evaluation history pagination is inconsistent")
        if not self.retention_enabled and (self.items or self.total):
            raise ValueError("Disabled evaluation history cannot expose retained runs")
        return self


class DeleteEvaluationRunHistoryResponse(StrictModel):
    deleted: Literal[True]
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    namespace: CacheNamespace
