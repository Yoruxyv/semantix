import logging
from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict, cast

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)


class PublicErrorIssue(TypedDict):
    code: str
    detail: str
    pointer: str
    case_id: NotRequired[str]
    case_index: NotRequired[int]


class AppError(Exception):
    status_code = 500
    error_code = "internal_error"
    public_detail: str | None = None

    def __init__(
        self,
        *args: object,
        headers: Mapping[str, str] | None = None,
        issues: Sequence[PublicErrorIssue] | None = None,
    ) -> None:
        super().__init__(*args)
        self.headers = dict(headers or {})
        self.issues = list(issues) if issues is not None else None


class AuthenticationRequiredError(AppError):
    status_code, error_code, public_detail = (
        401,
        "authentication_required",
        "A valid bearer token is required.",
    )


class AuthenticationTemporarilyLockedError(AppError):
    status_code, error_code, public_detail = (
        429,
        "authentication_temporarily_locked",
        "Too many failed authentication attempts. Please try again later.",
    )

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


class AuthorizationError(AppError):
    status_code, error_code, public_detail = (
        403,
        "forbidden",
        "The authenticated principal is not permitted to perform this operation.",
    )


class EmbeddingError(AppError):
    status_code, error_code, public_detail = (
        502,
        "embedding_error",
        "The embedding service returned an invalid result.",
    )


class CacheStorageError(AppError):
    status_code, error_code, public_detail = (
        500,
        "cache_error",
        "The cache could not process the request.",
    )


class DatabaseStorageError(AppError):
    status_code, error_code, public_detail = (
        500,
        "database_error",
        "A required database operation could not be completed.",
    )


class CoordinationStorageError(AppError):
    status_code, error_code, public_detail = (
        503,
        "coordination_unavailable",
        "A required coordination service is temporarily unavailable.",
    )


class SharedRateLimitExceeded(AppError):  # noqa: N818 - established domain name
    status_code, error_code, public_detail = (
        429,
        "rate_limit_exceeded",
        "Too many requests. Please try again later.",
    )


class EvaluationDatasetStorageError(AppError):
    status_code, error_code, public_detail = (
        500,
        "evaluation_dataset_storage_error",
        "The persistent evaluation dataset catalog could not process the request.",
    )


class EvaluationRunHistoryStorageError(AppError):
    status_code, error_code, public_detail = (
        500,
        "evaluation_run_history_storage_error",
        "The evaluation run history could not process the request.",
    )


class EvaluationRunHistoryDisabledError(AppError):
    status_code, error_code, public_detail = (
        409,
        "evaluation_run_history_disabled",
        "Durable evaluation run history is not enabled.",
    )


class EvaluationRunHistoryNotFoundError(AppError):
    status_code, error_code, public_detail = (
        404,
        "evaluation_run_history_not_found",
        "The requested evaluation run history does not exist or has expired.",
    )


class EvaluationDatasetPersistenceDisabledError(AppError):
    status_code, error_code, public_detail = (
        409,
        "evaluation_dataset_persistence_disabled",
        "Persistent evaluation dataset storage is not enabled.",
    )


class EvaluationDatasetCapacityError(AppError):
    status_code, error_code, public_detail = (
        409,
        "evaluation_dataset_capacity_exceeded",
        "The namespace has reached its persistent evaluation dataset limit.",
    )


class EvaluationDatasetRetentionError(AppError):
    status_code, error_code, public_detail = (
        422,
        "evaluation_dataset_retention_invalid",
        "The requested dataset retention exceeds the configured bound.",
    )


class EvaluationDatasetNotFoundError(AppError):
    status_code, error_code, public_detail = (
        404,
        "evaluation_dataset_not_found",
        "The requested evaluation dataset does not exist or has expired.",
    )


class CacheEntryNotFoundError(AppError):
    status_code, error_code, public_detail = (
        404,
        "cache_entry_not_found",
        "The requested cache entry does not exist or has expired.",
    )


class ProviderRetryableError(AppError):
    status_code, error_code, public_detail = (
        503,
        "service_unavailable",
        "The AI service is temporarily unavailable.",
    )


class ProviderAuthenticationError(AppError):
    status_code, error_code, public_detail = (
        503,
        "service_configuration_error",
        "The AI service is temporarily unavailable.",
    )


class ProviderRequestError(AppError):
    status_code, error_code, public_detail = (
        502,
        "upstream_error",
        "The AI service could not process the request.",
    )


class InvalidProviderResponseError(AppError):
    status_code, error_code, public_detail = (
        502,
        "invalid_upstream_response",
        "The AI service returned an invalid response.",
    )


class EvaluationTimeoutError(AppError):
    status_code, error_code, public_detail = (
        504,
        "evaluation_timeout",
        "The evaluation exceeded its configured wall-clock limit.",
    )


def _response(
    status: int,
    error: str,
    detail: str | None,
    *,
    headers: Mapping[str, str] | None = None,
    issues: Sequence[PublicErrorIssue] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    if status == 401:
        response_headers.setdefault("WWW-Authenticate", "Bearer")
    content: dict[str, object] = {"error": error, "detail": detail}
    if issues is not None:
        content["issues"] = list(issues)
    return JSONResponse(
        status_code=status,
        content=content,
        headers=response_headers or None,
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = cast(AppError, exc)
    logger.warning(
        "Application error type=%s path=%s", type(error).__name__, request.url.path
    )
    return _response(
        error.status_code,
        error.error_code,
        error.public_detail,
        headers=error.headers,
        issues=error.issues,
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast(RequestValidationError, exc)
    locations = {".".join(str(part) for part in item["loc"]) for item in error.errors()}
    return _response(
        422, "validation_error", "Invalid field: " + ", ".join(sorted(locations))
    )


async def rate_limit_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    cast(RateLimitExceeded, exc)
    return _response(
        429, "rate_limit_exceeded", "Too many requests. Please try again later."
    )


async def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    error = cast(HTTPException, exc)
    return _response(
        error.status_code,
        "http_error",
        error.detail if isinstance(error.detail, str) else None,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error path=%s type=%s",
        request.url.path,
        type(exc).__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _response(500, "internal_error", None)
