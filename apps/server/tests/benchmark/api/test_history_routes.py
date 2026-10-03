from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration
from app.core.config import Settings
from app.factory import create_app
from tests.benchmark.history_support import InMemoryEvaluationRunHistoryRepository
from tests.support import TEST_EMBEDDING_DIMENSIONS


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


def test_history_list_reports_disabled_storage(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.benchmark_service = service(None)
        response = client.get("/api/v1/evaluations/runs")
        detail = client.get(
            "/api/v1/evaluations/runs/00000000-0000-0000-0000-000000000001"
        )

    assert response.status_code == 200
    assert response.json() == {
        "storage_mode": "disabled",
        "retention_enabled": False,
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 20,
        "has_more": False,
    }
    assert detail.status_code == 409
    assert detail.json()["error"] == "evaluation_run_history_disabled"


def test_history_list_detail_and_delete_contracts(settings: Settings) -> None:
    app = create_app(settings)
    repository = InMemoryEvaluationRunHistoryRepository()

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)

        run = client.post(
            "/api/v1/evaluations/runs",
            json={
                "history_namespace": "tenant-history",
                "evaluation_thresholds": [0.80, 0.92],
                "allow_external_provider_calls": True,
            },
        )
        assert run.status_code == 200
        run_id = run.json()["run_id"]

        listed = client.get(
            "/api/v1/evaluations/runs",
            params={"namespace": "tenant-history"},
        )
        detail = client.get(f"/api/v1/evaluations/runs/{run_id}")

        missing_namespace_delete = client.delete(f"/api/v1/evaluations/runs/{run_id}")
        wrong_namespace_delete = client.delete(
            f"/api/v1/evaluations/runs/{run_id}",
            params={"namespace": "tenant-other"},
        )
        deleted = client.delete(
            f"/api/v1/evaluations/runs/{run_id}",
            params={"namespace": "tenant-history"},
        )
        after_delete = client.get(f"/api/v1/evaluations/runs/{run_id}")

    assert listed.status_code == 200
    page = listed.json()
    assert page["storage_mode"] == "postgres"
    assert page["retention_enabled"] is True
    assert page["total"] == 1
    assert page["items"][0]["run_id"] == run_id
    assert page["items"][0]["namespace"] == "tenant-history"
    assert page["items"][0]["terminal_state"] == "completed"
    assert "query_results" not in page["items"][0]
    assert "threshold_evaluations" not in page["items"][0]

    assert detail.status_code == 200
    evidence = detail.json()
    assert evidence["run_id"] == run_id
    assert evidence["namespace"] == "tenant-history"
    assert evidence["terminal_state"] == "completed"
    assert len(evidence["threshold_evaluations"]) == 2
    assert "query_results" not in evidence

    assert missing_namespace_delete.status_code == 403
    assert wrong_namespace_delete.status_code == 404
    assert wrong_namespace_delete.json()["error"] == "evaluation_run_history_not_found"

    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted": True,
        "run_id": run_id,
        "namespace": "tenant-history",
    }

    assert after_delete.status_code == 404
    assert after_delete.json()["error"] == "evaluation_run_history_not_found"
