"""Private sync and async HTTP transport implementations."""

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
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SemantixConfigurationError("The Semantix timeout must be a number.")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise SemantixConfigurationError(
            "The Semantix timeout must be finite and greater than zero."
        )
    return httpx.Timeout(timeout)


def _headers(token: str | None) -> dict[str, str]:
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
    content = bytearray()
    chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
    for chunk in chunks:
        if len(content) + len(chunk) > _MAX_HTTP_RESPONSE_BYTES:
            raise _ResponseTooLargeError
        content.extend(chunk)
    return bytes(content)


async def _read_content_async(response: httpx.Response) -> bytes:
    if response.is_stream_consumed:
        return _read_content(response)
    content = bytearray()
    async for chunk in response.aiter_raw():
        if len(content) + len(chunk) > _MAX_HTTP_RESPONSE_BYTES:
            raise _ResponseTooLargeError
        content.extend(chunk)
    return bytes(content)


def _is_json_response(response: httpx.Response) -> bool:
    media_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip()
    return media_type == "application/json" or media_type.endswith("+json")


def _reject_encoded_response(response: httpx.Response, token: str | None) -> None:
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding in {"", "identity"}:
        return
    if not response.is_success:
        _raise_api_error(response, None, token=token)
    raise SemantixResponseError(
        "The Semantix server returned an unexpected content encoding."
    )


def _json(content: bytes) -> object:
    try:
        return cast(object, json.loads(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SemantixResponseError(
            "The Semantix server returned malformed JSON."
        ) from error


def _safe_text(value: object, *, limit: int, token: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    sanitized = "".join(
        " " if ord(character) < 32 else character for character in value
    )
    if token:
        sanitized = sanitized.replace(token, "[redacted]")
    return sanitized[:limit]


def _retry_after(response: httpx.Response) -> int | None:
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
    data = payload if isinstance(payload, dict) else {}
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
    if not response.is_success:
        payload = None
        if _is_json_response(response):
            try:
                payload = _json(content)
            except SemantixResponseError:
                pass
        _raise_api_error(response, payload, token=token)
    if not _is_json_response(response):
        raise SemantixResponseError(
            "The Semantix server returned an unexpected content type."
        )
    return _json(content)


class _SyncTransport:
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
        self._client.close()


class _AsyncTransport:
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
        await self._client.aclose()
