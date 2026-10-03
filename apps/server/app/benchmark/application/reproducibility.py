import hashlib
import json

from app.benchmark.api.common_schemas import (
    BenchmarkDatasetSummary,
    BenchmarkReproducibilityMetadata,
)
from app.benchmark.api.run_schemas import EvaluationRunOptions
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration


def build_reproducibility_metadata(
    request: EvaluationRunOptions,
    dataset: BenchmarkDatasetSummary,
    runtime: BenchmarkRuntimeConfiguration,
) -> BenchmarkReproducibilityMetadata:
    """Build the safe, deterministic metadata describing an evaluation run."""

    safe_configuration = {
        "application_version": runtime.application_version,
        "dataset_id": dataset.dataset_id,
        "dataset_source": dataset.dataset_source,
        "dataset_schema_version": dataset.schema_version,
        "dataset_version": dataset.version,
        "dataset_digest": dataset.digest,
        "embedding_provider_category": runtime.embedding_provider_category,
        "generation_provider_category": runtime.generation_provider_category,
        "generation_configuration_fingerprint": (
            runtime.generation_configuration_fingerprint
        ),
        "comparison_contract_version": 1,
        "embedding_dimensions": runtime.embedding_dimensions,
        "embedding_space_fingerprint": runtime.embedding_space_fingerprint,
        "normalization_mode": runtime.normalization_mode,
        "normalization_fingerprint": runtime.normalization_fingerprint,
        "measured_threshold": request.threshold,
        "evaluation_thresholds": request.evaluation_thresholds,
        "repetitions": request.repetitions,
        "reset_cache_before_run": request.reset_cache_before_run,
        "estimated_cost_per_request_usd": request.estimated_cost_per_request_usd,
        "estimated_cost_per_1k_tokens_usd": request.estimated_cost_per_1k_tokens_usd,
        "evaluation_timeout_seconds": runtime.evaluation_timeout_seconds,
    }
    canonical = json.dumps(
        safe_configuration,
        separators=(",", ":"),
        sort_keys=True,
    )
    return BenchmarkReproducibilityMetadata(
        **safe_configuration,
        configuration_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
