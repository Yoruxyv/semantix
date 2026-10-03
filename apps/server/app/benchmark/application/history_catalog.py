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
        repository = self._require_repository()
        if not await repository.delete_run(run_id, namespace=namespace):
            raise EvaluationRunHistoryNotFoundError
        return DeleteEvaluationRunHistoryResponse(
            deleted=True,
            run_id=run_id,
            namespace=namespace,
        )
