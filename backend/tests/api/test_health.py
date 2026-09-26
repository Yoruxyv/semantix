from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.protocols import EvaluationDatasetRepository
from app.core.config import Settings
from app.core.exceptions import (
    CacheStorageError,
    CoordinationStorageError,
    EvaluationDatasetStorageError,
)
from app.factory import create_app


def settings() -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
    )


def test_health_reports_provider_names_and_is_not_rate_limited() -> None:
    with TestClient(create_app(settings())) as client:
        responses = [client.get("/health") for _ in range(25)]

    assert all(response.status_code == 200 for response in responses)
    assert responses[-1].json() == {
        "status": "ok",
        "embedding_provider": "mock",
        "generation_provider": "mock",
    }


def test_ready_reports_active_cache_backend() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "cache_backend": "memory",
        "evaluation_dataset_storage": "session",
    }


def test_ready_returns_503_when_cache_dependency_is_unavailable() -> None:
    class FailingCache:
        async def stats(self) -> None:
            raise CacheStorageError

    with TestClient(create_app(settings())) as client:
        cast(FastAPI, client.app).state.semantic_cache = FailingCache()
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": "not_ready",
        "detail": "A required storage dependency is unavailable.",
    }


def test_ready_returns_503_when_dataset_storage_is_unavailable() -> None:
    class FailingDatasetRepository:
        async def readiness(self) -> None:
            raise EvaluationDatasetStorageError

    with TestClient(create_app(settings())) as client:
        benchmark_service = cast(
            BenchmarkService,
            cast(FastAPI, client.app).state.benchmark_service,
        )
        benchmark_service._dataset_repository = cast(
            EvaluationDatasetRepository,
            FailingDatasetRepository(),
        )
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": "not_ready",
        "detail": "A required storage dependency is unavailable.",
    }


def test_ready_returns_503_when_coordination_is_unavailable() -> None:
    class FailingCoordination:
        async def read_threshold(self) -> float:
            raise CoordinationStorageError

    with TestClient(create_app(settings())) as client:
        cast(FastAPI, client.app).state.coordination = FailingCoordination()
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"] == "not_ready"
