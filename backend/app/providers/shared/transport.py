"""Retrying JSON transport shared by HTTP provider adapters."""

import asyncio
import json
from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import cast

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.config import (
    DEFAULT_PROVIDER_MAX_RESPONSE_BYTES as _DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
)
from app.core.exceptions import (
    InvalidProviderResponseError,
    ProviderAuthenticationError,
    ProviderRequestError,
    ProviderRetryableError,
)

RetryFactory = Callable[[], AsyncRetrying]
DEFAULT_PROVIDER_MAX_RESPONSE_BYTES = _DEFAULT_PROVIDER_MAX_RESPONSE_BYTES
_STREAM_CHUNK_BYTES = 64 * 1024


class _ProviderResponseTooLargeError(InvalidProviderResponseError):
    """Non-retryable rejection of an oversized decoded provider response."""


class _ProviderOperationDeadlineExceeded(Exception):
    """Internal signal for synchronous work crossing the operation deadline."""


def create_retry_factory(
    *,
    attempts: int,
    multiplier_seconds: float,
    max_wait_seconds: float,
) -> RetryFactory:
    def retry_factory() -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception_type(
                ProviderRetryableError,
            ),
            stop=stop_after_attempt(attempts),
            wait=wait_random_exponential(
                multiplier=multiplier_seconds,
                max=max_wait_seconds,
            ),
            reraise=True,
        )

    return retry_factory


async def post_json(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    headers: Mapping[str, str],
    body: dict[str, object],
    retry_factory: RetryFactory,
    max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
) -> object:
    loop = asyncio.get_running_loop()
    timeout_seconds = client.timeout.read
    deadline = None if timeout_seconds is None else loop.time() + timeout_seconds
    operation_timeout = asyncio.timeout_at(deadline)

    try:
        async with operation_timeout:
            async for attempt in retry_factory():
                with attempt:
                    result = await _post_once(
                        client,
                        endpoint,
                        headers=headers,
                        body=body,
                        max_response_bytes=max_response_bytes,
                    )
                    if deadline is not None and loop.time() >= deadline:
                        raise _ProviderOperationDeadlineExceeded
                    return result
    except _ProviderOperationDeadlineExceeded as exc:
        raise ProviderRetryableError("Network failure") from exc
    except TimeoutError as exc:
        if not operation_timeout.expired():
            raise
        raise ProviderRetryableError("Network failure") from exc

    raise ProviderRetryableError("Retry policy ended")


async def _post_once(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    headers: Mapping[str, str],
    body: dict[str, object],
    max_response_bytes: int,
) -> object:
    request_headers = httpx.Headers(headers)
    request_headers["Accept-Encoding"] = "identity"
    try:
        async with client.stream(
            "POST",
            endpoint,
            headers=request_headers,
            json=body,
        ) as response:
            if (
                response.status_code == HTTPStatus.TOO_MANY_REQUESTS
                or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
            ):
                raise ProviderRetryableError(
                    f"Retryable status {response.status_code}",
                )

            if response.status_code in {
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
            }:
                raise ProviderAuthenticationError(
                    "Credentials rejected",
                )

            if response.status_code >= HTTPStatus.BAD_REQUEST:
                raise ProviderRequestError(
                    f"Provider returned status {response.status_code}",
                )

            response_body = await _read_response_body(
                response,
                max_response_bytes=max_response_bytes,
            )
    except httpx.RequestError as exc:
        raise ProviderRetryableError(
            "Network failure",
        ) from exc

    try:
        return cast(object, json.loads(response_body))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidProviderResponseError(
            "Malformed JSON",
        ) from exc


async def _read_response_body(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> bytes:
    content_encoding = response.headers.get("Content-Encoding")
    if (
        content_encoding is not None
        and content_encoding.strip()
        and content_encoding.strip().casefold() != "identity"
    ):
        raise InvalidProviderResponseError(
            "Provider returned an encoded response",
        )

    declared_length = _declared_content_length(response)
    if declared_length is not None and declared_length > max_response_bytes:
        raise _ProviderResponseTooLargeError(
            "Provider response exceeded maximum size",
        )

    response_body = bytearray()
    chunk_size = min(_STREAM_CHUNK_BYTES, max_response_bytes)
    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
        if len(response_body) + len(chunk) > max_response_bytes:
            raise _ProviderResponseTooLargeError(
                "Provider response exceeded maximum size",
            )
        response_body.extend(chunk)
    return bytes(response_body)


def _declared_content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    return int(value)
