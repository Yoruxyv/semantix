# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Typed synchronous and asynchronous clients for the Semantix HTTP API.

The ``semantix-client`` distribution imports as ``semantix_client`` and requires
an already-running compatible Semantix FastAPI server. It sends requests and
decodes typed responses; embedding, generation, cache state and authorization
belong to that server. For in-process semantic caching without a server, use the
separate ``semantix-cache`` / ``semantix_cache`` package and AsyncSemanticCache.

This maintained optional/reference client is distinct from the primary intended
first public PyPI distribution, semantix-cache.

Public surface and lifecycle
----------------------------
``SemantixClient`` is synchronous; ``AsyncSemantixClient`` is asynchronous. Both
provide ``query()``, ``health()`` and ``ready()``. QueryResult describes response
text and server-reported cache/generation evidence; HealthStatus and
ReadinessStatus describe liveness and dependency readiness. ``CachePolicy``
selects the server's supported cache-read/write behavior.

Reuse one client across requests for HTTP connection pooling. Each owns its
HTTPX client: use ``with`` / ``async with``, or call ``close()`` /
``await aclose()`` at application shutdown. The package does not start the server
or provide a local cache fallback.

Connection and errors
---------------------
The application supplies ``base_url`` (HTTP(S), with an optional deployment path),
a bearer ``token`` when required, and a positive finite ``timeout``. URL selection,
credential storage and server availability remain application responsibilities.
The default timeout is 30 seconds for HTTP connect/read/write/pool waits, not a
whole-request deadline. The server enforces roles and namespace access.

All exported errors derive from ``SemantixError``. Configuration errors concern
client setup; transport/timeout errors concern HTTP communication;
``SemantixResponseError`` indicates an invalid response contract. API status errors
include authentication, authorization, validation, rate-limit and server failures.
``SemantixRateLimitError.retry_after_seconds`` exposes a parsed positive Retry-After
value when supplied. The client does not automatically retry a generation POST;
retry/idempotency decisions belong to the application.

Usage with a compatible running server
--------------------------------------
These functions share the same public contract and close their owned connections.
Pass a token from your application's credential source if the server requires it::

    from semantix_client import AsyncSemantixClient, SemantixClient

    def ask_sync(base_url: str, token: str | None = None):
        with SemantixClient(base_url=base_url, token=token, timeout=10.0) as client:
            return client.query("Explain semantic caching", namespace="support")

    async def ask_async(base_url: str, token: str | None = None):
        async with AsyncSemantixClient(
            base_url=base_url, token=token, timeout=10.0
        ) as client:
            return await client.query(
                "Explain semantic caching", namespace="support"
            )

For example, call ``ask_sync("http://127.0.0.1:8000")`` for a local server that
permits unauthenticated access to ``support``. In an async application, await
``ask_async`` with your deployment URL and authorized credentials.

Finding the contract
--------------------
Use ``help(SemantixClient)`` or ``help(AsyncSemantixClient)`` for exact signatures;
``models``, ``policies`` and ``errors`` define the returned evidence and failures.
Runtime dependencies are the standard library and HTTPX; server, database,
Pydantic and embedded-cache packages are not imported. Full usage and compatibility:
https://github.com/Yoruxyv/semantix/blob/main/packages/client/README.md.
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
