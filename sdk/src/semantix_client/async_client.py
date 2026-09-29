# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Asynchronous Semantix client."""

from types import TracebackType

import httpx

from ._transport import _AsyncTransport
from .models import (
    HealthStatus,
    QueryResult,
    ReadinessStatus,
    _decode_health,
    _decode_query_result,
    _decode_readiness,
)
from .policies import CachePolicy, _policy_fields


class AsyncSemantixClient:
    """Asynchronous client for the public Semantix HTTP API.

    Share one instance across concurrent tasks and close it during shutdown.
    It owns one pooled asynchronous HTTP client.

    Args:
        base_url: HTTP or HTTPS URL for the Semantix server.
        token: Optional bearer token sent to the server.
        timeout: Positive connect, read, write, and pool timeout in seconds;
            default ``30.0``. It is not a whole-request deadline.

    Raises:
        SemantixConfigurationError: URL, token, or timeout is invalid.

    Example:
        >>> async def main():
        ...     async with AsyncSemantixClient(base_url="http://localhost:8000") as client:
        ...         result = await client.query("Explain semantic caching")
        ...         print(result.response)
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._transport = _AsyncTransport(
            base_url=base_url,
            token=token,
            timeout=timeout,
        )

    @classmethod
    def _for_test(
        cls,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> "AsyncSemantixClient":
        client = cls.__new__(cls)
        client._transport = _AsyncTransport(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
        return client

    async def query(
        self,
        prompt: str,
        *,
        namespace: str = "default",
        policy: CachePolicy = CachePolicy.NORMAL,
        cache_ttl_seconds: int | None = None,
    ) -> QueryResult:
        """Submit a query and decode its cache-decision evidence.

        Args:
            prompt: Nonempty prompt, sanitized and bounded by the server.
            namespace: Concrete authorized namespace; ``*`` is invalid. Defaults
                to ``"default"``. The server enforces authorization.
            policy: Cache behavior; defaults to :attr:`CachePolicy.NORMAL`.
            cache_ttl_seconds: Optional lifetime in ``1..31_536_000``, valid
                only with NORMAL or REFRESH. A finite server default caps it.

        Returns:
            Immutable query evidence. A coalesced miss may skip generation
            while another request calls the provider.

        Raises:
            SemantixAPIError: The server rejects or fails the request.
            SemantixAuthenticationError: The bearer token is missing or invalid.
            SemantixAuthorizationError: The namespace or role is unauthorized.
            SemantixValidationError: The server rejects prompt, namespace, or TTL.
            SemantixRateLimitError: The server responds with HTTP 429.
            SemantixServerError: The server responds with HTTP 5xx.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached.
            SemantixTimeoutError: An HTTP timeout elapses.
        """
        payload: dict[str, object] = {
            "prompt": prompt,
            "namespace": namespace,
            **_policy_fields(policy),
        }
        if cache_ttl_seconds is not None:
            payload["cache_ttl_seconds"] = cache_ttl_seconds
        return _decode_query_result(
            await self._transport.request("POST", "api/v1/query", payload=payload)
        )

    async def health(self) -> HealthStatus:
        """Return public liveness information from the server.

        Returns:
            Immutable provider-category health evidence.

        Raises:
            SemantixAPIError: The server rejects the request.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached.
            SemantixTimeoutError: An HTTP timeout elapses.
        """
        return _decode_health(await self._transport.request("GET", "health"))

    async def ready(self) -> ReadinessStatus:
        """Return public dependency-readiness information from the server.

        Returns:
            Immutable active-storage readiness evidence.

        Raises:
            SemantixServerError: The server reports HTTP 503 when not ready.
            SemantixAPIError: Another non-success HTTP response occurs.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached.
            SemantixTimeoutError: An HTTP timeout elapses.
        """
        return _decode_readiness(await self._transport.request("GET", "ready"))

    async def aclose(self) -> None:
        """Close the owned asynchronous HTTP connection pool."""
        await self._transport.close()

    async def __aenter__(self) -> "AsyncSemantixClient":
        """Return this client for a managed ``async with`` block."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the owned pool when leaving an ``async with`` block."""
        await self.aclose()
