"""Keep public liveness separate from selected storage readiness checks.

Neither endpoint authenticates callers or consumes ordinary route quotas.
Settings and provider names are supplied at construction; storage services
used by readiness are supplied by the application lifespan.
"""

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
    """Report process liveness and configured provider names without probing I/O."""
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
    """Probe cache stats, the enabled dataset catalog and coordination threshold.

    The dataset catalog checks its repository only when configured. This path
    does not probe generation, embeddings or the run-history repository, and
    does not prove that every later storage operation will succeed.

    Args:
        request: Request whose application has completed lifespan startup.

    Returns:
        Configured cache and dataset storage modes on success. Cache,
        coordination and dataset storage errors produce a safe ``not_ready``
        HTTP 503 response; other failures use the normal exception boundary.
    """
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
