import asyncio
from collections.abc import Sequence
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration
from app.core.config import Settings
from app.factory import create_app
from tests.benchmark.history_support import (
    InMemoryEvaluationRunHistoryRepository,
    make_history_record,
)
from tests.support import TEST_EMBEDDING_DIMENSIONS

VIEWER_TOKEN = "comparison-viewer-secret"


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return [1.0] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 1)


class Provider:
    async def generate(self, prompt: str) -> str:
        return f"response:{prompt}"


def service(
    repository: InMemoryEvaluationRunHistoryRepository | None,
) -> BenchmarkService:
    history_enabled = repository is not None
    return BenchmarkService(
        Embeddings(),
        Provider(),
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
            evaluation_timeout_seconds=30,
            evaluation_run_history_storage=(
                "postgres" if history_enabled else "disabled"
            ),
            evaluation_run_history_retention_days=30 if history_enabled else None,
            evaluation_run_history_max_per_namespace=100 if history_enabled else None,
            evaluation_run_history_cleanup_batch_size=10 if history_enabled else None,
        ),
        history_repository=repository,
    )


def viewer_settings() -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        auth_mode="token",
        auth_principals=[
            {
                "name": "comparison-viewer",
                "token_sha256": sha256(VIEWER_TOKEN.encode("utf-8")).hexdigest(),
                "role": "viewer",
                "namespaces": ["tenant-a"],
            }
        ],
    )


def viewer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {VIEWER_TOKEN}"}


def test_comparison_endpoint_returns_server_backed_aggregate_deltas(
    settings: Settings,
) -> None:
    app = create_app(settings)
    repository = InMemoryEvaluationRunHistoryRepository()

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        baseline = client.post(
            "/api/v1/evaluations/runs",
            json={
                "history_namespace": "tenant-history",
                "threshold": 0.80,
                "evaluation_thresholds": [0.80, 0.92],
                "allow_external_provider_calls": True,
            },
        )
        candidate = client.post(
            "/api/v1/evaluations/runs",
            json={
                "history_namespace": "tenant-history",
                "threshold": 0.92,
                "evaluation_thresholds": [0.80, 0.92],
                "allow_external_provider_calls": True,
            },
        )
        assert baseline.status_code == candidate.status_code == 200

        response = client.post(
            "/api/v1/evaluations/runs/compare",
            json={
                "baseline_run_id": baseline.json()["run_id"],
                "candidate_run_id": candidate.json()["run_id"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["baseline"]["run_id"] == baseline.json()["run_id"]
    assert payload["candidate"]["run_id"] == candidate.json()["run_id"]
    assert payload["compatibility"] == {
        "status": "compatible",
        "can_compare": True,
        "incompatibilities": [],
        "warnings": [],
        "case_evidence": "not_retained",
        "opaque_configuration_fingerprint_matches": False,
    }
    assert payload["metric_deltas"]["measured_threshold"] == pytest.approx(0.12)
    assert len(payload["threshold_deltas"]) == 2
    assert "query_results" not in response.text


def test_comparison_endpoint_blocks_cross_namespace_deltas_for_global_viewer(
    settings: Settings,
) -> None:
    app = create_app(settings)
    repository = InMemoryEvaluationRunHistoryRepository()
    baseline = make_history_record(
        run_id=f"{1:032x}",
        namespace="tenant-a",
    )
    candidate = make_history_record(
        run_id=f"{2:032x}",
        namespace="tenant-b",
    )
    asyncio.run(repository.persist_terminal_run(baseline))
    asyncio.run(repository.persist_terminal_run(candidate))

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        response = client.post(
            "/api/v1/evaluations/runs/compare",
            json={
                "baseline_run_id": baseline.context.run_id,
                "candidate_run_id": candidate.context.run_id,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compatibility"]["status"] == "incompatible"
    assert payload["compatibility"]["can_compare"] is False
    assert [
        issue["code"] for issue in payload["compatibility"]["incompatibilities"]
    ] == ["namespace_mismatch"]
    assert payload["metric_deltas"] is None
    assert payload["threshold_deltas"] == []


def test_comparison_endpoint_uses_non_disclosing_foreign_history_behavior() -> None:
    app = create_app(viewer_settings())
    repository = InMemoryEvaluationRunHistoryRepository()
    baseline = make_history_record(
        run_id=f"{1:032x}",
        namespace="tenant-a",
    )
    foreign = make_history_record(
        run_id=f"{2:032x}",
        namespace="tenant-b",
    )
    asyncio.run(repository.persist_terminal_run(baseline))
    asyncio.run(repository.persist_terminal_run(foreign))

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        response = client.post(
            "/api/v1/evaluations/runs/compare",
            headers=viewer_headers(),
            json={
                "baseline_run_id": baseline.context.run_id,
                "candidate_run_id": foreign.context.run_id,
            },
        )

    assert response.status_code == 404
    assert response.json()["error"] == "evaluation_run_history_not_found"


def test_comparison_endpoint_requires_history_and_two_distinct_runs(
    settings: Settings,
) -> None:
    run_id = f"{1:032x}"
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.benchmark_service = service(None)
        disabled = client.post(
            "/api/v1/evaluations/runs/compare",
            json={
                "baseline_run_id": run_id,
                "candidate_run_id": f"{2:032x}",
            },
        )
        duplicate = client.post(
            "/api/v1/evaluations/runs/compare",
            json={
                "baseline_run_id": run_id,
                "candidate_run_id": run_id,
            },
        )

    assert disabled.status_code == 409
    assert disabled.json()["error"] == "evaluation_run_history_disabled"
    assert duplicate.status_code == 422
    assert duplicate.json()["error"] == "validation_error"
