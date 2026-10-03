from collections.abc import Sequence

import pytest

from app.benchmark.api.schemas import (
    EvaluationRunRequest,
    PersistedEvaluationDatasetSource,
    PersistEvaluationDatasetRequest,
)
from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.models import BenchmarkRuntimeConfiguration
from app.core.exceptions import (
    EvaluationDatasetNotFoundError,
    EvaluationDatasetPersistenceDisabledError,
    EvaluationDatasetRetentionError,
)
from tests.benchmark.support import InMemoryEvaluationDatasetRepository


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return [1.0, 0.0, 0.0, 0.0]


class Provider:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        return f"response:{prompt}"


def definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Persistent synthetic set",
        "description": "No generated responses are stored.",
        "cases": [
            {
                "case_id": "seed",
                "prompt": "Synthetic catalog seed",
                "expected_cache_hit": False,
                "category": "catalog",
            },
            {
                "case_id": "repeat",
                "prompt": "Synthetic catalog seed",
                "expected_cache_hit": True,
                "expected_match_case_id": "seed",
                "category": "catalog",
            },
        ],
    }


def service(
    provider: Provider,
    repository: InMemoryEvaluationDatasetRepository | None,
) -> BenchmarkService:
    return BenchmarkService(
        Embeddings(),
        provider,
        max_cache_size=10,
        cache_ttl_seconds=60,
        prompt_normalizer=lambda prompt: prompt,
        runtime_configuration=BenchmarkRuntimeConfiguration(
            application_version="1.0.0",
            embedding_provider_category="mock",
            generation_provider_category="mock",
            embedding_dimensions=4,
            embedding_space_fingerprint="1" * 64,
            generation_configuration_fingerprint="3" * 64,
            normalization_mode="identity",
            normalization_fingerprint="2" * 64,
            evaluation_timeout_seconds=30,
            evaluation_dataset_storage=(
                "session" if repository is None else "postgres"
            ),
            evaluation_dataset_default_retention_days=30,
            evaluation_dataset_max_retention_days=365,
        ),
        dataset_repository=repository,
    )


@pytest.mark.asyncio
async def test_session_mode_reports_disabled_catalog_without_a_database() -> None:
    benchmark = service(Provider(), None)

    catalog = await benchmark.list_persisted_datasets(
        namespace=None,
        offset=0,
        limit=20,
    )

    assert catalog.storage_mode == "session"
    assert catalog.persistence_enabled is False
    assert catalog.items == []
    with pytest.raises(EvaluationDatasetPersistenceDisabledError):
        await benchmark.persist_dataset(
            PersistEvaluationDatasetRequest(dataset=definition()),
            namespace="default",
        )


@pytest.mark.asyncio
async def test_catalog_crud_is_explicit_immutable_and_provider_free() -> None:
    provider = Provider()
    repository = InMemoryEvaluationDatasetRepository()
    benchmark = service(provider, repository)
    request = PersistEvaluationDatasetRequest(
        dataset=definition(),
        retention_days=14,
    )

    first = await benchmark.persist_dataset(request, namespace="tenant-a")
    second = await benchmark.persist_dataset(request, namespace="tenant-a")
    catalog = await benchmark.list_persisted_datasets(
        namespace="tenant-a",
        offset=0,
        limit=20,
    )
    detail = await benchmark.persisted_dataset_detail(
        str(first.dataset_id),
        authorized_namespaces=frozenset({"tenant-a"}),
    )

    assert provider.call_count == 0
    assert first.dataset_id != second.dataset_id
    assert first.digest == second.digest == detail.digest
    assert first.namespace == detail.namespace == "tenant-a"
    assert first.case_count == len(detail.cases) == 2
    assert [item.case_id for item in detail.cases] == ["seed", "repeat"]
    assert catalog.total == 2
    assert catalog.persistence_enabled is True

    await benchmark.delete_persisted_dataset(
        str(first.dataset_id),
        namespace="tenant-a",
    )

    with pytest.raises(EvaluationDatasetNotFoundError):
        await benchmark.persisted_dataset_detail(
            str(first.dataset_id),
            authorized_namespaces=frozenset({"tenant-a"}),
        )
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_foreign_and_missing_datasets_use_the_same_not_found_error() -> None:
    repository = InMemoryEvaluationDatasetRepository()
    benchmark = service(Provider(), repository)
    saved = await benchmark.persist_dataset(
        PersistEvaluationDatasetRequest(dataset=definition()),
        namespace="tenant-a",
    )

    for dataset_id in (str(saved.dataset_id), "00000000-0000-4000-8000-000000000000"):
        with pytest.raises(EvaluationDatasetNotFoundError):
            await benchmark.persisted_dataset_detail(
                dataset_id,
                authorized_namespaces=frozenset({"tenant-b"}),
            )

    with pytest.raises(EvaluationDatasetNotFoundError):
        await benchmark.delete_persisted_dataset(
            str(saved.dataset_id),
            namespace="tenant-b",
        )


@pytest.mark.asyncio
async def test_retention_above_the_deployment_limit_is_rejected() -> None:
    benchmark = service(Provider(), InMemoryEvaluationDatasetRepository())

    with pytest.raises(EvaluationDatasetRetentionError):
        await benchmark.persist_dataset(
            PersistEvaluationDatasetRequest(
                dataset=definition(),
                retention_days=366,
            ),
            namespace="default",
        )


@pytest.mark.asyncio
async def test_persisted_dataset_runs_without_changing_execution_semantics() -> None:
    provider = Provider()
    repository = InMemoryEvaluationDatasetRepository()
    benchmark = service(provider, repository)
    saved = await benchmark.persist_dataset(
        PersistEvaluationDatasetRequest(dataset=definition()),
        namespace="tenant-a",
    )

    result = await benchmark.run_evaluation(
        EvaluationRunRequest(
            dataset_source=PersistedEvaluationDatasetSource(
                kind="persisted",
                dataset_id=saved.dataset_id,
                namespace="tenant-a",
            ),
            threshold=0.9,
            evaluation_thresholds=[0.8, 0.9],
            allow_external_provider_calls=True,
        ),
        authorized_namespaces=frozenset({"tenant-a"}),
    )

    assert result.dataset.dataset_source == "persisted"
    assert result.dataset.dataset_id == str(saved.dataset_id)
    assert result.metrics.total_queries == 2
    assert provider.call_count == result.metrics.provider_calls == 1
