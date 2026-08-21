from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_benchmark_service, get_runtime_metrics, get_semantic_cache
from app.benchmark.application.service import BenchmarkService
from app.cache.application.service import SemanticCache
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.middleware.rate_limit import app_rate_limit, limiter
from app.observability.metrics import RuntimeMetrics
from app.observability.schemas import MetricsResponse, RuntimeDiagnosticsResponse
from app.security.auth import GlobalAdminPrincipal

router = APIRouter(prefix="/api/v1", tags=["observability"])
MetricsDependency = Annotated[RuntimeMetrics, Depends(get_runtime_metrics)]
CacheDependency = Annotated[SemanticCache, Depends(get_semantic_cache)]
BenchmarkDependency = Annotated[BenchmarkService, Depends(get_benchmark_service)]


@router.get("/metrics", response_model=MetricsResponse)
@limiter.limit(app_rate_limit)
async def metrics(
    request: Request,
    runtime_metrics: MetricsDependency,
    cache: CacheDependency,
    principal: GlobalAdminPrincipal,
) -> MetricsResponse:
    cache_stats = await cache.stats()
    return MetricsResponse.from_snapshot(
        runtime_metrics.snapshot(cache_size=cache_stats.size)
    )


@router.get("/diagnostics", response_model=RuntimeDiagnosticsResponse)
@limiter.limit(app_rate_limit)
async def diagnostics(
    request: Request,
    cache: CacheDependency,
    benchmark: BenchmarkDependency,
    principal: GlobalAdminPrincipal,
) -> RuntimeDiagnosticsResponse:
    cache_readiness: Literal["ready", "unavailable"]
    try:
        await cache.stats()
        cache_readiness = "ready"
    except CacheStorageError:
        cache_readiness = "unavailable"

    settings = cast(Settings, request.app.state.settings)
    return RuntimeDiagnosticsResponse.from_runtime(
        benchmark.runtime_configuration,
        cache_backend=settings.cache_backend,
        cache_readiness=cache_readiness,
        max_request_body_bytes=settings.max_request_body_bytes,
    )
