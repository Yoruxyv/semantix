"""Borrowed HTTP transport for optional integrations, independent of the server."""

import asyncio
import json
from collections.abc import Callable
from types import TracebackType
from typing import Self, TypeVar
from urllib.parse import urlsplit

try:
    import httpx
except ModuleNotFoundError as exc:
    if exc.name != "httpx":
        raise
    raise ImportError(
        "Provider adapters require HTTP support: install 'semantix-cache[providers]'. "
        "Custom integrations need no extra: "
        "https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-providers.md"
    ) from None

from .._lifecycle import Lifecycle
from .._semantics import finite_number
from ..errors import (
    CacheConfigurationError,
    CacheValidationError,
    EmbeddingError,
    GenerationError,
)
from ..models import EmbeddingSpace

__all__ = ["httpx"]
Parsed = TypeVar("Parsed")


def positive_integer(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CacheConfigurationError("Expected a positive integer")
    return value


def configured_text(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise CacheConfigurationError("Expected explicit non-empty configuration text")
    return value


def provider_url(value: str, *, local: bool) -> str:
    configured_text(value)
    valid = False
    try:
        parsed = urlsplit(value)
        valid = bool(
            parsed.scheme in ({"http", "https"} if local else {"https"})
            and parsed.hostname
            and parsed.port != 0
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() for char in value)
            and "\\" not in value
            and (not local or parsed.path in ("", "/"))
        )
    except ValueError:
        pass
    if not valid:
        raise CacheConfigurationError(
            "Provider URL must be an absolute HTTPS URL without credentials, query "
            "or fragment; local Ollama also permits an HTTP origin"
        )
    return value.rstrip("/")


class HTTPAdapter:
    """Private base; closing seals the adapter and never closes its borrowed client."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        model: str,
        base_url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        error: type[EmbeddingError] | type[GenerationError],
        local: bool = False,
    ) -> None:
        if not isinstance(client, httpx.AsyncClient):
            raise CacheConfigurationError("Expected a borrowed httpx.AsyncClient")
        try:
            timeout = finite_number(timeout_seconds, minimum=0, maximum=float("inf"))
            if timeout == 0:
                raise ValueError("Timeout must be positive")
        except ValueError:
            raise CacheConfigurationError(
                "Provider timeout must be finite and positive"
            ) from None
        self._client = client
        self._model = configured_text(model)
        self._base_url = provider_url(base_url, local=local)
        self._headers = headers
        self._timeout_seconds = timeout
        self._max_response_bytes = positive_integer(max_response_bytes)
        self._error = error
        self._lifecycle = Lifecycle()

    async def _post(
        self, path: str, body: dict[str, object], parse: Callable[[object], Parsed]
    ) -> Parsed:
        failure = ""
        result: Parsed
        with self._lifecycle.operation():
            if self._client.is_closed:
                raise self._error("Borrowed HTTP client is closed") from RuntimeError(
                    "Borrowed HTTP client is closed"
                )
            deadline = asyncio.get_running_loop().time() + self._timeout_seconds
            try:
                async with (
                    asyncio.timeout_at(deadline),
                    self._client.stream(
                        "POST",
                        self._base_url + path,
                        headers={**self._headers, "Accept-Encoding": "identity"},
                        json=body,
                        timeout=self._timeout_seconds,
                        follow_redirects=False,
                    ) as response,
                ):
                    if not 200 <= response.status_code < 300:
                        failure = (
                            f"Provider returned HTTP status {response.status_code}"
                        )
                    elif response.headers.get(
                        "Content-Encoding", "identity"
                    ).lower() not in ("", "identity"):
                        failure = "Provider returned an encoded response"
                    else:
                        length = response.headers.get("Content-Length", "")
                        if response_too_large(length, self._max_response_bytes):
                            failure = "Provider response exceeded maximum size"
                        else:
                            data = bytearray()
                            async for chunk in response.aiter_bytes(
                                chunk_size=min(65536, self._max_response_bytes)
                            ):
                                if len(data) + len(chunk) > self._max_response_bytes:
                                    failure = "Provider response exceeded maximum size"
                                    break
                                data.extend(chunk)
                            if not failure:
                                try:
                                    payload = json.loads(data)
                                except (ValueError, RecursionError):
                                    failure = "Provider returned invalid JSON"
                                else:
                                    result = parse(payload)
                if asyncio.get_running_loop().time() >= deadline:
                    failure = "Provider request exceeded its deadline"
            except (TimeoutError, httpx.TimeoutException):
                failure = "Provider request exceeded its deadline"
            except httpx.HTTPError:
                failure = "Provider transport failed"
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            if failure:
                # Construct the cause outside the except block: raw HTTP/JSON exceptions
                # can contain private URLs, credentials or response bodies.
                raise self._error(failure) from RuntimeError(failure)
        return result

    async def aclose(self) -> None:
        self._lifecycle.close()

    async def __aenter__(self) -> Self:
        self._lifecycle.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


def checked_space(value: EmbeddingSpace) -> EmbeddingSpace:
    if not isinstance(value, EmbeddingSpace):
        raise CacheConfigurationError("Expected explicit EmbeddingSpace metadata")
    try:
        return EmbeddingSpace.model_validate(value.model_dump())
    except ValueError:
        raise CacheConfigurationError("Embedding metadata is invalid") from None


def request_text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or not 1 <= len(value) <= 2000:
        raise CacheValidationError(
            "Provider input must be non-empty text within 2000 characters"
        )


def configured_key(value: str) -> str:
    configured_text(value)
    if not value.isascii() or any(char.isspace() for char in value):
        raise CacheConfigurationError(
            "Provider API key must be non-empty ASCII without whitespace"
        )
    return value


def response_too_large(declared_length: str, maximum: int) -> bool:
    if not declared_length.isascii() or not declared_length.isdecimal():
        return False
    try:
        return int(declared_length) > maximum
    except ValueError:
        # A header beyond Python's integer conversion bound is rejected safely.
        return True
