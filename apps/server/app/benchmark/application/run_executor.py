import asyncio
import math
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter

from app.benchmark.api.common_schemas import (
    BenchmarkOutcome,
    BenchmarkReproducibilityMetadata,
)
from app.benchmark.api.run_schemas import (
    BenchmarkQueryResult,
    BenchmarkRunResponse,
    EvaluationRunOptions,
)
from app.benchmark.application.history import EvaluationRunHistoryRecorder
from app.benchmark.application.reproducibility import build_reproducibility_metadata
from app.benchmark.domain.metrics import (
    calculate_metrics,
    evaluate_frozen_candidate_thresholds,
)
from app.benchmark.domain.models import (
    AcceptedEvaluationRunContext,
    BenchmarkCase,
    BenchmarkDataset,
    BenchmarkObservation,
    BenchmarkRuntimeConfiguration,
)
from app.benchmark.domain.protocols import EvaluationRunHistoryRepository
from app.cache.application.service import SemanticCache
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.core.exceptions import EvaluationTimeoutError
from app.providers.protocols import EmbeddingGenerator, GenerationProvider
from app.providers.shared.responses import validate_generation_response


def _classification(
    expected_cache_hit: bool,
    actual_cache_hit: bool,
) -> BenchmarkOutcome:
    if actual_cache_hit:
        return "true_positive" if expected_cache_hit else "false_positive"
    return "false_negative" if expected_cache_hit else "true_negative"


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class EvaluationRunExecutor:
    """Execute one accepted evaluation and retain its terminal aggregate outcome."""

    def __init__(
        self,
        embedding_service: EmbeddingGenerator,
        provider: GenerationProvider,
        *,
        max_cache_size: int,
        cache_ttl_seconds: int | None,
        prompt_normalizer: Callable[[str], str],
        runtime_configuration: BenchmarkRuntimeConfiguration,
        history_repository: EvaluationRunHistoryRepository | None,
    ) -> None:
        self._provider = provider
        self._embedding_service = embedding_service
        self._max_cache_size = max_cache_size
        self._cache_ttl_seconds = cache_ttl_seconds
        self._prompt_normalizer = prompt_normalizer
        self._runtime_configuration = runtime_configuration
        self._history_recorder = EvaluationRunHistoryRecorder(history_repository)
        self._run_lock = asyncio.Lock()

    @property
    def run_lock(self) -> asyncio.Lock:
        """Return the shared serialization lock used by evaluation runs."""

        return self._run_lock

    async def execute(
        self,
        request: EvaluationRunOptions,
        dataset: BenchmarkDataset,
        accepted_run: AcceptedEvaluationRunContext,
    ) -> BenchmarkRunResponse:
        attempt_started_at = datetime.now(UTC)
        reproducibility = build_reproducibility_metadata(
            request,
            dataset.summary,
            self._runtime_configuration,
        )

        try:
            response = await self._run_bounded(
                request,
                dataset,
                accepted_run,
                reproducibility=reproducibility,
            )
        except EvaluationTimeoutError as error:
            await self._history_recorder.retain_failure(
                accepted_run,
                terminal_state="timed_out",
                started_at=attempt_started_at,
                completed_at=datetime.now(UTC),
                reproducibility=reproducibility,
                error=error,
            )
            raise
        except Exception as error:
            await self._history_recorder.retain_failure(
                accepted_run,
                terminal_state="failed",
                started_at=attempt_started_at,
                completed_at=datetime.now(UTC),
                reproducibility=reproducibility,
                error=error,
            )
            raise

        return await self._history_recorder.retain_completed(
            accepted_run,
            response,
        )

    async def _run_bounded(
        self,
        request: EvaluationRunOptions,
        dataset: BenchmarkDataset,
        accepted_run: AcceptedEvaluationRunContext,
        *,
        reproducibility: BenchmarkReproducibilityMetadata,
    ) -> BenchmarkRunResponse:
        try:
            async with asyncio.timeout(
                self._runtime_configuration.evaluation_timeout_seconds
            ):
                async with self._run_lock:
                    return await self._run_exclusive(
                        request,
                        dataset,
                        accepted_run,
                        reproducibility=reproducibility,
                    )
        except TimeoutError as exc:
            raise EvaluationTimeoutError from exc

    def _create_run_cache(self, threshold: float) -> SemanticCache:
        return SemanticCache(
            self._embedding_service,
            InMemoryCacheBackend(
                self._max_cache_size,
                self._cache_ttl_seconds,
                dimensions=self._runtime_configuration.embedding_dimensions,
            ),
            threshold,
            prompt_normalizer=self._prompt_normalizer,
        )

    async def _execute_case(
        self,
        cache: SemanticCache,
        case: BenchmarkCase,
        *,
        sequence: int,
        repetition: int,
    ) -> tuple[BenchmarkQueryResult, BenchmarkObservation]:
        measured_at = perf_counter()
        lookup = await cache.lookup(case.prompt)
        if lookup.cache_hit:
            if lookup.response is None:
                raise RuntimeError("Validated benchmark hit had no response")
            response = lookup.response
        else:
            response = validate_generation_response(
                await self._provider.generate(case.prompt)
            )
            await cache.store(case.prompt, response, lookup.embedding)

        latency_ms = (perf_counter() - measured_at) * 1_000
        tokens_saved = (
            estimate_tokens(case.prompt) + estimate_tokens(response)
            if lookup.cache_hit
            else 0
        )
        result = BenchmarkQueryResult(
            sequence=sequence,
            repetition=repetition,
            case_id=case.case_id,
            category=case.category,
            prompt=case.prompt,
            expected_cache_hit=case.expected_cache_hit,
            expected_match_case_id=case.expected_match_case_id,
            note=case.note,
            actual_cache_hit=lookup.cache_hit,
            correct=case.expected_cache_hit == lookup.cache_hit,
            outcome=_classification(case.expected_cache_hit, lookup.cache_hit),
            similarity_score=lookup.similarity_score,
            latency_ms=latency_ms,
            provider_called=not lookup.cache_hit,
            matched_prompt=lookup.matched_prompt,
            matched_cache_key=lookup.matched_cache_key,
        )
        observation = BenchmarkObservation(
            expected_cache_hit=case.expected_cache_hit,
            actual_cache_hit=lookup.cache_hit,
            latency_ms=latency_ms,
            provider_called=not lookup.cache_hit,
            similarity_score=lookup.similarity_score,
            estimated_tokens_saved=tokens_saved,
        )
        return result, observation

    async def _run_exclusive(
        self,
        request: EvaluationRunOptions,
        dataset: BenchmarkDataset,
        accepted_run: AcceptedEvaluationRunContext,
        *,
        reproducibility: BenchmarkReproducibilityMetadata,
    ) -> BenchmarkRunResponse:
        started_at = datetime.now(UTC)
        run_cache = self._create_run_cache(request.threshold)

        query_results: list[BenchmarkQueryResult] = []
        observations: list[BenchmarkObservation] = []
        sequence = 0
        for repetition in range(1, request.repetitions + 1):
            if request.reset_cache_before_run:
                await run_cache.clear()
            for case in dataset.cases:
                sequence += 1
                result, observation = await self._execute_case(
                    run_cache,
                    case,
                    sequence=sequence,
                    repetition=repetition,
                )
                query_results.append(result)
                observations.append(observation)

        thresholds = request.evaluation_thresholds
        return BenchmarkRunResponse(
            run_id=accepted_run.run_id,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            dataset=dataset.summary,
            threshold=request.threshold,
            repetitions=request.repetitions,
            reset_cache_before_run=request.reset_cache_before_run,
            estimated_cost_per_request_usd=request.estimated_cost_per_request_usd,
            estimated_cost_per_1k_tokens_usd=request.estimated_cost_per_1k_tokens_usd,
            reproducibility=reproducibility,
            metrics=calculate_metrics(
                observations,
                estimated_cost_per_request_usd=request.estimated_cost_per_request_usd,
                estimated_cost_per_1k_tokens_usd=(
                    request.estimated_cost_per_1k_tokens_usd
                ),
            ),
            threshold_evaluation_mode="frozen_candidate_projection",
            threshold_evaluations=evaluate_frozen_candidate_thresholds(
                observations,
                thresholds,
                measured_threshold=request.threshold,
            ),
            query_results=query_results,
        )
