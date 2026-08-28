"""Typed clients for the public Semantix HTTP API."""

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
