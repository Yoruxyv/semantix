"""Apply configured route quotas using local or PostgreSQL coordination.

Local buckets use the application's unique scope, resolved address and
quota. Shared buckets use address, route template and quota in PostgreSQL;
replicas must share that authority and compatible settings. Only decorated
routes consume these quotas; authentication bootstrap and health probes do
not. Session lockouts have a separate policy in ``app.api.auth``.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from fastapi import Request
from slowapi import Limiter

from app.core.config import Settings
from app.core.exceptions import SharedRateLimitExceeded
from app.infrastructure.coordination import PostgresCoordination
from app.middleware.client_address import client_address

P = ParamSpec("P")
R = TypeVar("R")
PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def app_rate_limit(key: str) -> str:
    """Extract the quota embedded in the local limiter's application key."""
    return key.rsplit("|", maxsplit=1)[1]


def _app_scoped_client_address(request: Request) -> str:
    settings: Settings = request.app.state.settings
    scope: str = request.app.state.rate_limit_scope
    return f"{scope}|{client_address(request)}|{settings.rate_limit}"


class CoordinationLimiter:
    """Select the configured admission authority for decorated async routes.

    PostgreSQL denial raises SharedRateLimitExceeded; coordination failures
    propagate without falling back to local counters. Local SlowAPI denials
    and shared denials both have public HTTP 429 handlers.
    """

    def __init__(self) -> None:
        self.local = Limiter(key_func=_app_scoped_client_address)

    def limit(
        self, limit_value: Callable[[str], str]
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Decorate a route that receives Request as the ``request`` keyword.

        Args:
            limit_value: SlowAPI quota callback for local coordination, normally
                app_rate_limit. PostgreSQL coordination uses settings.rate_limit.

        Returns:
            Signature-preserving decorator admitting requests before calling the
            route. A missing Request raises TypeError; denials and storage failures
            propagate to the registered HTTP handlers.
        """

        def decorate(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            # SlowAPI returns a bare Callable; pin its signature at this boundary.
            local = cast(Callable[P, Awaitable[R]], self.local.limit(limit_value)(func))  # pyright: ignore[reportUnknownMemberType]

            @wraps(func)
            async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
                request = kwargs.get("request")
                if not isinstance(request, Request):
                    raise TypeError("A rate-limited route requires Request")
                request = cast(Request, request)
                settings: Settings = request.app.state.settings
                if settings.coordination_backend == "memory":
                    return await local(*args, **kwargs)

                amount_text, period = settings.rate_limit.split("/", maxsplit=1)
                route = request.scope.get("route")
                route_path = cast(str, getattr(route, "path", request.url.path))
                coordinator = cast(PostgresCoordination, request.app.state.coordination)
                allowed = await coordinator.allow_request(
                    client_address(request),
                    route_path,
                    settings.rate_limit,
                    int(amount_text),
                    PERIOD_SECONDS[period],
                )
                if not allowed:
                    raise SharedRateLimitExceeded
                return await func(*args, **kwargs)

            return wrapped

        return decorate


limiter = CoordinationLimiter()
