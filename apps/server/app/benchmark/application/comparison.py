"""Coordinate compatibility and arithmetic over retained historical aggregates.

``app.benchmark.application.comparison_compatibility`` owns blockers/warnings;
``app.benchmark.application.comparison_deltas`` owns subtraction and shared-cutoff
rows. No provider work, workload replay or live threshold mutation occurs here.
"""

from app.benchmark.api.comparison_schemas import (
    EvaluationComparisonCompatibility,
    EvaluationComparisonStatus,
    EvaluationRunComparisonResponse,
)
from app.benchmark.api.history_schemas import EvaluationRunHistoryDetail
from app.benchmark.application.comparison_compatibility import (
    comparison_blockers,
    comparison_warnings,
)
from app.benchmark.application.comparison_deltas import (
    metric_deltas,
    threshold_deltas,
)


def compare_evaluation_runs(
    baseline: EvaluationRunHistoryDetail,
    candidate: EvaluationRunHistoryDetail,
) -> EvaluationRunComparisonResponse:
    """Assess compatibility and calculate candidate-minus-baseline deltas.

    Blockers produce incompatible status and suppress metric/threshold deltas.
    Without blockers, warnings produce warning status; otherwise status is compatible.
    Warnings are still reported alongside blockers. Opaque configuration-fingerprint
    equality is reported separately and is not a scientific-equivalence gate. Case
    evidence is not retained, so aggregates cannot establish per-case equivalence or
    reproduce generated responses. This assessment uses the existing versioned contract.

    Args:
        baseline: Authorized retained reference detail.
        candidate: Authorized retained comparison detail; deltas subtract the baseline
            from this candidate.

    Returns:
        Both historical details, compatibility, and deltas permitted by the blockers.
    """

    incompatibilities = comparison_blockers(baseline, candidate)
    warnings = comparison_warnings(baseline, candidate)

    status: EvaluationComparisonStatus
    if incompatibilities:
        status = "incompatible"
    elif warnings:
        status = "warning"
    else:
        status = "compatible"

    can_compare = not incompatibilities
    compatibility = EvaluationComparisonCompatibility(
        status=status,
        can_compare=can_compare,
        incompatibilities=incompatibilities,
        warnings=warnings,
        case_evidence="not_retained",
        opaque_configuration_fingerprint_matches=(
            baseline.reproducibility.configuration_fingerprint
            == candidate.reproducibility.configuration_fingerprint
        ),
    )

    return EvaluationRunComparisonResponse(
        baseline=baseline,
        candidate=candidate,
        compatibility=compatibility,
        metric_deltas=metric_deltas(baseline, candidate) if can_compare else None,
        threshold_deltas=threshold_deltas(baseline, candidate) if can_compare else [],
    )
