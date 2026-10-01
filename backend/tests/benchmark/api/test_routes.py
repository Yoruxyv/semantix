import asyncio
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration
from app.benchmark.domain.protocols import EvaluationDatasetRepository
from app.core.config import Settings
from app.factory import create_app
from tests.benchmark.support import InMemoryEvaluationDatasetRepository
from tests.support import TEST_EMBEDDING_DIMENSIONS


class SameEmbeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return [1.0] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 1)


class Provider:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        return f"Generated answer for {prompt}"


class TimeoutThenProvider(Provider):
    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        if self.call_count == 1:
            await asyncio.sleep(60)
        return f"Generated answer for {prompt}"


def benchmark_service(
    provider: Provider,
    *,
    evaluation_timeout_seconds: float = 30,
    dataset_repository: EvaluationDatasetRepository | None = None,
    history_enabled: bool = False,
) -> BenchmarkService:
    return BenchmarkService(
        SameEmbeddings(),
        provider,
        max_cache_size=100,
        cache_ttl_seconds=60,
        prompt_normalizer=lambda prompt: prompt,
        runtime_configuration=BenchmarkRuntimeConfiguration(
            application_version="1.0.0",
            embedding_provider_category="mock",
            generation_provider_category="mock",
            embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
            embedding_space_fingerprint="1" * 64,
            generation_configuration_fingerprint="3" * 64,
            normalization_mode="identity",
            normalization_fingerprint="2" * 64,
            evaluation_timeout_seconds=evaluation_timeout_seconds,
            evaluation_dataset_storage=(
                "session" if dataset_repository is None else "postgres"
            ),
            evaluation_run_history_storage=(
                "postgres" if history_enabled else "disabled"
            ),
            evaluation_run_history_retention_days=30 if history_enabled else None,
            evaluation_run_history_max_per_namespace=100 if history_enabled else None,
            evaluation_run_history_cleanup_batch_size=10 if history_enabled else None,
        ),
        dataset_repository=dataset_repository,
    )


def inline_definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Inline route set",
        "cases": [
            {
                "case_id": "seed",
                "prompt": "Synthetic route seed",
                "expected_cache_hit": False,
            },
            {
                "case_id": "repeat",
                "prompt": "Synthetic route repeat",
                "expected_cache_hit": True,
                "expected_match_case_id": "seed",
            },
        ],
    }


def test_lists_controlled_datasets(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/v1/benchmarks/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_dataset_id"] == "quick"
    assert [dataset["dataset_id"] for dataset in payload["datasets"]] == [
        "quick",
        "extended",
    ]
    quick = payload["datasets"][0]
    assert quick["query_count"] == 8
    assert quick["version"] == "1.0.0"
    assert len(quick["digest"]) == 64
    assert quick["expected_hits"] + quick["expected_misses"] == 8
    assert {
        "exact_duplicate",
        "paraphrase",
        "unrelated",
        "typo",
        "negation",
        "different_intent",
    }.issubset(set(quick["categories"]))


def test_canonical_catalog_preserves_the_builtin_dataset_contract(
    settings: Settings,
) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        canonical = client.get("/api/v1/evaluations/datasets")
        legacy = client.get("/api/v1/benchmarks/datasets")

    assert canonical.status_code == legacy.status_code == 200
    assert canonical.json() == legacy.json()
    assert all(
        dataset["dataset_source"] == "builtin" and dataset["schema_version"] is None
        for dataset in canonical.json()["datasets"]
    )


def test_validates_inline_dataset_without_provider_calls(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(provider)
        response = client.post(
            "/api/v1/evaluations/datasets/validate",
            json={
                "dataset": inline_definition(),
                "repetitions": 2,
                "threshold_count": 3,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Inline route set"
    assert payload["case_count"] == 2
    assert payload["query_executions"] == 4
    assert payload["threshold_projection_evaluations"] == 12
    assert payload["maximum_provider_calls"] == 4
    assert payload["provider_calls_made"] == 0
    assert provider.call_count == 0


def test_persisted_catalog_crud_and_run_contracts(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()
    repository = InMemoryEvaluationDatasetRepository()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            provider,
            dataset_repository=repository,
            history_enabled=True,
        )
        created = client.post(
            "/api/v1/evaluations/datasets/persisted",
            json={
                "namespace": "default",
                "dataset": inline_definition(),
                "retention_days": 7,
            },
        )
        dataset_id = created.json()["dataset_id"]
        catalog = client.get("/api/v1/evaluations/datasets/persisted")
        detail = client.get(f"/api/v1/evaluations/datasets/persisted/{dataset_id}")

        assert provider.call_count == 0

        run = client.post(
            "/api/v1/evaluations/runs",
            json={
                "dataset_source": {
                    "kind": "persisted",
                    "dataset_id": dataset_id,
                    "namespace": "default",
                },
                "threshold": 0.9,
                "evaluation_thresholds": [0.8, 0.9],
                "allow_external_provider_calls": True,
            },
        )
        deleted = client.delete(
            f"/api/v1/evaluations/datasets/persisted/{dataset_id}",
            params={"namespace": "default"},
        )
        missing = client.get(f"/api/v1/evaluations/datasets/persisted/{dataset_id}")

    assert created.status_code == 201
    assert created.json()["namespace"] == "default"
    assert catalog.status_code == 200
    assert catalog.json()["storage_mode"] == "postgres"
    assert catalog.json()["items"][0]["dataset_id"] == dataset_id
    assert detail.status_code == 200
    assert [item["case_id"] for item in detail.json()["cases"]] == [
        "seed",
        "repeat",
    ]
    assert run.status_code == 200
    assert run.json()["dataset"]["dataset_source"] == "persisted"
    assert run.json()["history_retention"] == {"state": "not_retained"}
    assert provider.call_count == run.json()["metrics"]["provider_calls"] == 1
    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted": True,
        "dataset_id": dataset_id,
        "namespace": "default",
    }
    assert missing.status_code == 404
    assert missing.json()["error"] == "evaluation_dataset_not_found"


def test_session_catalog_fallback_is_explicit(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        catalog = client.get("/api/v1/evaluations/datasets/persisted")
        save = client.post(
            "/api/v1/evaluations/datasets/persisted",
            json={"namespace": "default", "dataset": inline_definition()},
        )

    assert catalog.status_code == 200
    assert catalog.json()["storage_mode"] == "session"
    assert catalog.json()["persistence_enabled"] is False
    assert catalog.json()["items"] == []
    assert save.status_code == 409
    assert save.json()["error"] == "evaluation_dataset_persistence_disabled"


def test_inline_validation_returns_safe_structured_issues(
    settings: Settings,
) -> None:
    definition = inline_definition()
    cases = definition["cases"]
    assert isinstance(cases, list)
    second = cases[1]
    assert isinstance(second, dict)
    second["case_id"] = "seed"

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/evaluations/datasets/validate",
            json={"dataset": definition},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": "evaluation_dataset_invalid",
        "detail": "The imported evaluation dataset is invalid.",
        "issues": [
            {
                "code": "duplicate_case_id",
                "detail": "Case IDs must be unique within one dataset.",
                "pointer": "/cases/1/case_id",
                "case_id": "seed",
                "case_index": 1,
            },
            {
                "code": "self_expected_match",
                "detail": "A case cannot reference itself as its expected match.",
                "pointer": "/cases/1/expected_match_case_id",
                "case_id": "seed",
                "case_index": 1,
            },
        ],
    }
    assert "Synthetic route" not in response.text


def test_runs_inline_dataset_through_canonical_contract(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(provider)
        response = client.post(
            "/api/v1/evaluations/runs",
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": inline_definition(),
                },
                "threshold": 0.9,
                "evaluation_thresholds": [0.8, 0.9, 0.95],
                "repetitions": 1,
                "reset_cache_before_run": True,
                "estimated_cost_per_request_usd": 0,
                "estimated_cost_per_1k_tokens_usd": 0,
                "allow_external_provider_calls": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["dataset_source"] == "inline"
    assert payload["dataset"]["schema_version"] == 1
    assert payload["dataset"]["dataset_id"].startswith("custom:")
    assert payload["reproducibility"]["dataset_source"] == "inline"
    assert payload["reproducibility"]["dataset_schema_version"] == 1
    assert payload["metrics"]["total_queries"] == 2
    assert payload["query_results"][1]["expected_match_case_id"] == "seed"
    assert provider.call_count == payload["metrics"]["provider_calls"] == 1


def test_history_enabled_builtin_requires_an_explicit_namespace_for_wildcard_principal(
    settings: Settings,
) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            Provider(),
            history_enabled=True,
        )
        missing_scope = client.post(
            "/api/v1/evaluations/runs",
            json={"allow_external_provider_calls": True},
        )
        scoped = client.post(
            "/api/v1/evaluations/runs",
            json={
                "history_namespace": "default",
                "allow_external_provider_calls": True,
            },
        )

    assert missing_scope.status_code == 403
    assert scoped.status_code == 200
    assert scoped.json()["history_retention"] == {"state": "not_retained"}


def test_inline_history_namespace_is_rejected_before_execution(
    settings: Settings,
) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            provider,
            history_enabled=True,
        )
        response = client.post(
            "/api/v1/evaluations/runs",
            json={
                "history_namespace": "default",
                "dataset_source": {
                    "kind": "inline",
                    "definition": inline_definition(),
                },
                "allow_external_provider_calls": True,
            },
        )
        allowed = client.post(
            "/api/v1/evaluations/runs",
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": inline_definition(),
                },
                "allow_external_provider_calls": True,
            },
        )

    assert response.status_code == 422
    assert allowed.status_code == 200
    assert allowed.json()["history_retention"] == {"state": "not_retained"}
    assert provider.call_count == allowed.json()["metrics"]["provider_calls"]


def test_inline_run_revalidates_instead_of_trusting_a_preview(
    settings: Settings,
) -> None:
    definition = inline_definition()
    app = create_app(settings)

    with TestClient(app) as client:
        preview = client.post(
            "/api/v1/evaluations/datasets/validate",
            json={"dataset": definition},
        )
        cases = definition["cases"]
        assert isinstance(cases, list)
        second = cases[1]
        assert isinstance(second, dict)
        second["expected_match_case_id"] = "missing"
        run = client.post(
            "/api/v1/evaluations/runs",
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": definition,
                },
                "allow_external_provider_calls": True,
            },
        )

    assert preview.status_code == 200
    assert run.status_code == 422
    assert run.json()["issues"][0]["code"] == "missing_expected_match"


def test_evaluation_import_obeys_global_body_limit_and_json_error_path(
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_request_body_bytes": 1_024})
    oversized = inline_definition()
    cases = oversized["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    assert isinstance(first, dict)
    first["prompt"] = "x" * 1_100

    with TestClient(create_app(limited)) as client:
        too_large = client.post(
            "/api/v1/evaluations/datasets/validate",
            json={"dataset": oversized},
        )
        malformed = client.post(
            "/api/v1/evaluations/datasets/validate",
            content=b'{"dataset":',
            headers={"Content-Type": "application/json"},
        )

    assert too_large.status_code == 413
    assert too_large.json()["error"] == "request_too_large"
    assert malformed.status_code == 422
    assert malformed.json()["error"] == "validation_error"


def test_runs_default_benchmark_end_to_end(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(provider)
        live_stats_before = client.get("/api/v1/cache/stats").json()
        runtime_before = app.state.runtime_metrics.snapshot(
            cache_size=live_stats_before["size"]
        )
        response = client.post(
            "/api/v1/benchmarks/run",
            json={
                "dataset_id": "quick",
                "threshold": 0.9,
                "evaluation_thresholds": [0.8, 0.9, 0.95],
                "repetitions": 2,
                "reset_cache_before_run": True,
                "estimated_cost_per_request_usd": 0.01,
                "estimated_cost_per_1k_tokens_usd": 0.002,
                "allow_external_provider_calls": True,
            },
        )
        live_stats_after = client.get("/api/v1/cache/stats").json()
        runtime_after = app.state.runtime_metrics.snapshot(
            cache_size=live_stats_after["size"]
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["dataset_id"] == "quick"
    assert payload["threshold"] == pytest.approx(0.9, rel=0.0, abs=1e-12)
    assert payload["metrics"]["total_queries"] == 16
    assert len(payload["query_results"]) == 16
    assert payload["threshold_evaluation_mode"] == "frozen_candidate_projection"
    assert len(payload["threshold_evaluations"]) == 3
    assert (
        sum(
            evaluation["result_kind"] == "measured"
            for evaluation in payload["threshold_evaluations"]
        )
        == 1
    )
    assert provider.call_count == payload["metrics"]["provider_calls"] == 2
    assert (
        payload["metrics"]["provider_calls"]
        + payload["metrics"]["provider_calls_avoided"]
        == 16
    )
    assert payload["metrics"]["true_positive_hits"] == 8
    assert payload["metrics"]["true_negative_misses"] == 2
    assert (
        payload["reproducibility"]["dataset_digest"] == (payload["dataset"]["digest"])
    )
    assert payload["reproducibility"]["measured_threshold"] == payload["threshold"]
    assert payload["reproducibility"]["evaluation_thresholds"] == [0.8, 0.9, 0.95]
    assert live_stats_after == live_stats_before
    for field in (
        "request_count",
        "error_count",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "in_flight_coalesced_requests",
        "latency_sample_size",
        "cache_size",
        "evictions",
        "expirations",
    ):
        assert getattr(runtime_after, field) == getattr(runtime_before, field)
    assert all("embedding" not in query for query in payload["query_results"])


def test_thresholds_are_bounded_unique_and_include_the_measured_value(
    settings: Settings,
) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        duplicate = client.post(
            "/api/v1/benchmarks/run",
            json={
                "threshold": 0.9,
                "evaluation_thresholds": [0.8, 0.8],
                "allow_external_provider_calls": True,
            },
        )
        too_many = client.post(
            "/api/v1/benchmarks/run",
            json={
                "threshold": 0.91,
                "evaluation_thresholds": [index / 100 for index in range(15)],
                "allow_external_provider_calls": True,
            },
        )

    assert duplicate.status_code == 422
    assert too_many.status_code == 422


def test_run_timeout_returns_a_structured_error_and_allows_a_later_run(
    settings: Settings,
) -> None:
    app = create_app(settings)
    provider = TimeoutThenProvider()

    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            provider,
            evaluation_timeout_seconds=0.1,
        )
        timed_out = client.post(
            "/api/v1/benchmarks/run",
            json={"allow_external_provider_calls": True},
        )
        recovered = client.post(
            "/api/v1/benchmarks/run",
            json={"allow_external_provider_calls": True},
        )

    assert timed_out.status_code == 504
    assert timed_out.json() == {
        "error": "evaluation_timeout",
        "detail": "The evaluation exceeded its configured wall-clock limit.",
    }
    assert recovered.status_code == 200
    assert recovered.json()["metrics"]["provider_calls"] == 1


def test_requires_explicit_external_provider_confirmation(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/benchmarks/run",
            json={
                "dataset_id": "quick",
                "threshold": 0.92,
                "repetitions": 1,
                "reset_cache_before_run": True,
            },
        )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
