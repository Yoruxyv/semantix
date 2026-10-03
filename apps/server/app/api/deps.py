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
