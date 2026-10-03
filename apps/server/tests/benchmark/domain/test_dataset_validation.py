import json
from collections.abc import Callable

import pytest

from app.benchmark.domain.validation import (
    EvaluationDatasetValidationError,
    ValidatedImportedDataset,
    validate_imported_dataset,
)


def dataset_definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Support cache decisions",
        "description": "Synthetic prompts for contract tests.",
        "cases": [
            {
                "case_id": "seed",
                "prompt": "How do I reset my password?",
                "expected_cache_hit": False,
                "category": "account",
            },
            {
                "case_id": "paraphrase",
                "prompt": "Help me change a forgotten password.",
                "expected_cache_hit": True,
                "expected_match_case_id": "seed",
                "category": "account",
                "note": "Expected to reuse the seed response.",
            },
        ],
    }


def validate(
    raw: object,
    *,
    max_cases: int = 50,
    max_decoded_bytes: int = 49_152,
    max_workload_queries: int = 250,
    repetitions: int = 1,
) -> ValidatedImportedDataset:
    return validate_imported_dataset(
        raw,
        repetitions=repetitions,
        threshold_count=3,
        max_cases=max_cases,
        max_decoded_bytes=max_decoded_bytes,
        max_workload_queries=max_workload_queries,
    )


def issue_codes(error: EvaluationDatasetValidationError) -> set[str]:
    assert error.issues is not None
    return {issue["code"] for issue in error.issues}


def test_valid_dataset_returns_normalized_preview_and_transient_dataset() -> None:
    validated = validate(dataset_definition())

    assert validated.preview.schema_version == 1
    assert validated.preview.dataset_id.startswith("custom:")
    assert validated.preview.case_count == 2
    assert validated.preview.expected_hits == 1
    assert validated.preview.expected_misses == 1
    assert validated.preview.query_executions == 2
    assert validated.preview.threshold_projection_evaluations == 6
    assert validated.preview.maximum_provider_calls == 2
    assert validated.preview.provider_calls_made == 0
    assert validated.dataset.summary.dataset_source == "inline"
    assert validated.dataset.summary.schema_version == 1
    assert validated.dataset.summary.digest == validated.preview.digest
    assert validated.dataset.cases[1].expected_match_case_id == "seed"


def test_dataset_document_must_be_a_json_object() -> None:
    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate([])

    assert issue_codes(caught.value) == {"invalid_document"}


def test_optional_categories_are_normalized_with_bounded_warnings() -> None:
    definition = dataset_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    second = cases[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    first.pop("category")
    second.pop("expected_match_case_id")

    validated = validate(definition)

    assert validated.preview.categories == ["uncategorized", "account"]
    assert {warning.code for warning in validated.preview.warnings} == {
        "uncategorized_cases",
        "expected_match_unspecified",
    }


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda value: value.update(schema_version=2), "unsupported_schema_version"),
        (lambda value: value.pop("name"), "required_field"),
        (lambda value: value.update(unknown=True), "unknown_field"),
        (lambda value: value.update(name=""), "empty_string"),
    ],
)
def test_schema_errors_have_stable_codes_and_pointers(
    mutation: Callable[[dict[str, object]], object],
    expected_code: str,
) -> None:
    definition = dataset_definition()
    mutation(definition)

    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate(definition)

    assert expected_code in issue_codes(caught.value)
    assert caught.value.issues
    assert all(issue["pointer"].startswith("/") for issue in caught.value.issues)


def test_duplicate_ids_and_invalid_references_are_rejected_together() -> None:
    definition = dataset_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    second = cases[1]
    assert isinstance(second, dict)
    second["case_id"] = "seed"
    second["expected_match_case_id"] = "missing"

    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate(definition)

    assert issue_codes(caught.value) == {
        "duplicate_case_id",
        "missing_expected_match",
    }


@pytest.mark.parametrize(
    ("reference", "expected_hit", "expected_code"),
    [
        ("paraphrase", True, "self_expected_match"),
        ("seed", False, "contradictory_expected_match"),
        ("later", True, "forward_expected_match"),
    ],
)
def test_expected_match_must_be_earlier_and_consistent(
    reference: str,
    expected_hit: bool,
    expected_code: str,
) -> None:
    definition = dataset_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    second = cases[1]
    assert isinstance(second, dict)
    second["expected_match_case_id"] = reference
    second["expected_cache_hit"] = expected_hit
    if reference == "later":
        cases.append(
            {
                "case_id": "later",
                "prompt": "Later synthetic case",
                "expected_cache_hit": False,
            }
        )

    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate(definition)

    assert expected_code in issue_codes(caught.value)


def test_case_decoded_size_and_workload_limits_are_independent() -> None:
    definition = dataset_definition()

    with pytest.raises(EvaluationDatasetValidationError) as too_many:
        validate(definition, max_cases=1)
    assert issue_codes(too_many.value) == {"case_limit_exceeded"}

    with pytest.raises(EvaluationDatasetValidationError) as too_large:
        validate(definition, max_decoded_bytes=100)
    assert issue_codes(too_large.value) == {"decoded_size_exceeded"}

    with pytest.raises(EvaluationDatasetValidationError) as too_much_work:
        validate(definition, max_workload_queries=3, repetitions=2)
    assert issue_codes(too_much_work.value) == {"workload_limit_exceeded"}


def test_exact_decoded_size_boundary_is_accepted() -> None:
    definition = dataset_definition()
    exact_size = len(
        json.dumps(
            definition,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )

    assert validate(definition, max_decoded_bytes=exact_size).preview.decoded_bytes == (
        exact_size
    )
    assert validate(definition, max_cases=2).preview.case_count == 2


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("prompt", "", "empty_string"),
        ("prompt", "x" * 2_001, "value_too_long"),
        ("category", "x" * 101, "value_too_long"),
        ("note", "x" * 501, "value_too_long"),
    ],
)
def test_case_text_boundaries_are_server_authoritative(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    definition = dataset_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    assert isinstance(first, dict)
    first[field] = value

    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate(definition)

    assert expected_code in issue_codes(caught.value)


def test_validation_errors_do_not_echo_prompt_content() -> None:
    sensitive_prompt = "private-customer-reference-12345"
    definition = dataset_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    assert isinstance(first, dict)
    first["prompt"] = sensitive_prompt
    first["unexpected"] = True

    with pytest.raises(EvaluationDatasetValidationError) as caught:
        validate(definition)

    assert sensitive_prompt not in str(caught.value.issues)


def test_digest_tracks_ordered_execution_semantics_not_descriptive_metadata() -> None:
    original = validate(dataset_definition())
    renamed = dataset_definition()
    renamed["name"] = "A different display name"
    reordered = dataset_definition()
    cases = reordered["cases"]
    assert isinstance(cases, list)
    cases.reverse()
    first = cases[0]
    assert isinstance(first, dict)
    first.pop("expected_match_case_id", None)

    assert validate(renamed).preview.digest == original.preview.digest
    assert validate(reordered).preview.digest != original.preview.digest
