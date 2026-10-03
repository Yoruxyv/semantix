from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.benchmark.api.schemas import (
    BenchmarkDatasetSummary,
    BenchmarkMetrics,
    BenchmarkReproducibilityMetadata,
    ThresholdEvaluation,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    EvaluationRunHistoryRecord,
    EvaluationRunTerminalState,
    RetainedEvaluationRun,
    RetainedEvaluationRunPage,
)
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.exceptions import EvaluationRunHistoryStorageError


def make_history_record(
    *,
    run_id: str | None = None,
    namespace: str = "tenant-history",
    terminal_state: EvaluationRunTerminalState = "completed",
    completed_at: datetime | None = None,
) -> EvaluationRunHistoryRecord:
    completed = completed_at or datetime.now(UTC)
    started = completed - timedelta(seconds=1)
    accepted = started - timedelta(seconds=1)

    dataset = BenchmarkDatasetSummary(
        dataset_id="quick",
        dataset_source="builtin",
        schema_version=None,
        version="builtin-1",
        digest="a" * 64,
        name="History synthetic dataset",
        description="Aggregate-only run history evidence.",
        query_count=2,
        expected_hits=1,
        expected_misses=1,
        categories=["history"],
    )
    reproducibility = BenchmarkReproducibilityMetadata(
        application_version="1.0.0",
        dataset_id=dataset.dataset_id,
        dataset_source=dataset.dataset_source,
        dataset_schema_version=dataset.schema_version,
        dataset_version=dataset.version,
        dataset_digest=dataset.digest,
        embedding_provider_category="mock",
        generation_provider_category="mock",
        generation_configuration_fingerprint="b" * 64,
        comparison_contract_version=1,
        embedding_dimensions=4,
        embedding_space_fingerprint="c" * 64,
        normalization_mode="identity",
        normalization_fingerprint="d" * 64,
        measured_threshold=0.92,
        evaluation_thresholds=[0.80, 0.92],
        repetitions=1,
        reset_cache_before_run=True,
        estimated_cost_per_request_usd=0.001,
        estimated_cost_per_1k_tokens_usd=0.002,
        evaluation_timeout_seconds=30,
        configuration_fingerprint="e" * 64,
    )
    context = AcceptedEvaluationRunContext(
        run_id=run_id or uuid4().hex,
        accepted_at=accepted,
        dataset=dataset,
        history_namespace=namespace,
        source_dataset_expires_at=None,
    )

    thresholds: tuple[ThresholdEvaluation, ...]
    if terminal_state == "completed":
        metrics = BenchmarkMetrics(
            total_queries=2,
            cache_hits=1,
            cache_misses=1,
            provider_calls=1,
            provider_calls_avoided=1,
            hit_rate=0.5,
            average_latency_ms=10,
            median_latency_ms=9,
            p95_latency_ms=15,
            average_cache_hit_latency_ms=2,
            average_cache_miss_latency_ms=18,
            estimated_latency_saved_ms=16,
            estimated_provider_cost_saved_usd=0.001,
            estimated_tokens_saved=25,
            true_positive_hits=1,
            true_negative_misses=1,
            false_positive_hits=0,
            false_negative_misses=0,
            precision=1,
            recall=1,
            f1_score=1,
        )
        thresholds = (
            ThresholdEvaluation(
                threshold=0.80,
                result_kind="projected",
                hit_rate=0.5,
                precision=1,
                recall=1,
                f1_score=1,
                average_latency_ms=10,
                provider_calls_avoided=1,
                true_positive_hits=1,
                true_negative_misses=1,
                false_positive_hits=0,
                false_negative_misses=0,
            ),
            ThresholdEvaluation(
                threshold=0.92,
                result_kind="measured",
                hit_rate=0.5,
                precision=1,
                recall=1,
                f1_score=1,
                average_latency_ms=10,
                provider_calls_avoided=1,
                true_positive_hits=1,
                true_negative_misses=1,
                false_positive_hits=0,
                false_negative_misses=0,
            ),
        )
        failure_code = None
        safe_failure_detail = None
    else:
        metrics = None
        thresholds = ()
        failure_code = (
            "evaluation_timeout" if terminal_state == "timed_out" else "internal_error"
        )
        safe_failure_detail = (
            "The evaluation exceeded its configured wall-clock limit."
            if terminal_state == "timed_out"
            else None
        )

    return EvaluationRunHistoryRecord(
        context=context,
        terminal_state=terminal_state,
        started_at=started,
        completed_at=completed,
        reproducibility=reproducibility,
        metrics=metrics,
        threshold_evaluation_mode="frozen_candidate_projection",
        threshold_evaluations=thresholds,
        failure_code=failure_code,
        safe_failure_detail=safe_failure_detail,
    )


class InMemoryEvaluationRunHistoryRepository:
    def __init__(self, *, retention_days: int = 30) -> None:
        self._retention_days = retention_days
        self.records: dict[str, RetainedEvaluationRun] = {}
        self.readiness_calls = 0

    def _expires_at(self, record: EvaluationRunHistoryRecord) -> datetime:
        expires_at = record.completed_at + timedelta(days=self._retention_days)
        source_expiry = record.context.source_dataset_expires_at
        if source_expiry is not None:
            expires_at = min(expires_at, source_expiry)
        if expires_at <= record.completed_at:
            raise EvaluationRunHistoryStorageError(
                "Synthetic history retention window has already expired"
            )
        return expires_at

    def _active(self) -> list[RetainedEvaluationRun]:
        now = datetime.now(UTC)
        expired = [
            run_id
            for run_id, record in self.records.items()
            if record.expires_at <= now
        ]
        for run_id in expired:
            del self.records[run_id]
        return list(self.records.values())

    async def persist_terminal_run(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> None:
        self.records[record.context.run_id] = RetainedEvaluationRun(
            record=record,
            expires_at=self._expires_at(record),
        )

    async def list_runs(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> RetainedEvaluationRunPage:
        items = [
            record.summary
            for record in self._active()
            if namespace is None or record.record.context.history_namespace == namespace
        ]
        items.sort(key=lambda item: item.context.run_id)
        items.sort(key=lambda item: item.completed_at, reverse=True)
        return RetainedEvaluationRunPage(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
        )

    async def get_run(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> RetainedEvaluationRun | None:
        self._active()
        record = self.records.get(run_id)
        if record is None:
            return None
        namespace = record.record.context.history_namespace
        if authorized_namespaces is not None and (
            namespace is None or namespace not in authorized_namespaces
        ):
            return None
        return record

    async def delete_run(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> bool:
        self._active()
        record = self.records.get(run_id)
        if record is None or record.record.context.history_namespace != namespace:
            return False
        del self.records[run_id]
        return True

    async def readiness(self) -> None:
        self.readiness_calls += 1
