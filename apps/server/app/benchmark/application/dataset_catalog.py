from dataclasses import dataclass
from datetime import datetime

from app.benchmark.api.dataset_schemas import (
    EvaluationDatasetPreview,
    EvaluationDatasetSource,
    EvaluationDatasetValidationRequest,
    ImportedEvaluationCase,
    InlineEvaluationDatasetSource,
    PersistedEvaluationDatasetCatalogLimits,
    PersistedEvaluationDatasetDetail,
    PersistedEvaluationDatasetListResponse,
    PersistedEvaluationDatasetMetadata,
    PersistedEvaluationDatasetSource,
    PersistEvaluationDatasetRequest,
)
from app.benchmark.domain.datasets import get_dataset
from app.benchmark.domain.models import (
    BenchmarkDataset,
    BenchmarkRuntimeConfiguration,
    PersistedEvaluationDataset,
)
from app.benchmark.domain.protocols import EvaluationDatasetRepository
from app.benchmark.domain.validation import (
    ValidatedImportedDataset,
    validate_imported_dataset,
)
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.exceptions import (
    EvaluationDatasetNotFoundError,
    EvaluationDatasetPersistenceDisabledError,
    EvaluationDatasetRetentionError,
)


@dataclass(frozen=True, slots=True)
class ResolvedEvaluationDataset:
    dataset: BenchmarkDataset
    history_namespace: str | None
    source_dataset_expires_at: datetime | None


def _persisted_metadata(
    record: PersistedEvaluationDataset,
) -> PersistedEvaluationDatasetMetadata:
    metadata = record.metadata
    return PersistedEvaluationDatasetMetadata(
        dataset_id=metadata.dataset_id,
        namespace=metadata.namespace,
        name=metadata.name,
        description=metadata.description,
        schema_version=metadata.schema_version,
        digest=metadata.digest,
        case_count=metadata.case_count,
        decoded_bytes=metadata.decoded_bytes,
        created_at=metadata.created_at,
        expires_at=metadata.expires_at,
    )


def _persisted_detail(
    record: PersistedEvaluationDataset,
) -> PersistedEvaluationDatasetDetail:
    return PersistedEvaluationDatasetDetail(
        **_persisted_metadata(record).model_dump(),
        cases=[
            ImportedEvaluationCase(
                case_id=case.case_id,
                prompt=case.prompt,
                expected_cache_hit=case.expected_cache_hit,
                expected_match_case_id=case.expected_match_case_id,
                category=case.category,
                note=case.note,
            )
            for case in record.dataset.cases
        ],
    )


class EvaluationDatasetCatalog:
    """Own imported-dataset validation, persistence, and run-time resolution."""

    def __init__(
        self,
        repository: EvaluationDatasetRepository | None,
        *,
        runtime_configuration: BenchmarkRuntimeConfiguration,
    ) -> None:
        self._repository = repository
        self._runtime_configuration = runtime_configuration

    @property
    def repository(self) -> EvaluationDatasetRepository | None:
        return self._repository

    @repository.setter
    def repository(self, value: EvaluationDatasetRepository | None) -> None:
        self._repository = value

    def validate_dataset(
        self,
        request: EvaluationDatasetValidationRequest,
    ) -> EvaluationDatasetPreview:
        return self.validate_inline(
            request.dataset,
            repetitions=request.repetitions,
            threshold_count=request.threshold_count,
        ).preview

    def validate_inline(
        self,
        definition: object,
        *,
        repetitions: int,
        threshold_count: int,
    ) -> ValidatedImportedDataset:
        runtime = self._runtime_configuration
        return validate_imported_dataset(
            definition,
            repetitions=repetitions,
            threshold_count=threshold_count,
            max_cases=runtime.evaluation_dataset_max_cases,
            max_decoded_bytes=runtime.evaluation_dataset_max_decoded_bytes,
            max_workload_queries=runtime.evaluation_max_workload_queries,
        )

    async def resolve_for_run(
        self,
        source: EvaluationDatasetSource,
        *,
        repetitions: int,
        threshold_count: int,
        authorized_namespaces: AuthorizedNamespaceScope,
        history_enabled: bool,
        builtin_history_namespace: str | None,
    ) -> ResolvedEvaluationDataset:
        if isinstance(source, InlineEvaluationDatasetSource):
            dataset = self.validate_inline(
                source.definition,
                repetitions=repetitions,
                threshold_count=threshold_count,
            ).dataset
            return ResolvedEvaluationDataset(
                dataset=dataset,
                history_namespace=None,
                source_dataset_expires_at=None,
            )

        if isinstance(source, PersistedEvaluationDatasetSource):
            repository = self._require_repository()
            record = await repository.get_dataset(
                str(source.dataset_id),
                authorized_namespaces=authorized_namespaces,
            )
            if record is None:
                raise EvaluationDatasetNotFoundError
            return ResolvedEvaluationDataset(
                dataset=record.dataset,
                history_namespace=(
                    record.metadata.namespace if history_enabled else None
                ),
                source_dataset_expires_at=record.metadata.expires_at,
            )

        dataset = get_dataset(source.dataset_id)
        history_namespace: str | None = None
        if history_enabled:
            if builtin_history_namespace is None:
                raise ValueError(
                    "Built-in history namespace must be resolved before execution"
                )
            history_namespace = builtin_history_namespace
        return ResolvedEvaluationDataset(
            dataset=dataset,
            history_namespace=history_namespace,
            source_dataset_expires_at=None,
        )

    async def list_persisted(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> PersistedEvaluationDatasetListResponse:
        runtime = self._runtime_configuration
        limits = PersistedEvaluationDatasetCatalogLimits(
            default_retention_days=runtime.evaluation_dataset_default_retention_days,
            max_retention_days=runtime.evaluation_dataset_max_retention_days,
            max_persisted_per_namespace=(
                runtime.evaluation_dataset_max_persisted_per_namespace
            ),
        )
        if self._repository is None:
            return PersistedEvaluationDatasetListResponse(
                storage_mode="session",
                persistence_enabled=False,
                items=[],
                total=0,
                offset=offset,
                limit=limit,
                has_more=False,
                limits=limits,
            )

        page = await self._repository.list_datasets(
            namespace=namespace,
            offset=offset,
            limit=limit,
        )
        items = [
            PersistedEvaluationDatasetMetadata(
                dataset_id=item.dataset_id,
                namespace=item.namespace,
                name=item.name,
                description=item.description,
                schema_version=item.schema_version,
                digest=item.digest,
                case_count=item.case_count,
                decoded_bytes=item.decoded_bytes,
                created_at=item.created_at,
                expires_at=item.expires_at,
            )
            for item in page.items
        ]
        return PersistedEvaluationDatasetListResponse(
            storage_mode="postgres",
            persistence_enabled=True,
            items=items,
            total=page.total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < page.total,
            limits=limits,
        )

    async def detail(
        self,
        dataset_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> PersistedEvaluationDatasetDetail:
        repository = self._require_repository()
        record = await repository.get_dataset(
            dataset_id,
            authorized_namespaces=authorized_namespaces,
        )
        if record is None:
            raise EvaluationDatasetNotFoundError
        return _persisted_detail(record)

    async def persist(
        self,
        request: PersistEvaluationDatasetRequest,
        *,
        namespace: str,
    ) -> PersistedEvaluationDatasetDetail:
        repository = self._require_repository()
        runtime = self._runtime_configuration
        retention_days = (
            runtime.evaluation_dataset_default_retention_days
            if request.retention_days is None
            else request.retention_days
        )
        if retention_days > runtime.evaluation_dataset_max_retention_days:
            raise EvaluationDatasetRetentionError

        validated = self.validate_inline(
            request.dataset,
            repetitions=1,
            threshold_count=2,
        )
        record = await repository.create_dataset(
            namespace=namespace,
            validated=validated,
            retention_days=retention_days,
        )
        return _persisted_detail(record)

    async def delete(
        self,
        dataset_id: str,
        *,
        namespace: str,
    ) -> None:
        repository = self._require_repository()
        if not await repository.delete_dataset(dataset_id, namespace=namespace):
            raise EvaluationDatasetNotFoundError

    async def readiness(self) -> None:
        if self._repository is not None:
            await self._repository.readiness()

    def _require_repository(self) -> EvaluationDatasetRepository:
        if self._repository is None:
            raise EvaluationDatasetPersistenceDisabledError
        return self._repository
