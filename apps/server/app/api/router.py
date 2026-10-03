from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.benchmark.api.router import evaluations_router
from app.benchmark.api.router import router as benchmark_router
from app.cache.api.router import router as cache_router
from app.observability.router import router as observability_router
from app.query.api.router import router as query_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(query_router)
api_router.include_router(cache_router)
api_router.include_router(benchmark_router)
api_router.include_router(evaluations_router)
api_router.include_router(observability_router)
api_router.include_router(health_router)
