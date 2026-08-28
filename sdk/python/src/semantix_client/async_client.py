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

    Args:
        base_url: HTTP or HTTPS URL for the Semantix server.
        token: Optional bearer token sent to the server.
        timeout: Finite request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        _http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = _AsyncTransport(
            base_url=base_url,
            token=token,
            timeout=timeout,
            transport=_http_transport,
        )

    async def query(
        self,
        prompt: str,
        *,
        namespace: str = "default",
        policy: CachePolicy = CachePolicy.NORMAL,
    ) -> QueryResult:
        """Submit a query to Semantix.

        Args:
            prompt: User prompt sent through the public query API.
            namespace: Concrete server-authorized cache namespace.
            policy: Cache read/write behavior for this request.

        Returns:
            Immutable query evidence returned by Semantix.

        Raises:
            SemantixAPIError: The server rejects or fails the request.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached or times out.
        """
        payload: dict[str, object] = {
            "prompt": prompt,
            "namespace": namespace,
            **_policy_fields(policy),
        }
        return _decode_query_result(
            await self._transport.request("POST", "api/v1/query", payload=payload)
        )

    async def health(self) -> HealthStatus:
        """Return public liveness information from the server.

        Returns:
            Immutable provider-category health evidence.

        Raises:
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached or times out.
        """
        return _decode_health(await self._transport.request("GET", "health"))

    async def ready(self) -> ReadinessStatus:
        """Return public dependency-readiness information from the server.

        Returns:
            Immutable active-storage readiness evidence.

        Raises:
            SemantixAPIError: The server reports that it is not ready.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached or times out.
        """
        return _decode_readiness(await self._transport.request("GET", "ready"))

    async def aclose(self) -> None:
        """Close the owned asynchronous HTTP connection pool."""
        await self._transport.close()

    async def __aenter__(self) -> "AsyncSemantixClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
