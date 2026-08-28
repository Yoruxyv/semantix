"""Public exception types for the Semantix client."""


class SemantixError(Exception):
    """Base class for all SDK-owned exceptions."""


class SemantixConfigurationError(SemantixError):
    """Raised when client configuration is invalid."""


class SemantixTransportError(SemantixError):
    """Raised when the server cannot be reached."""


class SemantixTimeoutError(SemantixTransportError):
    """Raised when the configured HTTP timeout elapses."""


class SemantixResponseError(SemantixError):
    """Raised when a successful server response violates the public contract."""


class SemantixAPIError(SemantixError):
    """Base class for typed HTTP error responses from Semantix."""

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
    """Raised when bearer authentication fails."""


class SemantixAuthorizationError(SemantixAPIError):
    """Raised when the authenticated principal lacks permission."""


class SemantixRateLimitError(SemantixAPIError):
    """Raised when the server rejects a request due to rate limiting."""


class SemantixValidationError(SemantixAPIError):
    """Raised when the server rejects request validation."""


class SemantixServerError(SemantixAPIError):
    """Raised when the server reports a 5xx failure."""
