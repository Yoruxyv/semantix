"""Build allowlisted configuration evidence without contacting providers.

Provider/normalization fingerprints are supplied by runtime composition. Dataset
digests describe the semantic subset in ``app.benchmark.domain.datasets``.
"""

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
    """Build the safe, deterministic metadata describing an evaluation run.

    Hash compact sorted-key JSON (default ASCII escaping) as UTF-8 with SHA-256.
    The allowlist includes dataset identity/source/version/digest, provider categories
    and fingerprints, embedding dimensions, normalization identity, measured and
    evaluation thresholds, repetitions/reset, cost assumptions, timeout and comparison
    contract version 1. Run IDs and timestamps do not enter this configuration hash.
    Raw prompts/responses, model names, URLs and credentials are not copied into it;
    dataset digests are still derived from prompt semantics and are not encryption.
    Evidence describes supplied configuration, not guaranteed deterministic provider
    output or identical outcomes on a future run.

    Args:
        request: Validated workload/threshold settings and cost assumptions.
        dataset: Resolved summary with dataset identity and semantic digest.
        runtime: Allowlisted runtime identity and precomputed fingerprints.

    Returns:
        Validated metadata with the configuration fingerprint.
    """

    safe_configuration: dict[str, object] = {
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
    return BenchmarkReproducibilityMetadata.model_validate(
        {
            **safe_configuration,
            "configuration_fingerprint": hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest(),
        }
    )
