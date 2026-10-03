# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Public exception types for the Semantix client."""


class SemantixError(Exception):
    """Base for all SDK errors; catch for one application-wide fallback."""


class SemantixConfigurationError(SemantixError):
    """Invalid URL, token, or timeout detected during construction."""


class SemantixTransportError(SemantixError):
    """Network failure; catch with :class:`SemantixTimeoutError` if alike."""


class SemantixTimeoutError(SemantixTransportError):
    """HTTP connect, read, write, or pool timeout; outcome may be unknown."""


class SemantixResponseError(SemantixError):
    """Successful HTTP response violates the expected JSON contract."""


class SemantixAPIError(SemantixError):
    """Non-success HTTP response; catch for all server rejections.

    Attributes:
        status_code: HTTP response status.
        error_code: Bounded server error code, or ``"http_error"``.
        detail: Bounded safe server detail, possibly ``None``.
        retry_after_seconds: Positive integer Retry-After delay if present;
            otherwise ``None``. The SDK never retries automatically.
    """

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        detail: str | None,
        retry_after_seconds: int | None = None,
    ) -> None:
        message = detail or "The Semantix server rejected the request."
        super().__init__(f"{message} (HTTP {status_code}, {error_code})")
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


class SemantixAuthenticationError(SemantixAPIError):
    """HTTP 401: missing or invalid bearer authentication."""


class SemantixAuthorizationError(SemantixAPIError):
    """HTTP 403: role or namespace permission is insufficient."""


class SemantixRateLimitError(SemantixAPIError):
    """HTTP 429: rate limited; inspect ``retry_after_seconds``."""


class SemantixValidationError(SemantixAPIError):
    """HTTP 422: query input or policy violates server validation."""


class SemantixServerError(SemantixAPIError):
    """HTTP 5xx: server failure, including readiness HTTP 503."""
