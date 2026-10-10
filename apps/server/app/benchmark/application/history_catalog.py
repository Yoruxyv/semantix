"""Expose stored aggregate history through caller-authorized repository scopes.

List summaries omit threshold rows; detail adds them without captured query-level
prompts/responses. Conversion validates response shapes, not the authenticity or
privacy of arbitrary repository values. Historical metadata describes the retained
run, not current runtime configuration. Comparison delegates to
``app.benchmark.application.comparison`` after both identifier reads succeed.
"""

from app.benchmark.api.comparison_schemas import (
    EvaluationRunComparisonRequest,
    EvaluationRunComparisonResponse,
)
from app.benchmark.api.schemas import (
    DeleteEvaluationRunHistoryResponse,
    EvaluationRunHistoryDetail,
    EvaluationRunHistoryItem,
    EvaluationRunHistoryListResponse,
)
from app.benchmark.application.comparison import compare_evaluation_runs
from app.benchmark.domain.models import (
    RetainedEvaluationRun,
    RetainedEvaluationRunSummary,
)
from app.benchmark.domain.protocols import EvaluationRunHistoryRepository
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.config import EvaluationRunHistoryStorageMode
from app.core.exceptions import (
    EvaluationRunHistoryDisabledError,
    EvaluationRunHistoryNotFoundError,
    EvaluationRunHistoryStorageError,
)


def _history_item(record: RetainedEvaluationRunSummary) -> EvaluationRunHistoryItem:
    """Project retained aggregate fields and require a concrete history namespace."""
    context = record.context
    namespace = context.history_namespace
    if namespace is None:
        raise EvaluationRunHistoryStorageError(
            "Retained evaluation run history is missing its namespace"
        )

    return EvaluationRunHistoryItem(
        run_id=context.run_id,
        namespace=namespace,
        terminal_state=record.terminal_state,
        accepted_at=context.accepted_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        expires_at=record.expires_at,
        source_dataset_expires_at=context.source_dataset_expires_at,
        dataset=context.dataset,
        reproducibility=record.reproducibility,
        metrics=record.metrics,
        failure_code=record.failure_code,
        safe_failure_detail=record.safe_failure_detail,
    )


def _history_detail(record: RetainedEvaluationRun) -> EvaluationRunHistoryDetail:
    item = _history_item(record.summary)
    return EvaluationRunHistoryDetail(
        **item.model_dump(),
        threshold_evaluation_mode=record.record.threshold_evaluation_mode,
        threshold_evaluations=list(record.record.threshold_evaluations),
    )


class EvaluationRunHistoryCatalog:
    """Borrow optional history storage without authenticating or owning its lifecycle.

    Disabled storage returns an explicit empty list, but detail/comparison/delete
    require enabled storage. Enabled mode with no repository is a storage error.
    The caller authorizes listing/mutation namespaces; identifier reads pass its
    authorized scope to the repository. Construction opens no resources.
    """

    def __init__(
        self,
        repository: EvaluationRunHistoryRepository | None,
        *,
        storage_mode: EvaluationRunHistoryStorageMode,
    ) -> None:
        self._repository = repository
        self._storage_mode = storage_mode

    def _require_repository(self) -> EvaluationRunHistoryRepository:
        if self._storage_mode == "disabled":
            raise EvaluationRunHistoryDisabledError
        if self._repository is None:
            raise EvaluationRunHistoryStorageError(
                "Evaluation run history is enabled but no repository is configured"
            )
        return self._repository

    async def list_runs(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> EvaluationRunHistoryListResponse:
        """Return retained summaries and pagination, or an explicit disabled empty page.

        Args:
            namespace: Authorized namespace filter, or None for an authorized global list.
            offset: Caller-validated number of matching records to skip.
            limit: Caller-validated maximum page size.

        Returns:
            Summary page; has_more derives from offset, returned length and total.

        Raises:
            EvaluationRunHistoryStorageError: Enabled storage lacks a repository or
                a retained summary has no namespace. Other repository/response
                validation errors can propagate.
        """
        if self._storage_mode == "disabled":
            return EvaluationRunHistoryListResponse(
                storage_mode="disabled",
                retention_enabled=False,
                items=[],
                total=0,
                offset=offset,
                limit=limit,
                has_more=False,
            )

        repository = self._require_repository()
        page = await repository.list_runs(
            namespace=namespace,
            offset=offset,
            limit=limit,
        )
        items = [_history_item(item) for item in page.items]
        return EvaluationRunHistoryListResponse(
            storage_mode="postgres",
            retention_enabled=True,
            items=items,
            total=page.total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < page.total,
        )

    async def get_run(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> EvaluationRunHistoryDetail:
        """Retrieve aggregate detail without distinguishing absent and invisible runs.

        Args:
            run_id: Retained run identity.
            authorized_namespaces: Caller-authorized scope; None permits unrestricted
                repository reads and an empty set permits none.

        Returns:
            Historical aggregate evidence plus retained threshold rows.

        Raises:
            EvaluationRunHistoryDisabledError: History storage is disabled.
            EvaluationRunHistoryStorageError: Enabled storage is unavailable/inconsistent.
            EvaluationRunHistoryNotFoundError: No visible retained record was returned.
        """
        repository = self._require_repository()
        record = await repository.get_run(
            run_id,
            authorized_namespaces=authorized_namespaces,
        )
        if record is None:
            raise EvaluationRunHistoryNotFoundError
        return _history_detail(record)

    async def compare_runs(
        self,
        request: EvaluationRunComparisonRequest,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> EvaluationRunComparisonResponse:
        """Read baseline then candidate with the same authorized scope and compare them.

        Reads are sequential, not a shared repository snapshot. Either inaccessible
        record fails before comparison. Permission to read both, including global
        administrator access, does not bypass comparison's namespace/identity gates.

        Args:
            request: Validated distinct baseline/candidate run identities.
            authorized_namespaces: Caller-authorized scope used for both lookups.

        Returns:
            Compatibility assessment and permitted candidate-minus-baseline deltas.

        Raises:
            EvaluationRunHistoryDisabledError: History storage is disabled.
            EvaluationRunHistoryStorageError: Enabled storage is unavailable/inconsistent.
            EvaluationRunHistoryNotFoundError: Either record is absent or invisible.
        """
        baseline = await self.get_run(
            request.baseline_run_id,
            authorized_namespaces=authorized_namespaces,
        )
        candidate = await self.get_run(
            request.candidate_run_id,
            authorized_namespaces=authorized_namespaces,
        )
        return compare_evaluation_runs(baseline, candidate)

    async def delete_run(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> DeleteEvaluationRunHistoryResponse:
        """Delete a retained run within a concrete caller-authorized namespace.

        Args:
            run_id: Retained record identity.
            namespace: Concrete namespace already authorized for mutation.

        Returns:
            Deletion acknowledgment only after a scoped repository deletion succeeds.

        Raises:
            EvaluationRunHistoryDisabledError: History storage is disabled.
            EvaluationRunHistoryStorageError: Enabled storage is unavailable.
            EvaluationRunHistoryNotFoundError: No scoped deletion was reported.
        """
        repository = self._require_repository()
        if not await repository.delete_run(run_id, namespace=namespace):
            raise EvaluationRunHistoryNotFoundError
        return DeleteEvaluationRunHistoryResponse(
            deleted=True,
            run_id=run_id,
            namespace=namespace,
        )
