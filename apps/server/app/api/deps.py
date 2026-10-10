"""Borrow application-state dependencies established by successful startup.

The lifespan publishes benchmark_service, semantic_cache, query_service,
runtime_metrics, embedding_provider and generation_provider. The matching
get_* functions retrieve those objects for FastAPI Depends; casts do not
construct resources, validate state or add cleanup. Callers need the matching
state initialized by the lifespan or an explicit dependency override.

Services and adapters borrow the lifespan-managed HTTP client and optional
database/cache resources. These getters do not transfer ownership or open a
client, pool or service for each request; startup failure can leave state
unavailable. Optional repositories are configured inside the shared services.
"""

from typing import cast

from fastapi import Request

from app.benchmark.application.service import BenchmarkService
from app.cache.application.service import SemanticCache
from app.observability.metrics import RuntimeMetrics
from app.providers.protocols import (
    EmbeddingProvider,
    GenerationProvider,
)
from app.query.application.service import QueryService


def get_benchmark_service(request: Request) -> BenchmarkService:
    return cast(
        BenchmarkService,
        request.app.state.benchmark_service,
    )


def get_semantic_cache(request: Request) -> SemanticCache:
    return cast(
        SemanticCache,
        request.app.state.semantic_cache,
    )


def get_query_service(request: Request) -> QueryService:
    return cast(
        QueryService,
        request.app.state.query_service,
    )


def get_runtime_metrics(request: Request) -> RuntimeMetrics:
    return cast(
        RuntimeMetrics,
        request.app.state.runtime_metrics,
    )


def get_embedding_provider(
    request: Request,
) -> EmbeddingProvider:
    return cast(
        EmbeddingProvider,
        request.app.state.embedding_provider,
    )


def get_generation_provider(
    request: Request,
) -> GenerationProvider:
    return cast(
        GenerationProvider,
        request.app.state.generation_provider,
    )
