from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.api.schemas import StrictModel
from app.benchmark.api.common_schemas import (
    MAX_BENCHMARK_REPETITIONS,
    MAX_EVALUATION_THRESHOLDS,
    SHA256_PATTERN,
    NormalizationMode,
    ProviderCategory,
)
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration
from app.core.config import CacheBackendName
from app.observability.metrics import MetricsSnapshot


class MetricsResponse(StrictModel):
    observed_at: datetime
    uptime_seconds: float = Field(ge=0)
    request_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    cache_misses: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    in_flight_coalesced_requests: int = Field(ge=0)
    average_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    latency_sample_size: int = Field(ge=0)
    cache_size: int = Field(ge=0)
    evictions: int = Field(ge=0)
    expirations: int = Field(ge=0)

    @classmethod
    def from_snapshot(cls, snapshot: MetricsSnapshot) -> "MetricsResponse":
        return cls(**asdict(snapshot))

    @model_validator(mode="after")
    def validate_latency_state(self) -> "MetricsResponse":
        has_latency = (
            self.average_latency_ms is not None and self.p95_latency_ms is not None
        )
        if has_latency != (self.latency_sample_size > 0):
            raise ValueError("Latency metrics and sample size must agree")
        if self.error_count > self.request_count:
            raise ValueError("error_count cannot exceed request_count")
        return self


class RuntimeDiagnosticsResponse(StrictModel):
    observed_at: datetime
    process_scope: Literal["single_backend_process"]
    application_version: str = Field(min_length=1, max_length=50)
    embedding_provider_category: ProviderCategory
    generation_provider_category: ProviderCategory
    embedding_dimensions: int = Field(gt=0)
    embedding_space_fingerprint: str = Field(pattern=SHA256_PATTERN)
    generation_configuration_fingerprint: str = Field(pattern=SHA256_PATTERN)
    cache_backend: CacheBackendName
    cache_readiness: Literal["ready", "unavailable"]
    normalization_mode: NormalizationMode
    normalization_algorithm_version: Literal[
        "identity-v1",
        "symspell-compound-v1",
    ]
    normalization_fingerprint: str = Field(pattern=SHA256_PATTERN)
    evaluation_timeout_seconds: float = Field(gt=0, le=3_600)
    evaluation_max_cases: int = Field(ge=1)
    evaluation_max_repetitions: int = Field(ge=1)
    evaluation_max_thresholds: int = Field(ge=2)
    evaluation_max_request_bytes: int = Field(ge=1_024)
    evaluation_dataset_persistence_enabled: bool
    evaluation_history_persistence_enabled: bool

    @classmethod
    def from_runtime(
        cls,
        runtime: BenchmarkRuntimeConfiguration,
        *,
        cache_backend: CacheBackendName,
        cache_readiness: Literal["ready", "unavailable"],
        max_request_body_bytes: int,
    ) -> "RuntimeDiagnosticsResponse":
        return cls(
            observed_at=datetime.now(UTC),
            process_scope="single_backend_process",
            application_version=runtime.application_version,
            embedding_provider_category=runtime.embedding_provider_category,
            generation_provider_category=runtime.generation_provider_category,
            embedding_dimensions=runtime.embedding_dimensions,
            embedding_space_fingerprint=runtime.embedding_space_fingerprint,
            generation_configuration_fingerprint=(
                runtime.generation_configuration_fingerprint
            ),
            cache_backend=cache_backend,
            cache_readiness=cache_readiness,
            normalization_mode=runtime.normalization_mode,
            normalization_algorithm_version=(
                "symspell-compound-v1"
                if runtime.normalization_mode == "typo_correction"
                else "identity-v1"
            ),
            normalization_fingerprint=runtime.normalization_fingerprint,
            evaluation_timeout_seconds=runtime.evaluation_timeout_seconds,
            evaluation_max_cases=runtime.evaluation_dataset_max_cases,
            evaluation_max_repetitions=MAX_BENCHMARK_REPETITIONS,
            evaluation_max_thresholds=MAX_EVALUATION_THRESHOLDS,
            evaluation_max_request_bytes=max_request_body_bytes,
            evaluation_dataset_persistence_enabled=(
                runtime.evaluation_dataset_storage == "postgres"
            ),
            evaluation_history_persistence_enabled=(
                runtime.evaluation_run_history_storage == "postgres"
            ),
        )
