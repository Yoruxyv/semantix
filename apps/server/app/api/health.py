from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.api.schemas import HealthResponse, ReadinessResponse
from app.core.exceptions import (
    CacheStorageError,
    CoordinationStorageError,
    EvaluationDatasetStorageError,
)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        embedding_provider=request.app.state.embedding_provider_name,
        generation_provider=request.app.state.generation_provider_name,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Not ready"}},
)
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    try:
        await request.app.state.semantic_cache.stats()
        await request.app.state.benchmark_service.dataset_catalog_readiness()
        coordination = request.app.state.coordination
        if coordination is not None:
            await coordination.read_threshold()
    except (CacheStorageError, CoordinationStorageError, EvaluationDatasetStorageError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "not_ready",
                "detail": "A required storage dependency is unavailable.",
            },
        )
    return ReadinessResponse(
        status="ready",
        cache_backend=request.app.state.settings.cache_backend,
        evaluation_dataset_storage=(
            request.app.state.settings.evaluation_dataset_storage
        ),
    )
