from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_query_service
from app.middleware.rate_limit import app_rate_limit, limiter
from app.query.api.schemas import QueryRequest, QueryResponse
from app.query.application.service import QueryService
from app.security.auth import OperatorPrincipal, resolve_namespace

router = APIRouter(prefix="/api/v1", tags=["query"])
QueryServiceDependency = Annotated[QueryService, Depends(get_query_service)]


@router.post("/query", response_model=QueryResponse)
@limiter.limit(app_rate_limit)
async def query(
    request: Request,
    payload: QueryRequest,
    service: QueryServiceDependency,
    principal: OperatorPrincipal,
) -> QueryResponse:
    namespace = resolve_namespace(
        principal,
        payload.namespace,
        allow_global=False,
    )
    if namespace is None:
        raise RuntimeError("Query namespace authorization returned no namespace")
    return await service.execute(
        payload.prompt,
        policy=replace(payload.cache_policy, namespace=namespace),
    )
