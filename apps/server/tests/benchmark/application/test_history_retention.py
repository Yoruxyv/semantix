import asyncio
from collections.abc import Sequence

import pytest

from app.benchmark.api.schemas import (
    BenchmarkRunRequest,
    EvaluationRunRequest,
    InlineEvaluationDatasetSource,
    PersistedEvaluationDatasetSource,
    PersistEvaluationDatasetRequest,
)
from app.benchmark.application.service import BenchmarkService
from app.benchmark.domain.models import (
    BenchmarkRuntimeConfiguration,
    EvaluationRunHistoryRecord,
    RetainedEvaluationRun,
    RetainedEvaluationRunPage,
)
from app.benchmark.domain.protocols import EvaluationDatasetRepository
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.exceptions import (
    EvaluationRunHistoryStorageError,
    EvaluationTimeoutError,
    InvalidProviderResponseError,
)
from app.providers.protocols import GenerationProvider
from tests.benchmark.support import InMemoryEvaluationDatasetRepository


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return [1.0, 0.0, 0.0, 0.0]


class Provider:
    async def generate(self, prompt: str) -> str:
        return f"response:{prompt}"


class InvalidResponseProvider:
    async def generate(self, prompt: str) -> str:
        raise InvalidProviderResponseError("raw upstream detail must not be retained")


class SecretFailureProvider:
    async def generate(self, prompt: str) -> str:
        raise RuntimeError("synthetic-secret-provider-detail")


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, prompt: str) -> str:
        self.started.set()
        await asyncio.Event().wait()
        return f"response:{prompt}"


class RecordingHistoryRepository:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.records: list[EvaluationRunHistoryRecord] = []
        self.fail_writes = fail_writes

    async def persist_terminal_run(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> None:
        if self.fail_writes:
            raise EvaluationRunHistoryStorageError(
                "Synthetic history persistence failure"
            )

        self.records.append(record)

    async def list_runs(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> RetainedEvaluationRunPage:
        return RetainedEvaluationRunPage(items=(), total=0)

    async def get_run(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> RetainedEvaluationRun | None:
        return None

    async def delete_run(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> bool:
        return False

    async def readiness(self) -> None:
        return None


def service(
    repository: RecordingHistoryRepository,
    *,
    dataset_repository: EvaluationDatasetRepository | None = None,
    provider: GenerationProvider | None = None,
    evaluation_timeout_seconds: float = 30,
) -> BenchmarkService:
    runtime = BenchmarkRuntimeConfiguration(
        application_version="1.0.0",
        embedding_provider_category="mock",
        generation_provider_category="mock",
        embedding_dimensions=4,
        embedding_space_fingerprint="1" * 64,
        generation_configuration_fingerprint="3" * 64,
        normalization_mode="identity",
        normalization_fingerprint="2" * 64,
        evaluation_timeout_seconds=evaluation_timeout_seconds,
        evaluation_run_history_storage="postgres",
        evaluation_run_history_retention_days=30,
        evaluation_run_history_max_per_namespace=100,
        evaluation_run_history_cleanup_batch_size=10,
    )

    return BenchmarkService(
        Embeddings(),
        provider or Provider(),
        max_cache_size=10,
        cache_ttl_seconds=60,
        prompt_normalizer=lambda prompt: prompt,
        runtime_configuration=runtime,
        dataset_repository=dataset_repository,
        history_repository=repository,
    )


@pytest.mark.asyncio
async def test_successful_builtin_evaluation_is_retained_as_aggregate_history() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(repository)

    response = await benchmark.run_evaluation(
        EvaluationRunRequest(
            evaluation_thresholds=[0.80, 0.92],
            allow_external_provider_calls=True,
        ),
        builtin_history_namespace="tenant-a",
    )

    assert response.history_retention.state == "retained"
    assert len(repository.records) == 1

    record = repository.records[0]

    assert record.context.run_id == response.run_id
    assert record.context.history_namespace == "tenant-a"
    assert record.context.dataset == response.dataset
    assert record.terminal_state == "completed"
    assert record.started_at == response.started_at
    assert record.completed_at == response.completed_at
    assert record.reproducibility == response.reproducibility
    assert record.metrics == response.metrics
    assert record.threshold_evaluations == tuple(response.threshold_evaluations)

    assert not hasattr(record, "query_results")


@pytest.mark.asyncio
async def test_successful_persisted_evaluation_inherits_history_namespace() -> None:
    history_repository = RecordingHistoryRepository()
    dataset_repository = InMemoryEvaluationDatasetRepository()

    benchmark = service(
        history_repository,
        dataset_repository=dataset_repository,
    )

    persisted = await benchmark.persist_dataset(
        PersistEvaluationDatasetRequest(
            dataset={
                "schema_version": 1,
                "name": "Persisted history evidence",
                "cases": [
                    {
                        "case_id": "seed",
                        "prompt": "Persisted history seed",
                        "expected_cache_hit": False,
                        "category": "history",
                    },
                    {
                        "case_id": "repeat",
                        "prompt": "Persisted history seed",
                        "expected_cache_hit": True,
                        "expected_match_case_id": "seed",
                        "category": "history",
                    },
                ],
            },
            retention_days=7,
        ),
        namespace="tenant-persisted",
    )

    response = await benchmark.run_evaluation(
        EvaluationRunRequest(
            dataset_source=PersistedEvaluationDatasetSource(
                kind="persisted",
                dataset_id=persisted.dataset_id,
                namespace="tenant-persisted",
            ),
            evaluation_thresholds=[0.80, 0.92],
            allow_external_provider_calls=True,
        ),
        authorized_namespaces=frozenset({"tenant-persisted"}),
    )

    assert response.history_retention.state == "retained"
    assert len(history_repository.records) == 1

    record = history_repository.records[0]

    assert record.context.history_namespace == "tenant-persisted"
    assert record.context.dataset.dataset_source == "persisted"
    assert record.context.dataset.dataset_id == str(persisted.dataset_id)
    assert record.context.source_dataset_expires_at == persisted.expires_at
    assert record.context.run_id == response.run_id
    assert record.terminal_state == "completed"


@pytest.mark.asyncio
async def test_successful_history_write_failure_does_not_lose_evaluation_result() -> (
    None
):
    repository = RecordingHistoryRepository(
        fail_writes=True,
    )
    benchmark = service(repository)

    response = await benchmark.run_evaluation(
        EvaluationRunRequest(
            evaluation_thresholds=[0.80, 0.92],
            allow_external_provider_calls=True,
        ),
        builtin_history_namespace="tenant-a",
    )

    assert response.history_retention.state == "retention_failed"
    assert response.metrics.total_queries > 0
    assert response.query_results
    assert repository.records == []


@pytest.mark.asyncio
async def test_inline_evaluation_remains_non_durable_when_history_is_enabled() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(repository)

    response = await benchmark.run_evaluation(
        EvaluationRunRequest(
            dataset_source=InlineEvaluationDatasetSource(
                kind="inline",
                definition={
                    "schema_version": 1,
                    "name": "Inline non-durable history evidence",
                    "cases": [
                        {
                            "case_id": "seed",
                            "prompt": "Inline history seed",
                            "expected_cache_hit": False,
                            "category": "history",
                        }
                    ],
                },
            ),
            evaluation_thresholds=[0.80, 0.92],
            allow_external_provider_calls=True,
        )
    )

    assert response.history_retention.state == "not_retained"
    assert repository.records == []


@pytest.mark.asyncio
async def test_legacy_benchmark_run_remains_non_durable() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(repository)

    response = await benchmark.run(
        BenchmarkRunRequest(
            evaluation_thresholds=[0.80, 0.92],
            allow_external_provider_calls=True,
        )
    )

    assert response.history_retention.state == "not_retained"
    assert repository.records == []


@pytest.mark.asyncio
async def test_failed_evaluation_is_retained_with_safe_public_error() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(
        repository,
        provider=InvalidResponseProvider(),
    )

    with pytest.raises(InvalidProviderResponseError):
        await benchmark.run_evaluation(
            EvaluationRunRequest(
                evaluation_thresholds=[0.80, 0.92],
                allow_external_provider_calls=True,
            ),
            builtin_history_namespace="tenant-failed",
        )

    assert len(repository.records) == 1
    record = repository.records[0]

    assert record.terminal_state == "failed"
    assert record.metrics is None
    assert record.threshold_evaluations == ()
    assert record.failure_code == InvalidProviderResponseError.error_code
    assert record.safe_failure_detail == InvalidProviderResponseError.public_detail
    assert "raw upstream detail" not in (record.safe_failure_detail or "")
    assert record.context.accepted_at <= record.started_at <= record.completed_at


@pytest.mark.asyncio
async def test_unhandled_failure_does_not_retain_exception_message() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(
        repository,
        provider=SecretFailureProvider(),
    )

    with pytest.raises(RuntimeError, match="synthetic-secret-provider-detail"):
        await benchmark.run_evaluation(
            EvaluationRunRequest(
                evaluation_thresholds=[0.80, 0.92],
                allow_external_provider_calls=True,
            ),
            builtin_history_namespace="tenant-internal-failure",
        )

    assert len(repository.records) == 1
    record = repository.records[0]

    assert record.terminal_state == "failed"
    assert record.failure_code == "internal_error"
    assert record.safe_failure_detail is None


@pytest.mark.asyncio
async def test_timeout_while_waiting_for_run_lock_is_retained() -> None:
    repository = RecordingHistoryRepository()
    benchmark = service(
        repository,
        evaluation_timeout_seconds=0.05,
    )
    run_lock = benchmark._run_lock
    await run_lock.acquire()

    try:
        with pytest.raises(EvaluationTimeoutError):
            await benchmark.run_evaluation(
                EvaluationRunRequest(
                    evaluation_thresholds=[0.80, 0.92],
                    allow_external_provider_calls=True,
                ),
                builtin_history_namespace="tenant-timeout",
            )
    finally:
        run_lock.release()

    assert len(repository.records) == 1
    record = repository.records[0]

    assert record.terminal_state == "timed_out"
    assert record.metrics is None
    assert record.threshold_evaluations == ()
    assert record.failure_code == EvaluationTimeoutError.error_code
    assert record.safe_failure_detail == EvaluationTimeoutError.public_detail
    assert record.context.accepted_at <= record.started_at <= record.completed_at


@pytest.mark.asyncio
async def test_failure_history_write_does_not_replace_original_error() -> None:
    repository = RecordingHistoryRepository(fail_writes=True)
    benchmark = service(
        repository,
        provider=InvalidResponseProvider(),
    )

    with pytest.raises(InvalidProviderResponseError):
        await benchmark.run_evaluation(
            EvaluationRunRequest(
                evaluation_thresholds=[0.80, 0.92],
                allow_external_provider_calls=True,
            ),
            builtin_history_namespace="tenant-write-failure",
        )

    assert repository.records == []


@pytest.mark.asyncio
async def test_cancelled_evaluation_is_not_retained() -> None:
    repository = RecordingHistoryRepository()
    provider = BlockingProvider()
    benchmark = service(repository, provider=provider)

    task = asyncio.create_task(
        benchmark.run_evaluation(
            EvaluationRunRequest(
                evaluation_thresholds=[0.80, 0.92],
                allow_external_provider_calls=True,
            ),
            builtin_history_namespace="tenant-cancelled",
        )
    )
    await provider.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.records == []
