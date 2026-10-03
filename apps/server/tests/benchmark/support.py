from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.benchmark.domain.models import (
    BenchmarkDataset,
    PersistedEvaluationDataset,
    PersistedEvaluationDatasetMetadata,
    PersistedEvaluationDatasetPage,
)
from app.benchmark.domain.validation import ValidatedImportedDataset
from app.cache.domain.namespaces import AuthorizedNamespaceScope


class InMemoryEvaluationDatasetRepository:
    def __init__(self) -> None:
        self.records: dict[str, PersistedEvaluationDataset] = {}
        self.readiness_calls = 0

    async def list_datasets(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> PersistedEvaluationDatasetPage:
        items = [
            record.metadata
            for record in self.records.values()
            if namespace is None or record.metadata.namespace == namespace
        ]
        items.sort(
            key=lambda item: (item.created_at, item.dataset_id),
            reverse=True,
        )
        return PersistedEvaluationDatasetPage(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
        )

    async def get_dataset(
        self,
        dataset_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> PersistedEvaluationDataset | None:
        record = self.records.get(dataset_id)
        if record is None:
            return None
        if (
            authorized_namespaces is not None
            and record.metadata.namespace not in authorized_namespaces
        ):
            return None
        return record

    async def create_dataset(
        self,
        *,
        namespace: str,
        validated: ValidatedImportedDataset,
        retention_days: int,
    ) -> PersistedEvaluationDataset:
        dataset_id = str(uuid4())
        created_at = datetime.now(UTC)
        metadata = PersistedEvaluationDatasetMetadata(
            dataset_id=dataset_id,
            namespace=namespace,
            name=validated.preview.name,
            description=validated.preview.description,
            schema_version=validated.preview.schema_version,
            digest=validated.preview.digest,
            case_count=validated.preview.case_count,
            decoded_bytes=validated.preview.decoded_bytes,
            created_at=created_at,
            expires_at=created_at + timedelta(days=retention_days),
        )
        dataset = BenchmarkDataset(
            summary=validated.dataset.summary.model_copy(
                update={
                    "dataset_id": dataset_id,
                    "dataset_source": "persisted",
                }
            ),
            cases=validated.dataset.cases,
        )
        record = PersistedEvaluationDataset(metadata=metadata, dataset=dataset)
        self.records[dataset_id] = record
        return record

    async def delete_dataset(
        self,
        dataset_id: str,
        *,
        namespace: str,
    ) -> bool:
        record = self.records.get(dataset_id)
        if record is None or record.metadata.namespace != namespace:
            return False
        del self.records[dataset_id]
        return True

    async def readiness(self) -> None:
        self.readiness_calls += 1
