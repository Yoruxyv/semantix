"""Borrowed HTTP transport for optional integrations, independent of the server."""

import asyncio
import json
from collections.abc import Callable
from types import TracebackType
from typing import Self, TypeVar, cast
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
    """Validate syntax for a hosted HTTPS root or an Ollama HTTP/HTTPS origin.

    Reject userinfo, queries, fragments, whitespace, backslashes and invalid
    ports; local origins also reject paths. Return the root without trailing
    slashes. This validates syntax, not destination trust or network locality.
    """
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
    """Private base; closing seals the adapter and never closes its borrowed client.

    Concrete integrations inherit operation admission, finite request deadlines,
    bounded JSON transport and async context management. This is implementation
    support, not a public custom-provider extension API or the server transport.
    There is no automatic retry, fallback or redirect following here.
    """

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
        """Validate transport configuration without opening a connection.

        Args:
            client: Existing HTTPX AsyncClient borrowed for the adapter's lifetime.
            model: Explicit nonblank model identifier without edge whitespace
                or control characters.
            base_url: Hosted HTTPS root, or HTTP/HTTPS origin when ``local=True``;
                no embedded credentials, query or fragment.
            headers: Provider-specific headers stored for requests.
            timeout_seconds: Finite positive total operation deadline and explicit
                per-request HTTPX timeout, overriding client timeout defaults.
            max_response_bytes: Positive integer limit on buffered body bytes.
            error: EmbeddingError or GenerationError used for expected failures.
            local: Permit an HTTP origin, without enforcing loopback/private routing.

        Raises:
            CacheConfigurationError: Client, model, URL, timeout or byte limit
                fails the corresponding validation.
        """
        if not isinstance(cast(object, client), httpx.AsyncClient):
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
        """Admit one operation, POST bounded JSON and run a provider parsing callback.

        Send Accept-Encoding identity and explicitly disable redirects. Reject all
        non-2xx statuses, encoded bodies and oversized declared/received lengths.
        Check chunks before growing the body buffer. The finite adapter deadline
        includes reading, JSON decoding and ``parse``; synchronous work cannot be
        interrupted, so a final clock check rejects a late successful result.

        Expected HTTPX, timeout and JSON failures become the configured integration
        error with payload-free messages and a newly constructed RuntimeError cause.
        Parser errors and unrelated programming exceptions propagate unchanged;
        this is not blanket exception sanitization. Client hooks/logging remain
        caller-owned. A parsed ``None`` is still a successful result.

        Response contexts and operation admission unwind on failure/cancellation.
        External cancellation propagates, including when a transport swallowed it.
        No retry, remote cancellation or request rollback is promised.

        Args:
            path: Integration-owned endpoint suffix appended to the validated root.
            body: Provider-owned JSON request payload.
            parse: Synchronous decoder/validator run on the JSON value within the
                operation. Its result is returned without further interpretation.

        Returns:
            The provider parsing callback's result.

        Raises:
            CacheClosedError: The adapter has been sealed.
            EmbeddingError: Expected integration failure for an embedding adapter.
            GenerationError: Expected integration failure for a generation adapter.
            asyncio.CancelledError: External cancellation, without closing the client.
        """
        failure = ""
        # A parsed None is still a successful result.
        result: tuple[Parsed] | None = None
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
                                    result = (parse(payload),)
                if asyncio.get_running_loop().time() >= deadline:
                    failure = "Provider request exceeded its deadline"
            except (TimeoutError, httpx.TimeoutException):
                failure = "Provider request exceeded its deadline"
            except httpx.HTTPError:
                failure = "Provider transport failed"
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            if failure or result is None:
                # Construct the cause outside the except block: raw HTTP/JSON exceptions
                # can contain private URLs, credentials or response bodies.
                message = failure or "Provider returned no parsed result"
                raise self._error(message) from RuntimeError(message)
        return result[0]

    async def aclose(self) -> None:
        """Seal the adapter without waiting for operations or closing its HTTP client.

        Repeated closure is harmless. Busy closure leaves the adapter open; drain
        or cancel active tasks before retrying. Subsequent embedding/generation
        requests and context entry raise CacheClosedError after successful closure.

        Raises:
            CacheBusyError: An admitted operation is still active.
        """
        self._lifecycle.close()

    async def __aenter__(self) -> Self:
        """Return this open adapter without opening or acquiring its HTTP client."""
        self._lifecycle.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Seal this adapter through aclose, including its busy-operation check."""
        await self.aclose()


def checked_space(value: object) -> EmbeddingSpace:
    """Revalidate and copy even manually constructed EmbeddingSpace metadata."""
    if not isinstance(value, EmbeddingSpace):
        raise CacheConfigurationError("Expected explicit EmbeddingSpace metadata")
    try:
        return EmbeddingSpace.model_validate(value.model_dump())
    except ValueError:
        raise CacheConfigurationError("Embedding metadata is invalid") from None


def request_text(value: str) -> None:
    """Validate nonblank text of 1-2000 characters without rewriting its content."""
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
    """Check an ASCII decimal Content-Length, rejecting oversized integer text.

    Missing/malformed lengths do not establish a bound; streaming checks still
    enforce the limit. Digit strings beyond Python's conversion bound are
    conservatively treated as too large rather than exposing raw parse errors.
    """
    if not declared_length.isascii() or not declared_length.isdecimal():
        return False
    try:
        return int(declared_length) > maximum
    except ValueError:
        # A header beyond Python's integer conversion bound is rejected safely.
        return True
