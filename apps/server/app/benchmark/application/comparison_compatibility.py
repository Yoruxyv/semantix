from app.benchmark.api.comparison_schemas import (
    EvaluationComparisonBlocker,
    EvaluationComparisonWarning,
)
from app.benchmark.api.history_schemas import EvaluationRunHistoryDetail


def comparison_blockers(
    baseline: EvaluationRunHistoryDetail,
    candidate: EvaluationRunHistoryDetail,
) -> list[EvaluationComparisonBlocker]:
    blockers: list[EvaluationComparisonBlocker] = []

    if baseline.namespace != candidate.namespace:
        blockers.append(
            EvaluationComparisonBlocker(
                code="namespace_mismatch",
                detail="Run namespaces differ; cross-namespace comparison is blocked.",
            )
        )
    if baseline.terminal_state != "completed":
        blockers.append(
            EvaluationComparisonBlocker(
                code="baseline_not_completed",
                detail="The baseline run did not complete successfully.",
            )
        )
    if candidate.terminal_state != "completed":
        blockers.append(
            EvaluationComparisonBlocker(
                code="candidate_not_completed",
                detail="The candidate run did not complete successfully.",
            )
        )

    baseline_dataset = baseline.dataset
    candidate_dataset = candidate.dataset
    if baseline_dataset.schema_version != candidate_dataset.schema_version:
        blockers.append(
            EvaluationComparisonBlocker(
                code="dataset_schema_mismatch",
                detail="Dataset schema versions differ.",
            )
        )
    if baseline_dataset.digest != candidate_dataset.digest:
        blockers.append(
            EvaluationComparisonBlocker(
                code="dataset_digest_mismatch",
                detail="Dataset content digests differ.",
            )
        )

    baseline_metadata = baseline.reproducibility
    candidate_metadata = candidate.reproducibility
    if (
        baseline_metadata.embedding_dimensions
        != candidate_metadata.embedding_dimensions
    ):
        blockers.append(
            EvaluationComparisonBlocker(
                code="embedding_dimensions_mismatch",
                detail="Embedding dimensions differ.",
            )
        )
    if (
        baseline_metadata.embedding_space_fingerprint
        != candidate_metadata.embedding_space_fingerprint
    ):
        blockers.append(
            EvaluationComparisonBlocker(
                code="embedding_space_mismatch",
                detail="Embedding-space fingerprints differ.",
            )
        )
    if baseline_metadata.normalization_mode != candidate_metadata.normalization_mode:
        blockers.append(
            EvaluationComparisonBlocker(
                code="normalization_mode_mismatch",
                detail="Prompt normalization modes differ.",
            )
        )
    if (
        baseline_metadata.normalization_fingerprint
        != candidate_metadata.normalization_fingerprint
    ):
        blockers.append(
            EvaluationComparisonBlocker(
                code="normalization_fingerprint_mismatch",
                detail="Prompt normalization fingerprints differ.",
            )
        )
    if baseline_metadata.repetitions != candidate_metadata.repetitions:
        blockers.append(
            EvaluationComparisonBlocker(
                code="repetitions_mismatch",
                detail="Evaluation repetition counts differ.",
            )
        )
    if (
        baseline_metadata.reset_cache_before_run
        != candidate_metadata.reset_cache_before_run
    ):
        blockers.append(
            EvaluationComparisonBlocker(
                code="reset_policy_mismatch",
                detail="Benchmark cache reset policies differ.",
            )
        )
    if (
        baseline_metadata.comparison_contract_version
        != candidate_metadata.comparison_contract_version
    ):
        blockers.append(
            EvaluationComparisonBlocker(
                code="comparison_contract_version_mismatch",
                detail="Comparison contract versions differ.",
            )
        )
    if baseline.threshold_evaluation_mode != candidate.threshold_evaluation_mode:
        blockers.append(
            EvaluationComparisonBlocker(
                code="threshold_evaluation_mode_mismatch",
                detail="Threshold projection contracts differ.",
            )
        )

    return blockers


def comparison_warnings(
    baseline: EvaluationRunHistoryDetail,
    candidate: EvaluationRunHistoryDetail,
) -> list[EvaluationComparisonWarning]:
    warnings: list[EvaluationComparisonWarning] = []
    baseline_metadata = baseline.reproducibility
    candidate_metadata = candidate.reproducibility

    if (
        baseline_metadata.generation_provider_category
        != candidate_metadata.generation_provider_category
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="generation_provider_changed",
                detail="Generation provider categories differ.",
            )
        )
    if (
        baseline_metadata.generation_configuration_fingerprint
        != candidate_metadata.generation_configuration_fingerprint
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="generation_configuration_changed",
                detail="Safe generation configuration fingerprints differ.",
            )
        )
    if baseline_metadata.application_version != candidate_metadata.application_version:
        warnings.append(
            EvaluationComparisonWarning(
                code="application_version_changed",
                detail="Application versions differ.",
            )
        )
    if (
        baseline_metadata.estimated_cost_per_request_usd
        != candidate_metadata.estimated_cost_per_request_usd
        or baseline_metadata.estimated_cost_per_1k_tokens_usd
        != candidate_metadata.estimated_cost_per_1k_tokens_usd
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="cost_assumptions_changed",
                detail="Estimated provider cost assumptions differ.",
            )
        )
    if (
        baseline_metadata.evaluation_timeout_seconds
        != candidate_metadata.evaluation_timeout_seconds
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="evaluation_timeout_changed",
                detail="Evaluation timeout settings differ.",
            )
        )
    if (
        baseline_metadata.evaluation_thresholds
        != candidate_metadata.evaluation_thresholds
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="projection_list_changed",
                detail=(
                    "Threshold projection lists differ; only shared threshold "
                    "projections are compared."
                ),
            )
        )

    baseline_dataset = baseline.dataset
    candidate_dataset = candidate.dataset
    if (
        baseline_dataset.dataset_source == "persisted"
        and candidate_dataset.dataset_source == "persisted"
        and baseline_dataset.digest == candidate_dataset.digest
        and baseline_dataset.schema_version == candidate_dataset.schema_version
        and (
            baseline_dataset.dataset_id != candidate_dataset.dataset_id
            or baseline_dataset.version != candidate_dataset.version
        )
    ):
        warnings.append(
            EvaluationComparisonWarning(
                code="persisted_dataset_identity_changed",
                detail=(
                    "Persisted dataset identity or version differs even though "
                    "the retained content digest matches."
                ),
            )
        )

    return warnings
