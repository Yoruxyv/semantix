# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Private sync and async HTTP transports owned by the public clients.

Each transport reuses one HTTPX connection pool. Requests use identity
encoding, bound raw response content before JSON decoding, and preserve HTTP
status categories when an error body is unusable. Public model validation
happens after this layer. Neither transport retries requests automatically.
"""

import contextlib
import json
import math
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import (
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixConfigurationError,
    SemantixRateLimitError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
    SemantixTransportError,
    SemantixValidationError,
)

_MAX_HTTP_RESPONSE_BYTES = 1_048_576
_MAX_ERROR_CODE_LENGTH = 100
_MAX_ERROR_DETAIL_LENGTH = 500


class _ResponseTooLargeError(Exception):
    pass


def _normalize_base_url(base_url: str) -> str:
    """Normalize an HTTP(S) URL with an optional deployment path prefix.

    Strip surrounding whitespace and trailing path slashes. Require a hostname
    and a valid parsed port; reject embedded credentials and nonempty query or
    fragment components. This does not check reachability or trusted destinations.
    """
    candidate = base_url.strip()
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as error:
        raise SemantixConfigurationError("The Semantix base URL is invalid.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise SemantixConfigurationError(
            "The Semantix base URL must be an HTTP(S) origin with an optional path."
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _timeout(value: float) -> httpx.Timeout:
    """Validate a positive finite number for HTTPX's four timeout phases.

    The value applies to connect, read, write and pool waits, rather than a total
    wall-clock deadline for the request.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SemantixConfigurationError("The Semantix timeout must be a number.")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise SemantixConfigurationError(
            "The Semantix timeout must be finite and greater than zero."
        )
    return httpx.Timeout(timeout)


def _headers(token: str | None) -> dict[str, str]:
    """Request JSON with identity encoding and the original optional token.

    Reject empty, all-whitespace or CR/LF-containing tokens; otherwise preserve
    the supplied value in the Bearer header. The server owns authentication and
    authorization; this helper does not substitute a token digest.
    """
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    if token is not None:
        if not token or token.isspace() or "\r" in token or "\n" in token:
            raise SemantixConfigurationError(
                "The Semantix bearer token must be a non-empty header value."
            )
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_content(response: httpx.Response) -> bytes:
    """Collect at most 1 MiB of raw streamed bytes, or already-consumed content.

    Raise the private size sentinel before adding a chunk that exceeds the bound.
    The caller's HTTPX stream context owns response closure, including on failure.
    """
    content = bytearray()
    chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
    for chunk in chunks:
        if len(content) + len(chunk) > _MAX_HTTP_RESPONSE_BYTES:
            raise _ResponseTooLargeError
        content.extend(chunk)
    return bytes(content)


async def _read_content_async(response: httpx.Response) -> bytes:
    """Apply the same 1 MiB bound while asynchronously reading raw chunks.

    Already-consumed responses use the synchronous reader. Response cleanup
    belongs to the caller's asynchronous stream context.
    """
    if response.is_stream_consumed:
        return _read_content(response)
    content = bytearray()
    async for chunk in response.aiter_raw():
        if len(content) + len(chunk) > _MAX_HTTP_RESPONSE_BYTES:
            raise _ResponseTooLargeError
        content.extend(chunk)
    return bytes(content)


def _is_json_response(response: httpx.Response) -> bool:
    """Accept application/json or a media type ending in +json, ignoring parameters."""
    media_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip()
    return media_type == "application/json" or media_type.endswith("+json")


def _reject_encoded_response(response: httpx.Response, token: str | None) -> None:
    """Accept absent/identity encoding before reading the response body.

    Other encodings raise a response error on success or a status-classified API
    error without body details on HTTP failure.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding in {"", "identity"}:
        return
    if not response.is_success:
        _raise_api_error(response, None, token=token)
    raise SemantixResponseError(
        "The Semantix server returned an unexpected content encoding."
    )


def _json(content: bytes) -> object:
    """Decode JSON bytes, translating Unicode and JSON syntax failures."""
    try:
        return cast(object, json.loads(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SemantixResponseError(
            "The Semantix server returned malformed JSON."
        ) from error


def _safe_text(value: object, *, limit: int, token: str | None) -> str | None:
    """Replace C0 controls, redact exact token matches, then truncate text.

    Empty or non-string fields become None. Token matching occurs after control
    replacement; this is limited sanitization, not detection of arbitrary secrets.
    """
    if not isinstance(value, str) or not value:
        return None
    sanitized = "".join(
        " " if ord(character) < 32 else character for character in value
    )
    if token:
        sanitized = sanitized.replace(token, "[redacted]")
    return sanitized[:limit]


def _retry_after(response: httpx.Response) -> int | None:
    """Parse a positive integer delay; dates and nonpositive values give None."""
    value = response.headers.get("retry-after", "").strip()
    if not value.isdigit():
        return None
    seconds = int(value)
    return seconds if seconds > 0 else None


def _raise_api_error(
    response: httpx.Response,
    payload: object | None,
    *,
    token: str | None,
) -> None:
    """Raise a status-classified error with bounded, sanitized body fields.

    Codes are limited to 100 characters and details to 500. Unusable fields fall
    back to http_error and None. Map 401/403/422/429 to their dedicated errors and
    5xx to server errors; other non-success statuses use SemantixAPIError.
    Retry-After is exposed as metadata, without scheduling a retry.
    """
    data = cast("dict[object, object]", payload) if isinstance(payload, dict) else {}
    error_code = (
        _safe_text(
            data.get("error"),
            limit=_MAX_ERROR_CODE_LENGTH,
            token=token,
        )
        or "http_error"
    )
    detail = _safe_text(
        data.get("detail"),
        limit=_MAX_ERROR_DETAIL_LENGTH,
        token=token,
    )
    exception_type: type[SemantixAPIError]
    if response.status_code == 401:
        exception_type = SemantixAuthenticationError
    elif response.status_code == 403:
        exception_type = SemantixAuthorizationError
    elif response.status_code == 422:
        exception_type = SemantixValidationError
    elif response.status_code == 429:
        exception_type = SemantixRateLimitError
    elif response.status_code >= 500:
        exception_type = SemantixServerError
    else:
        exception_type = SemantixAPIError
    raise exception_type(
        status_code=response.status_code,
        error_code=error_code,
        detail=detail,
        retry_after_seconds=_retry_after(response),
    )


def _decode_response(
    response: httpx.Response, content: bytes, token: str | None
) -> object:
    """Decode success JSON or preserve an HTTP failure's status category.

    Success requires an accepted JSON media type and parseable content. On HTTP
    failure, malformed or non-JSON content falls back to a generic API error body;
    valid JSON may supply bounded error/detail fields. Typed models are decoded
    separately by the public client.
    """
    if not response.is_success:
        payload = None
        if _is_json_response(response):
            with contextlib.suppress(SemantixResponseError):
                payload = _json(content)
        _raise_api_error(response, payload, token=token)
    if not _is_json_response(response):
        raise SemantixResponseError(
            "The Semantix server returned an unexpected content type."
        )
    return _json(content)


class _SyncTransport:
    """Own a pooled HTTPX Client until the public client closes it.

    The optional injected transport is an internal test seam, not a public
    extension API or a borrowed HTTPX client.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.Client(
            base_url=f"{_normalize_base_url(base_url)}/",
            headers=_headers(token),
            timeout=_timeout(timeout),
            transport=transport,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        """Send one request and close its stream before decoding the JSON body.

        Encoded or oversized HTTP failures retain status-based API errors without
        body details; equivalent successful responses raise SemantixResponseError.
        Translate HTTPX timeouts and request errors to SDK transport errors. No retry
        occurs, and a failed local request does not establish the remote outcome.
        """
        try:
            with self._client.stream(method, path, json=payload) as response:
                _reject_encoded_response(response, self._token)
                try:
                    content = _read_content(response)
                except _ResponseTooLargeError:
                    if not response.is_success:
                        _raise_api_error(response, None, token=self._token)
                    raise SemantixResponseError(
                        "The Semantix response exceeded the client safety limit."
                    ) from None
        except httpx.TimeoutException as error:
            raise SemantixTimeoutError("The Semantix request timed out.") from error
        except httpx.RequestError as error:
            raise SemantixTransportError(
                "The Semantix server could not be reached."
            ) from error
        return _decode_response(response, content, self._token)

    def close(self) -> None:
        """Close the owned synchronous HTTPX connection pool."""
        self._client.close()


class _AsyncTransport:
    """Own a pooled HTTPX AsyncClient until the public client awaits closure.

    Keep asynchronous stream and pool cleanup separate from the sync transport.
    The optional transport argument is an internal test seam.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=f"{_normalize_base_url(base_url)}/",
            headers=_headers(token),
            timeout=_timeout(timeout),
            transport=transport,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        """Await one request with the same bounds and status mapping as sync.

        The HTTPX asynchronous stream context handles response cleanup. Cancellation
        propagates; neither cancellation nor a transport error proves that remote
        generation or cache writes were rolled back. Requests are not retried.
        """
        try:
            async with self._client.stream(method, path, json=payload) as response:
                _reject_encoded_response(response, self._token)
                try:
                    content = await _read_content_async(response)
                except _ResponseTooLargeError:
                    if not response.is_success:
                        _raise_api_error(response, None, token=self._token)
                    raise SemantixResponseError(
                        "The Semantix response exceeded the client safety limit."
                    ) from None
        except httpx.TimeoutException as error:
            raise SemantixTimeoutError("The Semantix request timed out.") from error
        except httpx.RequestError as error:
            raise SemantixTransportError(
                "The Semantix server could not be reached."
            ) from error
        return _decode_response(response, content, self._token)

    async def close(self) -> None:
        """Close the owned asynchronous HTTPX connection pool."""
        await self._client.aclose()
