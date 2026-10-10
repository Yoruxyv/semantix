"""Define separate dataset and terminal-history repository capabilities.

The caller authenticates and authorizes before using a port. Identifier reads
receive AuthorizedNamespaceScope: None permits unrestricted reads, an empty set
permits none, and a nonempty set restricts visible namespaces. Listing's None
namespace means global listing and mutations require a concrete authorized scope.
These protocols neither install/configure storage nor guarantee durability or
manage the borrowed repository lifecycle. Readiness checks the implementation's
capability, not providers or the other repository port.
"""

from typing import Protocol

from app.benchmark.domain.models import (
    EvaluationRunHistoryRecord,
    PersistedEvaluationDataset,
    PersistedEvaluationDatasetPage,
    RetainedEvaluationRun,
    RetainedEvaluationRunPage,
)
from app.benchmark.domain.validation import ValidatedImportedDataset
from app.cache.domain.namespaces import AuthorizedNamespaceScope


class EvaluationDatasetRepository(Protocol):
    """Store validated imports and expose scoped dataset metadata/cases.

    list_datasets returns a metadata page. get_dataset returns an authorized
    record or None without distinguishing missing/foreign records. create_dataset
    accepts validated cases plus explicit namespace/retention; delete_dataset
    reports whether a scoped record was deleted. Implementations enforce storage
    bounds, visibility and expiry; callers own authentication and lifecycle.
    """

    async def list_datasets(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> PersistedEvaluationDatasetPage: ...

    async def get_dataset(
        self,
        dataset_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> PersistedEvaluationDataset | None: ...

    async def create_dataset(
        self,
        *,
        namespace: str,
        validated: ValidatedImportedDataset,
        retention_days: int,
    ) -> PersistedEvaluationDataset: ...

    async def delete_dataset(
        self,
        dataset_id: str,
        *,
        namespace: str,
    ) -> bool: ...

    async def readiness(self) -> None: ...


class EvaluationRunHistoryRepository(Protocol):
    """Read/delete scoped history and persist eligible terminal aggregates.

    list_runs returns retained summaries; get_run returns the visible retained
    record or None. delete_run reports a scoped deletion. persist_terminal_run
    receives a terminal record with a history namespace, not raw query results.
    Failure/retention policy belongs to application and infrastructure code;
    this port alone does not promise that every run is durably recorded.
    """

    async def list_runs(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> RetainedEvaluationRunPage: ...

    async def get_run(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> RetainedEvaluationRun | None: ...

    async def delete_run(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> bool: ...

    async def persist_terminal_run(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> None: ...

    async def readiness(self) -> None: ...
