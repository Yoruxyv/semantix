"""Retain eligible terminal aggregates without making storage a run-success gate.

``app.benchmark.application.run_executor`` selects terminal outcomes and re-raises
ordinary execution errors after this handoff. The recorder receives an accepted
identity and already resolved history namespace; it neither authenticates callers
nor captures query-level prompts, responses or observations for replay.
"""

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
    """Select declared AppError code/public detail, or internal_error with no detail.

    Never copy exception args or str(error). AppError public fields must already be
    safe; this selector does not sanitize arbitrary text supplied in those fields.
    """
    if isinstance(error, AppError):
        return error.error_code, error.public_detail
    return "internal_error", None


class EvaluationRunHistoryRecorder:
    """Attempt terminal retention through an optional borrowed repository.

    Eligibility requires both a repository and context.history_namespace, not
    merely successful execution or configured storage mode. Ordinary record/write
    failures are logged and contained. CancelledError and other BaseException
    subclasses are not caught; cancellation/process death cannot promise a row.
    Construction performs no I/O and does not own repository/pool closure.
    """

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
        """Log the accepted run ID and exception type without the exception message.

        Normal acceptance supplies a bounded UUID-hex ID; this logger adds no separate
        truncation or sanitization of arbitrary caller-supplied context values.
        """
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
        """Attempt aggregate retention while preserving measured results on ordinary failure.

        Ineligible contexts return the supplied response unchanged. Otherwise persist
        completed timestamps, configuration evidence, metrics and threshold rows,
        excluding query_results. Return a response copy marked retained after a
        successful repository await or retention_failed after an ordinary construction
        or persistence error. The status reports this attempt, not perpetual storage.

        Args:
            context: Accepted identity and optional caller-resolved history scope.
            response: Completed measured run evidence to preserve.

        Returns:
            Original response if ineligible, otherwise a copy with retention status.

        Raises:
            asyncio.CancelledError: Cancellation interrupts the retention await.
        """
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
        """Attempt failed/timed_out retention without raising ordinary retention errors.

        Store safe failure classification and configuration evidence with no metrics
        or threshold rows. Unknown exceptions become internal_error with no detail;
        AppError contributes its declared public code/detail, not internal args.
        The executor owns re-raising the original execution exception. Cancellation
        during this method can propagate instead of completing that ordinary path.

        Args:
            context: Accepted identity and optional resolved retention scope.
            terminal_state: Failed or timed_out classification chosen by the executor.
            started_at: Attempt start, which can precede run-lock acquisition.
            completed_at: Terminal failure time supplied by the executor.
            reproducibility: Recorded configuration evidence, not a reproduction guarantee.
            error: Execution error used only to select public-safe failure metadata.

        Raises:
            asyncio.CancelledError: Cancellation interrupts the retention await.
        """
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
