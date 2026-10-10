"""Route distinct dataset, execution and retained-history workflows.

Both routers borrow BenchmarkService and apply the configured route quota.
Viewers read built-in catalogs, authorized persisted datasets/history and
comparisons. Operators validate imports, persist datasets and execute runs;
admins delete persisted datasets or history in a concrete authorized namespace.

/benchmarks provides built-in catalogs and synchronous runs. /evaluations
adds imported/persisted sources and history. Validation returns a provider-free
preview; persistence is an explicit operation, not a side effect of validation
or inline execution. Runs use isolated in-memory caches rather than the live
interactive cache, and threshold projections never update live configuration.

Scoped listings may infer a sole namespace; wildcard access allows global
listings. Persistence, persisted-source execution and deletion require concrete
scope, including for wildcard admins. Built-in evaluation history also resolves
concrete scope when requested or enabled. Detail/comparison reads pass authorized
namespace sets to storage so missing and foreign IDs share not-found behavior.
Dataset persistence and terminal aggregate history are separately configured;
inline runs are not retained, and retention failure need not fail a completed run.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_benchmark_service
from app.benchmark.api.schemas import (
    BenchmarkDatasetListResponse,
    BenchmarkRunRequest,
    BenchmarkRunResponse,
    BuiltinEvaluationDatasetSource,
    DeleteEvaluationRunHistoryResponse,
    DeletePersistedEvaluationDatasetResponse,
    EvaluationDatasetPreview,
    EvaluationDatasetValidationRequest,
    EvaluationRunComparisonRequest,
    EvaluationRunComparisonResponse,
    EvaluationRunHistoryDetail,
    EvaluationRunHistoryListResponse,
    EvaluationRunRequest,
    PersistedEvaluationDatasetDetail,
    PersistedEvaluationDatasetListResponse,
    PersistedEvaluationDatasetSource,
    PersistEvaluationDatasetRequest,
)
from app.benchmark.application.service import BenchmarkService
from app.cache.domain.namespaces import AuthorizedNamespaceScope, CacheNamespace
from app.middleware.rate_limit import app_rate_limit, limiter
from app.security.auth import (
    AdminPrincipal,
    OperatorPrincipal,
    ViewerPrincipal,
    resolve_namespace,
)

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])
evaluations_router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])
BenchmarkDependency = Annotated[BenchmarkService, Depends(get_benchmark_service)]
EvaluationNamespaceQuery = Annotated[CacheNamespace | None, Query()]


@router.get("/datasets", response_model=BenchmarkDatasetListResponse)
@limiter.limit(app_rate_limit)
async def benchmark_datasets(
    request: Request,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
) -> BenchmarkDatasetListResponse:
    return benchmark.datasets()


@router.post("/run", response_model=BenchmarkRunResponse)
@limiter.limit(app_rate_limit)
async def run_benchmark(
    request: Request,
    payload: BenchmarkRunRequest,
    benchmark: BenchmarkDependency,
    principal: OperatorPrincipal,
) -> BenchmarkRunResponse:
    """Execute a built-in benchmark synchronously with an isolated run cache.

    This legacy execution route does not select a retained-history namespace.
    External provider calls require the request's explicit acknowledgement.
    """
    return await benchmark.run(payload)


@evaluations_router.get(
    "/datasets",
    response_model=BenchmarkDatasetListResponse,
)
@limiter.limit(app_rate_limit)
async def evaluation_datasets(
    request: Request,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
) -> BenchmarkDatasetListResponse:
    return benchmark.datasets()


@evaluations_router.post(
    "/datasets/validate",
    response_model=EvaluationDatasetPreview,
)
@limiter.limit(app_rate_limit)
async def validate_evaluation_dataset(
    request: Request,
    payload: EvaluationDatasetValidationRequest,
    benchmark: BenchmarkDependency,
    principal: OperatorPrincipal,
) -> EvaluationDatasetPreview:
    """Validate imported data and estimate workload without calling providers.

    Returns:
        Preview with zero provider calls; this neither persists data nor runs it.

    Raises:
        EvaluationDatasetValidationError: Import rules fail, producing safe
            structured issues with HTTP 422.
    """
    return benchmark.validate_dataset(payload)


@evaluations_router.get(
    "/datasets/persisted",
    response_model=PersistedEvaluationDatasetListResponse,
)
@limiter.limit(app_rate_limit)
async def list_persisted_evaluation_datasets(
    request: Request,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
    namespace: EvaluationNamespaceQuery = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PersistedEvaluationDatasetListResponse:
    authorized_namespace = resolve_namespace(
        principal,
        namespace,
        allow_global=True,
    )
    return await benchmark.list_persisted_datasets(
        namespace=authorized_namespace,
        offset=offset,
        limit=limit,
    )


@evaluations_router.post(
    "/datasets/persisted",
    response_model=PersistedEvaluationDatasetDetail,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(app_rate_limit)
async def persist_evaluation_dataset(
    request: Request,
    payload: PersistEvaluationDatasetRequest,
    benchmark: BenchmarkDependency,
    principal: OperatorPrincipal,
) -> PersistedEvaluationDatasetDetail:
    """Persist an operator-authorized import in a concrete namespace.

    Returns:
        Stored dataset detail with HTTP 201 and bounded retention metadata.

    Raises:
        EvaluationDatasetPersistenceDisabledError: No persistent catalog is
            configured, producing HTTP 409 rather than silently saving locally.
    """
    namespace = resolve_namespace(
        principal,
        payload.namespace,
        allow_global=False,
    )
    if namespace is None:
        raise RuntimeError("Persistent dataset namespace was not resolved")
    return await benchmark.persist_dataset(payload, namespace=namespace)


@evaluations_router.get(
    "/datasets/persisted/{dataset_id}",
    response_model=PersistedEvaluationDatasetDetail,
)
@limiter.limit(app_rate_limit)
async def get_persisted_evaluation_dataset(
    request: Request,
    dataset_id: UUID,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
) -> PersistedEvaluationDatasetDetail:
    return await benchmark.persisted_dataset_detail(
        str(dataset_id),
        authorized_namespaces=(
            None if principal.has_global_namespace_access else principal.namespaces
        ),
    )


@evaluations_router.delete(
    "/datasets/persisted/{dataset_id}",
    response_model=DeletePersistedEvaluationDatasetResponse,
)
@limiter.limit(app_rate_limit)
async def delete_persisted_evaluation_dataset(
    request: Request,
    dataset_id: UUID,
    benchmark: BenchmarkDependency,
    principal: AdminPrincipal,
    namespace: EvaluationNamespaceQuery = None,
) -> DeletePersistedEvaluationDatasetResponse:
    """Delete a stored dataset as admin in one concrete authorized namespace."""
    authorized_namespace = resolve_namespace(
        principal,
        namespace,
        allow_global=False,
    )
    if authorized_namespace is None:
        raise RuntimeError("Persistent dataset namespace was not resolved")
    await benchmark.delete_persisted_dataset(
        str(dataset_id),
        namespace=authorized_namespace,
    )
    return DeletePersistedEvaluationDatasetResponse(
        deleted=True,
        dataset_id=dataset_id,
        namespace=authorized_namespace,
    )


@evaluations_router.get(
    "/runs",
    response_model=EvaluationRunHistoryListResponse,
)
@limiter.limit(app_rate_limit)
async def list_evaluation_run_history(
    request: Request,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
    namespace: EvaluationNamespaceQuery = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EvaluationRunHistoryListResponse:
    """List viewer-authorized aggregates, or an explicit empty disabled catalog."""
    authorized_namespace = resolve_namespace(
        principal,
        namespace,
        allow_global=True,
    )
    return await benchmark.list_run_history(
        namespace=authorized_namespace,
        offset=offset,
        limit=limit,
    )


@evaluations_router.post("/runs", response_model=BenchmarkRunResponse)
@limiter.limit(app_rate_limit)
async def run_evaluation(
    request: Request,
    payload: EvaluationRunRequest,
    benchmark: BenchmarkDependency,
    principal: OperatorPrincipal,
) -> BenchmarkRunResponse:
    """Execute a validated source with operator authorization and isolated cache.

    Persisted sources resolve concrete access before loading. Built-in sources
    resolve history scope when requested or retention is enabled; inline sources
    remain unretained. The service revalidates inline data rather than trusting a
    prior preview. The response describes the completed run and retention outcome.
    """
    authorized_namespaces: AuthorizedNamespaceScope = frozenset()
    builtin_history_namespace: str | None = None
    if isinstance(payload.dataset_source, PersistedEvaluationDatasetSource):
        namespace = resolve_namespace(
            principal,
            payload.dataset_source.namespace,
            allow_global=False,
        )
        if namespace is None:
            raise RuntimeError("Persistent dataset namespace was not resolved")
        authorized_namespaces = frozenset({namespace})
    elif isinstance(payload.dataset_source, BuiltinEvaluationDatasetSource) and (
        payload.history_namespace is not None or benchmark.run_history_enabled
    ):
        builtin_history_namespace = resolve_namespace(
            principal,
            payload.history_namespace,
            allow_global=False,
        )
        if builtin_history_namespace is None:
            raise RuntimeError("Evaluation history namespace was not resolved")

    return await benchmark.run_evaluation(
        payload,
        authorized_namespaces=authorized_namespaces,
        builtin_history_namespace=builtin_history_namespace,
    )


@evaluations_router.post(
    "/runs/compare",
    response_model=EvaluationRunComparisonResponse,
)
@limiter.limit(app_rate_limit)
async def compare_evaluation_run_history(
    request: Request,
    payload: EvaluationRunComparisonRequest,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
) -> EvaluationRunComparisonResponse:
    """Compare two viewer-authorized retained runs without executing providers.

    Both reads enforce namespace scope. Compatibility blockers suppress deltas,
    including cross-namespace comparisons by otherwise global principals.
    """
    return await benchmark.compare_run_history(
        payload,
        authorized_namespaces=(
            None if principal.has_global_namespace_access else principal.namespaces
        ),
    )


@evaluations_router.get(
    "/runs/{run_id}",
    response_model=EvaluationRunHistoryDetail,
)
@limiter.limit(app_rate_limit)
async def get_evaluation_run_history(
    request: Request,
    run_id: UUID,
    benchmark: BenchmarkDependency,
    principal: ViewerPrincipal,
) -> EvaluationRunHistoryDetail:
    """Read viewer-authorized historical aggregates without per-query evidence."""
    return await benchmark.run_history_detail(
        run_id.hex,
        authorized_namespaces=(
            None if principal.has_global_namespace_access else principal.namespaces
        ),
    )


@evaluations_router.delete(
    "/runs/{run_id}",
    response_model=DeleteEvaluationRunHistoryResponse,
)
@limiter.limit(app_rate_limit)
async def delete_evaluation_run_history(
    request: Request,
    run_id: UUID,
    benchmark: BenchmarkDependency,
    principal: AdminPrincipal,
    namespace: EvaluationNamespaceQuery = None,
) -> DeleteEvaluationRunHistoryResponse:
    """Delete retained history as admin in a concrete authorized namespace."""
    authorized_namespace = resolve_namespace(
        principal,
        namespace,
        allow_global=False,
    )
    if authorized_namespace is None:
        raise RuntimeError("Evaluation history namespace was not resolved")
    return await benchmark.delete_run_history(
        run_id.hex,
        namespace=authorized_namespace,
    )
