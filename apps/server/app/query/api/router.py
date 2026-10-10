"""Authorize interactive queries and delegate execution to QueryService.

POST /api/v1/query uses the configured route quota and an operator-or-higher
dependency. Resolve the validated request namespace before replacing the
policy's namespace and invoking the borrowed service. QueryRequest supplies
a concrete ``default`` namespace when omitted; it is still authorized.
The service owns cache-hit confirmation, generation and local coalescing;
this endpoint does not expose a conversation or session protocol.
"""

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
    """Execute one operator-authorized query in its permitted namespace.

    Returns:
        Answer and consistent hit/generation evidence from QueryService.execute.

    Raises:
        AuthorizationError: The requested namespace is outside the principal's
            permissions. Role enforcement occurs through the route dependency.
    """
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
