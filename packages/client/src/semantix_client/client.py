# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Synchronous Semantix client."""

from types import TracebackType

import httpx

from ._transport import _SyncTransport
from .models import (
    HealthStatus,
    QueryResult,
    ReadinessStatus,
    _decode_health,
    _decode_query_result,
    _decode_readiness,
)
from .policies import CachePolicy, _policy_fields


class SemantixClient:
    """Synchronous client for the public Semantix HTTP API.

    Reuse one instance for many requests. It owns a pooled HTTP client; close it
    during shutdown or use a context manager. A running Semantix server is required.

    Args:
        base_url: HTTP or HTTPS URL for the Semantix server.
        token: Optional bearer token sent to the server.
        timeout: Positive timeout for HTTP connect, read, write, and pool waits,
            in seconds; default ``30.0``. It is not a whole-request deadline.

    Raises:
        SemantixConfigurationError: URL, token, or timeout is invalid.

    Example:
        >>> with SemantixClient(base_url="http://localhost:8000") as client:
        ...     result = client.query("Explain semantic caching")
        ...     print(result.response)
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._transport = _SyncTransport(
            base_url=base_url,
            token=token,
            timeout=timeout,
        )

    @classmethod
    def _for_test(
        cls,
        *,
        base_url: str,
        transport: httpx.BaseTransport,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> "SemantixClient":
        client = cls.__new__(cls)
        client._transport = _SyncTransport(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
        return client

    def query(
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
            cache_ttl_seconds: Optional requested lifetime in ``1..31_536_000``.
                Valid only with NORMAL or REFRESH. A finite server default caps
                the request; omission uses the server default.

        Returns:
            Immutable query evidence. A hit skips generation; a coalesced miss
            can also skip generation while another request calls the provider.

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
            self._transport.request("POST", "api/v1/query", payload=payload)
        )

    def health(self) -> HealthStatus:
        """Return public liveness information from the server.

        Returns:
            Immutable provider-category health evidence.

        Raises:
            SemantixAPIError: The server rejects the request.
            SemantixResponseError: The response violates the public contract.
            SemantixTransportError: The server cannot be reached.
            SemantixTimeoutError: An HTTP timeout elapses.
        """
        return _decode_health(self._transport.request("GET", "health"))

    def ready(self) -> ReadinessStatus:
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
        return _decode_readiness(self._transport.request("GET", "ready"))

    def close(self) -> None:
        """Close the owned HTTP connection pool."""
        self._transport.close()

    def __enter__(self) -> "SemantixClient":
        """Return this client for a managed ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the owned connection pool when leaving a ``with`` block."""
        self.close()
