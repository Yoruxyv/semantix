from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.benchmark.api.common_schemas import (
    MAX_BENCHMARK_REPETITIONS,
    MAX_EVALUATION_THRESHOLDS,
    SHA256_PATTERN,
    BenchmarkDatasetId,
)
from app.cache.domain.namespaces import CacheNamespace
from app.core.limits import (
    MAX_EVALUATION_CASE_ID_LENGTH,
    MAX_EVALUATION_CATEGORY_LENGTH,
    MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    MAX_EVALUATION_DATASET_NAME_LENGTH,
    MAX_EVALUATION_NOTE_LENGTH,
    MAX_PROMPT_LENGTH,
)


class BuiltinEvaluationDatasetSource(StrictModel):
    kind: Literal["builtin"]
    dataset_id: BenchmarkDatasetId = "quick"


class InlineEvaluationDatasetSource(StrictModel):
    kind: Literal["inline"]
    definition: object


class PersistedEvaluationDatasetSource(StrictModel):
    kind: Literal["persisted"]
    dataset_id: UUID
    namespace: CacheNamespace | None = None


EvaluationDatasetSource = Annotated[
    BuiltinEvaluationDatasetSource
    | InlineEvaluationDatasetSource
    | PersistedEvaluationDatasetSource,
    Field(discriminator="kind"),
]


class EvaluationDatasetValidationRequest(StrictModel):
    dataset: object
    repetitions: int = Field(default=1, ge=1, le=MAX_BENCHMARK_REPETITIONS)
    threshold_count: int = Field(default=2, ge=2, le=MAX_EVALUATION_THRESHOLDS)


class EvaluationDatasetValidationIssue(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=300)
    pointer: str = Field(min_length=1, max_length=300)
    case_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
    )
    case_index: int | None = Field(default=None, ge=0)


class ImportedEvaluationCase(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    case_id: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    expected_cache_hit: bool
    expected_match_case_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_CATEGORY_LENGTH,
    )
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_NOTE_LENGTH,
    )


class ImportedEvaluationDatasetDefinition(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal[1]
    name: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_DATASET_NAME_LENGTH,
    )
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    )
    cases: list[ImportedEvaluationCase] = Field(min_length=1)


class EvaluationDatasetWarning(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=300)
    count: int = Field(ge=1)


class EvaluationDatasetPreviewLimits(StrictModel):
    max_cases: int = Field(ge=1)
    max_decoded_bytes: int = Field(ge=1)
    max_workload_queries: int = Field(ge=1)


class EvaluationDatasetPreview(StrictModel):
    schema_version: Literal[1]
    dataset_id: str = Field(
        min_length=1,
        max_length=MAX_EVALUATION_CASE_ID_LENGTH,
    )
    digest: str = Field(pattern=SHA256_PATTERN)
    name: str = Field(min_length=1, max_length=MAX_EVALUATION_DATASET_NAME_LENGTH)
    description: str | None = Field(
        default=None,
        max_length=MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    )
    case_count: int = Field(ge=1)
    expected_hits: int = Field(ge=0)
    expected_misses: int = Field(ge=0)
    categories: list[str] = Field(min_length=1)
    decoded_bytes: int = Field(ge=1)
    warnings: list[EvaluationDatasetWarning]
    query_executions: int = Field(ge=1)
    threshold_projection_evaluations: int = Field(ge=2)
    maximum_provider_calls: int = Field(ge=1)
    provider_calls_made: Literal[0]
    limits: EvaluationDatasetPreviewLimits


class PersistedEvaluationDatasetMetadata(StrictModel):
    dataset_id: UUID
    namespace: CacheNamespace
    name: str = Field(min_length=1, max_length=MAX_EVALUATION_DATASET_NAME_LENGTH)
    description: str | None = Field(
        default=None,
        max_length=MAX_EVALUATION_DATASET_DESCRIPTION_LENGTH,
    )
    source_type: Literal["imported"] = "imported"
    schema_version: Literal[1]
    digest: str = Field(pattern=SHA256_PATTERN)
    case_count: int = Field(ge=1)
    decoded_bytes: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dataset timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_retention(self) -> "PersistedEvaluationDatasetMetadata":
        if self.expires_at <= self.created_at:
            raise ValueError("Dataset expiry must follow creation")
        return self


class PersistedEvaluationDatasetCatalogLimits(StrictModel):
    default_retention_days: int = Field(ge=1)
    max_retention_days: int = Field(ge=1)
    max_persisted_per_namespace: int = Field(ge=1)


class PersistedEvaluationDatasetListResponse(StrictModel):
    storage_mode: Literal["session", "postgres"]
    persistence_enabled: bool
    items: list[PersistedEvaluationDatasetMetadata]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool
    limits: PersistedEvaluationDatasetCatalogLimits

    @model_validator(mode="after")
    def validate_page(self) -> "PersistedEvaluationDatasetListResponse":
        if self.persistence_enabled != (self.storage_mode == "postgres"):
            raise ValueError("Dataset storage capability is inconsistent")
        if len(self.items) > self.limit:
            raise ValueError("Dataset catalog page exceeds its requested limit")
        if self.has_more != (self.offset + len(self.items) < self.total):
            raise ValueError("Dataset catalog pagination is inconsistent")
        if not self.persistence_enabled and (self.items or self.total):
            raise ValueError("Disabled persistence cannot expose stored datasets")
        return self


class PersistedEvaluationDatasetDetail(PersistedEvaluationDatasetMetadata):
    cases: list[ImportedEvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_count(self) -> "PersistedEvaluationDatasetDetail":
        if len(self.cases) != self.case_count:
            raise ValueError("Persisted case evidence does not match metadata")
        return self


class PersistEvaluationDatasetRequest(StrictModel):
    namespace: CacheNamespace | None = None
    dataset: object
    retention_days: int | None = Field(default=None, ge=1, le=3_650)


class DeletePersistedEvaluationDatasetResponse(StrictModel):
    deleted: Literal[True]
    dataset_id: UUID
    namespace: CacheNamespace
