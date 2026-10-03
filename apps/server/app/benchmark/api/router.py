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
