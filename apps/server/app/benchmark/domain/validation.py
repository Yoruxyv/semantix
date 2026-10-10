"""Validate decoded imported datasets without providers or storage access.

Schema validation, ordered-reference checks and configured import/workload bounds
precede domain conversion. Structured issues use fixed messages and selected
location context instead of raw Pydantic input/error messages. Digests use
``app.benchmark.domain.datasets``; previews report estimates, not executed work.
"""

import json
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError

from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    EvaluationDatasetPreview,
    EvaluationDatasetPreviewLimits,
    EvaluationDatasetValidationIssue,
    EvaluationDatasetWarning,
    ImportedEvaluationDatasetDefinition,
)
from app.benchmark.domain.datasets import dataset_semantics_digest
from app.benchmark.domain.models import BenchmarkCase, BenchmarkDataset
from app.core.exceptions import AppError, PublicErrorIssue

UNCATEGORIZED = "uncategorized"
MAX_VALIDATION_ISSUES = 100


class EvaluationDatasetValidationError(AppError):
    """Expose a stable 422 import error with at most 100 public issues.

    The public slice bounds the response, not internal issue collection. Issue
    pointers and permitted case IDs still contain caller-chosen identifiers.
    """

    status_code = 422
    error_code = "evaluation_dataset_invalid"
    public_detail = "The imported evaluation dataset is invalid."

    def __init__(
        self,
        issues: list[EvaluationDatasetValidationIssue],
    ) -> None:
        public_issues = [
            cast(
                PublicErrorIssue,
                issue.model_dump(exclude_none=True),
            )
            for issue in issues[:MAX_VALIDATION_ISSUES]
        ]
        super().__init__(issues=public_issues)


@dataclass(frozen=True, slots=True)
class ValidatedImportedDataset:
    """Pair ordered converted cases with the provider-free validation preview."""

    dataset: BenchmarkDataset
    preview: EvaluationDatasetPreview


def _json_pointer(location: tuple[int | str, ...]) -> str:
    if not location:
        return "/"
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in location]
    return "/" + "/".join(parts)


def _safe_case_context(
    raw: object,
    location: tuple[int | str, ...],
) -> tuple[str | None, int | None]:
    """Select a zero-based index and bounded identifier-like case ID for an issue.

    Return no prompt or note contents; character filtering does not guarantee
    that a caller-chosen identifier contains no private information.
    """
    if len(location) < 2 or location[0] != "cases" or not isinstance(location[1], int):
        return None, None
    case_index = location[1]
    if not isinstance(raw, dict):
        return None, case_index
    cases = cast("dict[object, object]", raw).get("cases")
    if not isinstance(cases, list) or case_index >= len(cast("list[object]", cases)):
        return None, case_index
    case = cast("list[object]", cases)[case_index]
    if not isinstance(case, dict):
        return None, case_index
    case_id = cast("dict[object, object]", case).get("case_id")
    if (
        isinstance(case_id, str)
        and 0 < len(case_id) <= 100
        and all(character.isalnum() or character in "._:-" for character in case_id)
    ):
        return case_id, case_index
    return None, case_index


def _pydantic_issue(
    raw: object,
    error: dict[str, object],
) -> EvaluationDatasetValidationIssue:
    """Map error type/location to fixed issue text without copying raw input.

    JSON pointers escape path components; unknown-field names can remain in the
    pointer. This deliberately avoids Pydantic's input and free-form message.
    """
    raw_location = error.get("loc")
    location = (
        tuple(
            part
            for part in cast("tuple[object, ...]", raw_location)
            if isinstance(part, (int, str))
        )
        if isinstance(raw_location, tuple)
        else ()
    )
    error_type = error.get("type")
    pointer = _json_pointer(location)

    if pointer == "/schema_version" and error_type == "literal_error":
        code = "unsupported_schema_version"
        detail = "Only evaluation dataset schema_version 1 is supported."
    elif error_type == "missing":
        code = "required_field"
        detail = "A required dataset field is missing."
    elif error_type == "extra_forbidden":
        code = "unknown_field"
        detail = "The dataset contains an unsupported field."
    elif error_type == "string_too_short":
        code = "empty_string"
        detail = "This dataset string must not be empty."
    elif error_type == "string_too_long":
        code = "value_too_long"
        detail = "This dataset string exceeds its allowed length."
    elif error_type == "string_pattern_mismatch":
        code = "invalid_identifier"
        detail = "This identifier contains unsupported characters."
    elif error_type == "too_short" and pointer == "/cases":
        code = "cases_required"
        detail = "The dataset must contain at least one case."
    else:
        code = "invalid_value"
        detail = "This dataset value has the wrong type or value."

    case_id, case_index = _safe_case_context(raw, location)
    return EvaluationDatasetValidationIssue(
        code=code,
        detail=detail,
        pointer=pointer,
        case_id=case_id,
        case_index=case_index,
    )


def _decoded_size(raw: object) -> int:
    """Measure compact sorted-key decoded JSON in UTF-8, including metadata.

    This is canonical decoded size, not wire bytes or upload length. JSON
    serialization TypeError/ValueError become invalid_document issues; UTF-8
    encoding occurs afterward, outside that exception mapping.
    """
    try:
        canonical = json.dumps(
            raw,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise EvaluationDatasetValidationError(
            [
                EvaluationDatasetValidationIssue(
                    code="invalid_document",
                    detail="The dataset must be a JSON object.",
                    pointer="/",
                )
            ]
        ) from exc
    return len(canonical.encode("utf-8"))


def _reference_issues(
    definition: ImportedEvaluationDatasetDefinition,
) -> list[EvaluationDatasetValidationIssue]:
    """Reject duplicate IDs and contradictory, self, ambiguous or forward references.

    A declared expected-match ID must identify a unique earlier case and appear
    only on an expected hit. An expected hit without a reference is allowed and
    becomes a preview warning instead.
    """
    issues: list[EvaluationDatasetValidationIssue] = []
    positions: dict[str, int] = {}
    duplicate_ids: set[str] = set()
    for index, case in enumerate(definition.cases):
        if case.case_id in positions:
            duplicate_ids.add(case.case_id)
            issues.append(
                EvaluationDatasetValidationIssue(
                    code="duplicate_case_id",
                    detail="Case IDs must be unique within one dataset.",
                    pointer=f"/cases/{index}/case_id",
                    case_id=case.case_id,
                    case_index=index,
                )
            )
        else:
            positions[case.case_id] = index

    for index, case in enumerate(definition.cases):
        reference = case.expected_match_case_id
        if reference is None:
            continue
        pointer = f"/cases/{index}/expected_match_case_id"
        if not case.expected_cache_hit:
            issues.append(
                EvaluationDatasetValidationIssue(
                    code="contradictory_expected_match",
                    detail="Expected misses cannot identify an expected match.",
                    pointer=pointer,
                    case_id=case.case_id,
                    case_index=index,
                )
            )
            continue
        if reference == case.case_id:
            code = "self_expected_match"
            detail = "A case cannot reference itself as its expected match."
        elif reference in duplicate_ids:
            code = "ambiguous_expected_match"
            detail = "The expected match references a duplicated case ID."
        elif reference not in positions:
            code = "missing_expected_match"
            detail = "The expected match does not exist in this dataset."
        elif positions[reference] >= index:
            code = "forward_expected_match"
            detail = "The expected match must reference an earlier case."
        else:
            continue
        issues.append(
            EvaluationDatasetValidationIssue(
                code=code,
                detail=detail,
                pointer=pointer,
                case_id=case.case_id,
                case_index=index,
            )
        )
    return issues


def validate_imported_dataset(
    raw: object,
    *,
    repetitions: int,
    threshold_count: int,
    max_cases: int,
    max_decoded_bytes: int,
    max_workload_queries: int,
) -> ValidatedImportedDataset:
    """Validate an import and describe its proposed workload without executing it.

    Measure canonical decoded bytes before strict schema-version-1 validation;
    reject unknown fields, invalid structure, excessive case count and invalid
    ordered references. Bound query work as cases * repetitions. Threshold count
    affects projection-work estimates, not that query cap. Repetition/threshold
    count ranges are expected to have been checked by the calling request schema.

    Convert validated cases in order, assigning missing categories to
    uncategorized. Missing categories and expected hits without references produce
    warnings, not rejection. The semantic digest excludes display metadata and
    notes; its prefix supplies the custom ID. Preview provider calls are zero;
    maximum possible calls and query/projection counts describe proposed work.

    Args:
        raw: Decoded untrusted JSON definition, including display metadata.
        repetitions: Proposed repetition count for the query-work bound.
        threshold_count: Proposed threshold-row count for projection-work estimates.
        max_cases: Configured maximum number of imported cases.
        max_decoded_bytes: Configured canonical decoded UTF-8 size limit.
        max_workload_queries: Configured maximum cases-times-repetitions work.

    Returns:
        Converted dataset and a preview of identity, counts, limits and warnings.

    Raises:
        EvaluationDatasetValidationError: A mapped serialization, schema,
            reference, size, case-count or query-work validation check fails.
        UnicodeEncodeError: Canonical JSON cannot be represented as UTF-8.
    """
    decoded_bytes = _decoded_size(raw)
    if decoded_bytes > max_decoded_bytes:
        raise EvaluationDatasetValidationError(
            [
                EvaluationDatasetValidationIssue(
                    code="decoded_size_exceeded",
                    detail=(
                        "The decoded dataset exceeds the configured "
                        "session-import size limit."
                    ),
                    pointer="/",
                )
            ]
        )

    if not isinstance(raw, dict):
        raise EvaluationDatasetValidationError(
            [
                EvaluationDatasetValidationIssue(
                    code="invalid_document",
                    detail="The dataset must be a JSON object.",
                    pointer="/",
                )
            ]
        )

    raw_cases = cast("dict[object, object]", raw).get("cases")
    if isinstance(raw_cases, list) and len(cast("list[object]", raw_cases)) > max_cases:
        raise EvaluationDatasetValidationError(
            [
                EvaluationDatasetValidationIssue(
                    code="case_limit_exceeded",
                    detail="The dataset contains too many cases.",
                    pointer="/cases",
                )
            ]
        )

    try:
        definition = ImportedEvaluationDatasetDefinition.model_validate(raw)
    except ValidationError as exc:
        issues = [
            _pydantic_issue(cast(object, raw), cast(dict[str, object], error))
            for error in exc.errors(include_url=False)
        ]
        raise EvaluationDatasetValidationError(issues) from exc

    issues = _reference_issues(definition)
    if issues:
        raise EvaluationDatasetValidationError(issues)

    query_executions = len(definition.cases) * repetitions
    if query_executions > max_workload_queries:
        raise EvaluationDatasetValidationError(
            [
                EvaluationDatasetValidationIssue(
                    code="workload_limit_exceeded",
                    detail=(
                        "Cases multiplied by repetitions exceed the configured "
                        "evaluation workload limit."
                    ),
                    pointer="/cases",
                )
            ]
        )

    cases = tuple(
        BenchmarkCase(
            case_id=case.case_id,
            category=case.category or UNCATEGORIZED,
            prompt=case.prompt,
            expected_cache_hit=case.expected_cache_hit,
            expected_match_case_id=case.expected_match_case_id,
            note=case.note,
        )
        for case in definition.cases
    )
    digest = dataset_semantics_digest(cases)
    dataset_id = f"custom:{digest[:16]}"
    expected_hits = sum(case.expected_cache_hit for case in cases)
    categories = list(dict.fromkeys(case.category for case in cases))
    warnings: list[EvaluationDatasetWarning] = []
    uncategorized_count = sum(case.category is None for case in definition.cases)
    if uncategorized_count:
        warnings.append(
            EvaluationDatasetWarning(
                code="uncategorized_cases",
                detail="Cases without a category are grouped as uncategorized.",
                count=uncategorized_count,
            )
        )
    unreferenced_hits = sum(
        case.expected_cache_hit and case.expected_match_case_id is None
        for case in definition.cases
    )
    if unreferenced_hits:
        warnings.append(
            EvaluationDatasetWarning(
                code="expected_match_unspecified",
                detail=(
                    "Expected hits without a match reference are evaluated "
                    "as hit-or-miss decisions only."
                ),
                count=unreferenced_hits,
            )
        )

    summary: dict[str, object] = {
        "dataset_id": dataset_id,
        "dataset_source": "inline",
        "schema_version": definition.schema_version,
        "version": str(definition.schema_version),
        "digest": digest,
        "name": definition.name,
        "description": (
            definition.description or "Session-local imported evaluation dataset."
        ),
        "query_count": len(cases),
        "expected_hits": expected_hits,
        "expected_misses": len(cases) - expected_hits,
        "categories": categories,
    }
    resolved_dataset = BenchmarkDataset(
        summary=BenchmarkDatasetSummary.model_validate(summary),
        cases=cases,
    )
    preview = EvaluationDatasetPreview(
        schema_version=definition.schema_version,
        dataset_id=dataset_id,
        digest=digest,
        name=definition.name,
        description=definition.description,
        case_count=len(cases),
        expected_hits=expected_hits,
        expected_misses=len(cases) - expected_hits,
        categories=categories,
        decoded_bytes=decoded_bytes,
        warnings=warnings,
        query_executions=query_executions,
        threshold_projection_evaluations=query_executions * threshold_count,
        maximum_provider_calls=query_executions,
        provider_calls_made=0,
        limits=EvaluationDatasetPreviewLimits(
            max_cases=max_cases,
            max_decoded_bytes=max_decoded_bytes,
            max_workload_queries=max_workload_queries,
        ),
    )
    return ValidatedImportedDataset(dataset=resolved_dataset, preview=preview)
