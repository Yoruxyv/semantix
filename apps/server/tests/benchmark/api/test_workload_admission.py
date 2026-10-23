"""Exercise per-run admission through real routes, execution and memory caches."""

import asyncio
from collections.abc import Iterator, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.benchmark.api.run_schemas import BenchmarkRunResponse
from app.benchmark.application import run_executor, service
from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.datasets import get_dataset
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    BenchmarkRuntimeConfiguration,
)
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.core.config import AuthPrincipalSettings, Settings
from app.factory import create_app
from semantix_cache import CacheClosedError
from tests.benchmark.application.test_history_retention import (
    RecordingHistoryRepository,
)
from tests.benchmark.support import InMemoryEvaluationDatasetRepository

TOKEN = sha256(b"synthetic-budget-operator").hexdigest()


class Embeddings:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> Sequence[float]:
        self.calls += 1
        return [1.0, 0.0, 0.0, 0.0]


class Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return "Synthetic budget answer"


def definition(count: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Synthetic workload budget",
        "cases": [
            {
                "case_id": f"case-{index}",
                "prompt": f"Synthetic budget prompt {index}",
                "expected_cache_hit": False,
            }
            for index in range(count)
        ],
    }


@dataclass
class AdmissionHarness:
    app: FastAPI
    client: TestClient
    repository: InMemoryEvaluationDatasetRepository
    history: RecordingHistoryRepository
    embeddings: Embeddings
    provider: Provider
    allocated: MagicMock
    caches: list[InMemoryCacheBackend]
    monkeypatch: pytest.MonkeyPatch
    executed: AsyncMock

    def configure(self, limit: int) -> None:
        benchmark = BenchmarkService(
            self.embeddings,
            self.provider,
            max_cache_size=50,
            cache_ttl_seconds=None,
            prompt_normalizer=lambda prompt: prompt,
            runtime_configuration=BenchmarkRuntimeConfiguration(
                application_version="1.0.0",
                embedding_provider_category="mock",
                generation_provider_category="mock",
                embedding_dimensions=4,
                embedding_space_fingerprint="1" * 64,
                generation_configuration_fingerprint="2" * 64,
                normalization_mode="identity",
                normalization_fingerprint="3" * 64,
                evaluation_timeout_seconds=5,
                evaluation_max_workload_queries=limit,
                evaluation_dataset_storage="postgres",
                evaluation_run_history_storage="postgres",
                evaluation_run_history_retention_days=30,
                evaluation_run_history_max_per_namespace=100,
                evaluation_run_history_cleanup_batch_size=10,
            ),
            dataset_repository=self.repository,
            history_repository=self.history,
        )
        self.executed = AsyncMock(wraps=benchmark._run_executor.execute)
        self.monkeypatch.setattr(benchmark._run_executor, "execute", self.executed)
        self.app.state.benchmark_service = benchmark

    def save(self, count: int) -> dict[str, object]:
        response = self.client.post(
            "/api/v1/evaluations/datasets/persisted",
            json={"dataset": definition(count), "namespace": "default"},
        )
        assert response.status_code == 201, response.text
        dataset_id = response.json()["dataset_id"]
        return {"kind": "persisted", "dataset_id": dataset_id, "namespace": "default"}

    def assert_no_execution(self) -> None:
        self.allocated.assert_not_called()
        self.executed.assert_not_called()
        assert self.embeddings.calls == self.provider.calls == 0
        assert self.caches == []
        assert self.history.records == []


async def close_caches(caches: list[InMemoryCacheBackend]) -> None:
    for cache in caches:
        async with asyncio.timeout(2):
            await cache.store.aclose()
            with pytest.raises(CacheClosedError):
                await cache.store.inspect_entries()


async def assert_cache_hits(cache: InMemoryCacheBackend, queries: int) -> None:
    async with asyncio.timeout(2):
        page = await cache.store.inspect_entries()
    assert page.total == 1
    assert page.items[0].hit_count == queries - 1


@pytest.fixture
def admission(monkeypatch: pytest.MonkeyPatch) -> Iterator[AdmissionHarness]:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        mock_embedding_dimensions=4,
        cache_backend="memory",
        evaluation_dataset_storage="session",
        evaluation_run_history_storage="disabled",
        auth_mode="token",
        auth_principals=[
            AuthPrincipalSettings(
                name="budget-operator",
                token_sha256=sha256(TOKEN.encode()).hexdigest(),
                role="operator",
                namespaces=["default"],
            )
        ],
    )
    caches: list[InMemoryCacheBackend] = []

    def create_cache(
        max_size: int, ttl_seconds: int | None, *, dimensions: int
    ) -> InMemoryCacheBackend:
        cache = InMemoryCacheBackend(max_size, ttl_seconds, dimensions=dimensions)
        caches.append(cache)
        return cache

    allocated = MagicMock(wraps=uuid4)
    monkeypatch.setattr(service, "uuid4", allocated)
    monkeypatch.setattr(run_executor, "InMemoryCacheBackend", create_cache)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        harness = AdmissionHarness(
            app,
            client,
            InMemoryEvaluationDatasetRepository(),
            RecordingHistoryRepository(),
            Embeddings(),
            Provider(),
            allocated,
            caches,
            monkeypatch,
            AsyncMock(),
        )
        harness.configure(100)
        try:
            yield harness
        finally:
            assert client.portal is not None
            client.portal.call(close_caches, caches)
            harness.repository.records.clear()
            harness.history.records.clear()


@pytest.mark.parametrize(
    ("source", "limit", "cases", "repetitions", "status"),
    [
        ("inline", 100, 20, 5, 200),
        ("inline", 100, 21, 5, 422),
        ("persisted", 100, 20, 5, 200),
        ("persisted", 100, 21, 5, 422),
        ("persisted", 20, 21, 1, 422),
        *[
            (source, limit, 8, repetitions, status)
            for source in ("builtin", "legacy")
            for limit, repetitions, status in (
                (5, 1, 422),
                (8, 1, 200),
                (39, 5, 422),
                (40, 5, 200),
            )
        ],
    ],
)
def test_run_budget_for_every_source(
    admission: AdmissionHarness,
    source: str,
    limit: int,
    cases: int,
    repetitions: int,
    status: int,
) -> None:
    if source == "persisted":
        selection = admission.save(cases)
    elif source == "inline":
        selection = {"kind": "inline", "definition": definition(cases)}
    else:
        selection = {"kind": "builtin", "dataset_id": "quick"}
    before = deepcopy(admission.repository.records)
    admission.configure(limit)
    payload: dict[str, object] = {
        "repetitions": repetitions,
        "threshold": 1.0,
        "evaluation_thresholds": [0.5, 1.0],
        "reset_cache_before_run": False,
        "allow_external_provider_calls": True,
    }
    route = "/api/v1/evaluations/runs"
    if source == "legacy":
        route = "/api/v1/benchmarks/run"
        payload["dataset_id"] = "quick"
    else:
        payload["dataset_source"] = selection
        if source == "builtin":
            payload["history_namespace"] = "default"
    response = admission.client.post(route, json=payload)

    assert admission.repository.records == before
    assert response.status_code == status, response.text
    if status == 422:
        admission.assert_no_execution()
        if source == "inline":
            assert response.json()["error"] == "evaluation_dataset_invalid"
            assert response.json()["issues"][0]["code"] == "workload_limit_exceeded"
        else:
            assert response.json() == {
                "error": "evaluation_workload_limit_exceeded",
                "detail": "The planned evaluation queries exceed the configured per-run limit. Reduce repetitions or use a smaller dataset.",
            }
        return

    result = BenchmarkRunResponse.model_validate(response.json())
    planned = cases * repetitions
    admission.allocated.assert_called_once()
    admission.executed.assert_awaited_once()
    accepted = admission.executed.call_args.args[2]
    assert isinstance(accepted, AcceptedEvaluationRunContext)
    assert result.run_id == accepted.run_id
    assert (
        accepted.accepted_at
        <= result.started_at
        <= result.completed_at
        <= datetime.now(UTC)
    )
    assert len(admission.caches) == 1
    assert admission.embeddings.calls == result.metrics.total_queries == planned
    assert admission.provider.calls == result.metrics.provider_calls == 1
    assert result.metrics.cache_hits == planned - 1
    assert admission.client.portal is not None
    admission.client.portal.call(assert_cache_hits, admission.caches[0], planned)
    assert len(result.threshold_evaluations) == 2
    assert [row.sequence for row in result.query_results] == list(range(1, planned + 1))
    expected_ids = (
        [f"case-{index}" for index in range(cases)]
        if source in ("inline", "persisted")
        else [case.case_id for case in get_dataset("quick").cases]
    )
    assert [row.case_id for row in result.query_results] == expected_ids * repetitions
    assert [row.repetition for row in result.query_results] == [
        repetition for repetition in range(1, repetitions + 1) for _ in range(cases)
    ]
    retained = source in ("persisted", "builtin")
    assert len(admission.history.records) == int(retained)
    assert result.history_retention.state == (
        "retained" if retained else "not_retained"
    )
    if retained:
        record = admission.history.records[0]
        assert record.context == accepted
        assert record.metrics == result.metrics
        if source == "persisted":
            saved = next(iter(before.values()))
            assert record.context.source_dataset_expires_at == saved.metadata.expires_at
            assert result.dataset.digest == saved.metadata.digest


@pytest.mark.parametrize(
    ("scenario", "status", "error"),
    [
        ("unauthenticated", 401, "authentication_required"),
        ("foreign_scope", 403, "forbidden"),
        ("foreign_record", 404, "evaluation_dataset_not_found"),
        ("missing", 404, "evaluation_dataset_not_found"),
        ("storage_disabled", 409, "evaluation_dataset_persistence_disabled"),
        ("consent_false", 422, "validation_error"),
        ("consent_missing", 422, "validation_error"),
    ],
)
def test_source_and_authorization_gates_precede_budget(
    admission: AdmissionHarness, scenario: str, status: int, error: str
) -> None:
    selection = admission.save(21)
    if scenario == "missing":
        selection["dataset_id"] = str(uuid4())
    if scenario == "foreign_scope":
        selection["namespace"] = "foreign"
    if scenario == "foreign_record":
        # Same authorized lookup as a missing UUID; repository scope hides the row.
        selection["namespace"] = "default"
        record = next(iter(admission.repository.records.values()))
        admission.repository.records[record.metadata.dataset_id] = replace(
            record, metadata=replace(record.metadata, namespace="foreign")
        )
    before = deepcopy(admission.repository.records)
    admission.configure(1)
    read = AsyncMock(wraps=admission.repository.get_dataset)
    admission.monkeypatch.setattr(admission.repository, "get_dataset", read)
    if scenario == "storage_disabled":
        admission.app.state.benchmark_service._dataset_repository = None
    if scenario == "unauthenticated":
        del admission.client.headers["Authorization"]
    payload: dict[str, object] = {
        "dataset_source": selection,
        "allow_external_provider_calls": scenario != "consent_false",
    }
    if scenario == "consent_missing":
        del payload["allow_external_provider_calls"]
    response = admission.client.post("/api/v1/evaluations/runs", json=payload)

    assert response.status_code == status, response.text
    assert response.json()["error"] == error
    assert admission.repository.records == before
    assert read.await_count == int(scenario in ("missing", "foreign_record"))
    admission.assert_no_execution()
    assert "Synthetic budget" not in response.text
