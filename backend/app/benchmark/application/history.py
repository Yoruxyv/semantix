import logging
from datetime import datetime
from typing import Literal

from app.benchmark.api.schemas import (
    BenchmarkReproducibilityMetadata,
    BenchmarkRunResponse,
    EvaluationRunRetentionStatus,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    EvaluationRunHistoryRecord,
)
from app.benchmark.domain.protocols import EvaluationRunHistoryRepository
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

FailureTerminalState = Literal["failed", "timed_out"]


def _safe_failure_metadata(error: Exception) -> tuple[str, str | None]:
    if isinstance(error, AppError):
        return error.error_code, error.public_detail
    return "internal_error", None


class EvaluationRunHistoryRecorder:
    def __init__(
        self,
        repository: EvaluationRunHistoryRepository | None,
    ) -> None:
        self._repository = repository

    def _can_retain(self, context: AcceptedEvaluationRunContext) -> bool:
        return self._repository is not None and context.history_namespace is not None

    def _log_retention_failure(
        self,
        context: AcceptedEvaluationRunContext,
        error: Exception,
    ) -> None:
        logger.warning(
            "Evaluation run history retention failed run_id=%s error_type=%s",
            context.run_id,
            type(error).__name__,
        )

    async def _persist(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> None:
        repository = self._repository
        if repository is None:
            return

        await repository.persist_terminal_run(record)

    async def retain_completed(
        self,
        context: AcceptedEvaluationRunContext,
        response: BenchmarkRunResponse,
    ) -> BenchmarkRunResponse:
        if not self._can_retain(context):
            return response

        try:
            record = EvaluationRunHistoryRecord(
                context=context,
                terminal_state="completed",
                started_at=response.started_at,
                completed_at=response.completed_at,
                reproducibility=response.reproducibility,
                metrics=response.metrics,
                threshold_evaluation_mode=response.threshold_evaluation_mode,
                threshold_evaluations=tuple(response.threshold_evaluations),
            )
            await self._persist(record)
        except Exception as error:  # noqa: BLE001 - retention must not fail the benchmark
            self._log_retention_failure(context, error)
            retention_state = "retention_failed"
        else:
            retention_state = "retained"

        return response.model_copy(
            update={
                "history_retention": EvaluationRunRetentionStatus(
                    state=retention_state,
                )
            }
        )

    async def retain_failure(
        self,
        context: AcceptedEvaluationRunContext,
        *,
        terminal_state: FailureTerminalState,
        started_at: datetime,
        completed_at: datetime,
        reproducibility: BenchmarkReproducibilityMetadata,
        error: Exception,
    ) -> None:
        if not self._can_retain(context):
            return

        try:
            failure_code, safe_failure_detail = _safe_failure_metadata(error)
            record = EvaluationRunHistoryRecord(
                context=context,
                terminal_state=terminal_state,
                started_at=started_at,
                completed_at=completed_at,
                reproducibility=reproducibility,
                metrics=None,
                threshold_evaluation_mode="frozen_candidate_projection",
                threshold_evaluations=(),
                failure_code=failure_code,
                safe_failure_detail=safe_failure_detail,
            )
            await self._persist(record)
        except Exception as retention_error:  # noqa: BLE001 - retention is best-effort
            self._log_retention_failure(context, retention_error)
