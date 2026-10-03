from asyncio import Lock
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from app.benchmark.api.common_schemas import BenchmarkDatasetListResponse
from app.benchmark.api.comparison_schemas import (
    EvaluationRunComparisonRequest,
    EvaluationRunComparisonResponse,
)
from app.benchmark.api.dataset_schemas import (
    EvaluationDatasetPreview,
    EvaluationDatasetValidationRequest,
    PersistedEvaluationDatasetDetail,
    PersistedEvaluationDatasetListResponse,
    PersistEvaluationDatasetRequest,
)
from app.benchmark.api.history_schemas import (
    DeleteEvaluationRunHistoryResponse,
    EvaluationRunHistoryDetail,
    EvaluationRunHistoryListResponse,
)
from app.benchmark.api.run_schemas import (
    BenchmarkRunRequest,
    BenchmarkRunResponse,
    EvaluationRunRequest,
)
from app.benchmark.application.dataset_catalog import EvaluationDatasetCatalog
from app.benchmark.application.history_catalog import EvaluationRunHistoryCatalog
from app.benchmark.application.run_executor import EvaluationRunExecutor
from app.benchmark.domain.datasets import (
    DEFAULT_DATASET_ID,
    get_dataset,
    list_datasets,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    BenchmarkDataset,
    BenchmarkRuntimeConfiguration,
)
from app.benchmark.domain.protocols import (
    EvaluationDatasetRepository,
    EvaluationRunHistoryRepository,
)
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.providers.protocols import EmbeddingGenerator, GenerationProvider


class BenchmarkService:
    """Thin application facade for datasets, execution, history, and comparison."""

    def __init__(
        self,
        embedding_service: EmbeddingGenerator,
        provider: GenerationProvider,
        *,
        max_cache_size: int,
        cache_ttl_seconds: int | None,
        prompt_normalizer: Callable[[str], str],
        runtime_configuration: BenchmarkRuntimeConfiguration,
        dataset_repository: EvaluationDatasetRepository | None = None,
        history_repository: EvaluationRunHistoryRepository | None = None,
    ) -> None:
        if runtime_configuration.evaluation_timeout_seconds <= 0:
            raise ValueError("evaluation_timeout_seconds must be positive")

        self._runtime_configuration = runtime_configuration
        self._dataset_catalog = EvaluationDatasetCatalog(
            dataset_repository,
            runtime_configuration=runtime_configuration,
        )
        self._run_executor = EvaluationRunExecutor(
            embedding_service,
            provider,
            max_cache_size=max_cache_size,
            cache_ttl_seconds=cache_ttl_seconds,
            prompt_normalizer=prompt_normalizer,
            runtime_configuration=runtime_configuration,
            history_repository=history_repository,
        )
        self._history_catalog = EvaluationRunHistoryCatalog(
            history_repository,
            storage_mode=runtime_configuration.evaluation_run_history_storage,
        )

    @property
    def _dataset_repository(self) -> EvaluationDatasetRepository | None:
        """Compatibility bridge for the existing readiness dependency test."""

        return self._dataset_catalog.repository

    @_dataset_repository.setter
    def _dataset_repository(
        self,
        value: EvaluationDatasetRepository | None,
    ) -> None:
        self._dataset_catalog.repository = value

    @property
    def _run_lock(self) -> Lock:
        """Compatibility bridge for the lock-wait timeout regression test."""

        return self._run_executor.run_lock

    @property
    def run_history_enabled(self) -> bool:
        return self._runtime_configuration.evaluation_run_history_storage == "postgres"

    @property
    def runtime_configuration(self) -> BenchmarkRuntimeConfiguration:
        return self._runtime_configuration

    def datasets(self) -> BenchmarkDatasetListResponse:
        return BenchmarkDatasetListResponse(
            datasets=list_datasets(),
            default_dataset_id=DEFAULT_DATASET_ID,
        )

    async def run(self, request: BenchmarkRunRequest) -> BenchmarkRunResponse:
        dataset = get_dataset(request.dataset_id)
        accepted_run = self._accept_run(dataset)
        return await self._run_executor.execute(request, dataset, accepted_run)

    def validate_dataset(
        self,
        request: EvaluationDatasetValidationRequest,
    ) -> EvaluationDatasetPreview:
        return self._dataset_catalog.validate_dataset(request)

    async def run_evaluation(
        self,
        request: EvaluationRunRequest,
        *,
        authorized_namespaces: AuthorizedNamespaceScope = frozenset(),
        builtin_history_namespace: str | None = None,
    ) -> BenchmarkRunResponse:
        resolved = await self._dataset_catalog.resolve_for_run(
            request.dataset_source,
            repetitions=request.repetitions,
            threshold_count=len(request.evaluation_thresholds),
            authorized_namespaces=authorized_namespaces,
            history_enabled=self.run_history_enabled,
            builtin_history_namespace=builtin_history_namespace,
        )
        accepted_run = self._accept_run(
            resolved.dataset,
            history_namespace=resolved.history_namespace,
            source_dataset_expires_at=resolved.source_dataset_expires_at,
        )
        return await self._run_executor.execute(
            request,
            resolved.dataset,
            accepted_run,
        )

    async def list_run_history(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> EvaluationRunHistoryListResponse:
        return await self._history_catalog.list_runs(
            namespace=namespace,
            offset=offset,
            limit=limit,
        )

    async def run_history_detail(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> EvaluationRunHistoryDetail:
        return await self._history_catalog.get_run(
            run_id,
            authorized_namespaces=authorized_namespaces,
        )

    async def compare_run_history(
        self,
        request: EvaluationRunComparisonRequest,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> EvaluationRunComparisonResponse:
        return await self._history_catalog.compare_runs(
            request,
            authorized_namespaces=authorized_namespaces,
        )

    async def delete_run_history(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> DeleteEvaluationRunHistoryResponse:
        return await self._history_catalog.delete_run(
            run_id,
            namespace=namespace,
        )

    async def list_persisted_datasets(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> PersistedEvaluationDatasetListResponse:
        return await self._dataset_catalog.list_persisted(
            namespace=namespace,
            offset=offset,
            limit=limit,
        )

    async def persisted_dataset_detail(
        self,
        dataset_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> PersistedEvaluationDatasetDetail:
        return await self._dataset_catalog.detail(
            dataset_id,
            authorized_namespaces=authorized_namespaces,
        )

    async def persist_dataset(
        self,
        request: PersistEvaluationDatasetRequest,
        *,
        namespace: str,
    ) -> PersistedEvaluationDatasetDetail:
        return await self._dataset_catalog.persist(
            request,
            namespace=namespace,
        )

    async def delete_persisted_dataset(
        self,
        dataset_id: str,
        *,
        namespace: str,
    ) -> None:
        await self._dataset_catalog.delete(
            dataset_id,
            namespace=namespace,
        )

    async def dataset_catalog_readiness(self) -> None:
        await self._dataset_catalog.readiness()

    def _accept_run(
        self,
        dataset: BenchmarkDataset,
        *,
        history_namespace: str | None = None,
        source_dataset_expires_at: datetime | None = None,
    ) -> AcceptedEvaluationRunContext:
        return AcceptedEvaluationRunContext(
            run_id=uuid4().hex,
            accepted_at=datetime.now(UTC),
            dataset=dataset.summary,
            history_namespace=history_namespace,
            source_dataset_expires_at=source_dataset_expires_at,
        )
