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
    if len(location) < 2 or location[0] != "cases" or not isinstance(location[1], int):
        return None, None
    case_index = location[1]
    if not isinstance(raw, dict):
        return None, case_index
    cases = raw.get("cases")
    if not isinstance(cases, list) or case_index >= len(cases):
        return None, case_index
    case = cases[case_index]
    if not isinstance(case, dict):
        return None, case_index
    case_id = case.get("case_id")
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
    raw_location = error.get("loc")
    location = (
        tuple(part for part in raw_location if isinstance(part, (int, str)))
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

    raw_cases = raw.get("cases")
    if isinstance(raw_cases, list) and len(raw_cases) > max_cases:
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
            _pydantic_issue(raw, cast(dict[str, object], error))
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

    summary = {
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
