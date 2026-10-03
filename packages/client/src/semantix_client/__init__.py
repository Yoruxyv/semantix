# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Optional/reference typed HTTP clients for a running Semantix FastAPI server.

The semantix-client distribution imports as semantix_client. It talks to an
already-running compatible Semantix server over its public HTTP API and does not
provide the embedded semantic-cache engine. The separate semantix-cache package
(import semantix_cache) supplies in-process caching.

SemantixClient is synchronous; AsyncSemantixClient is asynchronous. Both return
typed query/health/readiness models and raise the exported SemantixError family.
Reuse a client for multiple requests. Each owns its pooled HTTP client: use with
or async with, or call close() / await aclose() at application shutdown.

For a compatible local server::

    from semantix_client import AsyncSemantixClient, SemantixClient

    with SemantixClient(base_url="http://127.0.0.1:8000") as client:
        status = client.health()

    async def health():
        async with AsyncSemantixClient(
            base_url="http://127.0.0.1:8000"
        ) as client:
            return await client.health()

Supply token= when the server requires bearer authentication. The package README
contains the supported request contracts and full lifecycle guidance.
"""

from .async_client import AsyncSemantixClient
from .client import SemantixClient
from .errors import (
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixConfigurationError,
    SemantixError,
    SemantixRateLimitError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
    SemantixTransportError,
    SemantixValidationError,
)
from .models import HealthStatus, QueryResult, ReadinessStatus
from .policies import CachePolicy

__all__ = [
    "AsyncSemantixClient",
    "CachePolicy",
    "HealthStatus",
    "QueryResult",
    "ReadinessStatus",
    "SemantixAPIError",
    "SemantixAuthenticationError",
    "SemantixAuthorizationError",
    "SemantixClient",
    "SemantixConfigurationError",
    "SemantixError",
    "SemantixRateLimitError",
    "SemantixResponseError",
    "SemantixServerError",
    "SemantixTimeoutError",
    "SemantixTransportError",
    "SemantixValidationError",
]
