"""Server OpenAI embedding and chat-completion wire contracts.

Application lifespan owns the injected HTTP client; these adapters never close it.
Constructors expect deployment-validated configuration. ``post_json`` applies the
retry policy, byte limit and deadline derived from the client's read timeout;
provider-specific parsing occurs after that transport call and is not retried.
Cancellation propagates during HTTP waits without guaranteeing remote rollback.
See ``app.providers.shared.transport`` and ``docs/guides/providers.md``.
"""

from collections.abc import Sequence
from typing import cast

import httpx

from app.core.exceptions import InvalidProviderResponseError
from app.providers.shared.transport import (
    DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    RetryFactory,
    create_retry_factory,
    post_json,
)
from app.providers.shared.vectors import parse_vector

RETRY_ATTEMPTS = 3
RETRY_MULTIPLIER_SECONDS = 0.5
RETRY_MAX_WAIT_SECONDS = 4.0
DEFAULT_RETRY_FACTORY = create_retry_factory(
    attempts=RETRY_ATTEMPTS,
    multiplier_seconds=RETRY_MULTIPLIER_SECONDS,
    max_wait_seconds=RETRY_MAX_WAIT_SECONDS,
)


class OpenAIProvider:
    """Provide configured OpenAI embedding and generation capabilities to the server."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        embedding_model: str | None,
        generation_model: str | None,
        embedding_dimensions: int | None,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        """Capture explicit configuration and borrowed transport without API calls.

        Args:
            client: Application-owned async HTTP client.
            api_key: Credential sent in the Bearer authorization header.
            base_url: Validated API root, normally including its version path.
            embedding_model: Embedding model, or ``None`` when not configured.
            generation_model: Chat model, or ``None`` when not configured.
            embedding_dimensions: Requested and expected vector length; may be
                ``None`` when embedding is not configured.
            max_new_tokens: Generation budget sent as ``max_completion_tokens``.
            retry_factory: Fresh policy per request; the default retries only
                transport-classified retryable errors, for up to three attempts.
            max_response_bytes: Shared transport's buffered response byte limit.
        """
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._generation_model = generation_model
        self._embedding_dimensions = embedding_dimensions
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
        """POST one text to ``/embeddings`` and decode the first data item's vector.

        The payload includes ``input``, ``model``, ``encoding_format="float"`` and
        configured ``dimensions``. Additional data items are ignored. Components
        must be finite numbers, excluding booleans, with the exact expected length.
        Nonzero magnitude and normalization are handled later by EmbeddingService.

        Returns:
            A float vector at the provider's scale, without local normalization.

        Raises:
            RuntimeError: Embedding model or dimensions are not configured.
            InvalidProviderResponseError: The response shape or vector is invalid.
        """
        if self._embedding_model is None or self._embedding_dimensions is None:
            raise RuntimeError("OpenAI embedding provider is not configured")
        payload = await post_json(
            self._client,
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            body={
                "input": text,
                "model": self._embedding_model,
                "encoding_format": "float",
                "dimensions": self._embedding_dimensions,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid embedding response",
            )

        data = cast("dict[str, object]", payload).get("data")
        if not isinstance(data, list) or not data:
            raise InvalidProviderResponseError(
                "Embedding response contained no data",
            )

        first = cast("list[object]", data)[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid embedding item",
            )

        vector = parse_vector(
            cast("dict[str, object]", first).get("embedding"),
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
        """POST a user message to ``/chat/completions`` with streaming disabled.

        Uses ``max_completion_tokens`` and returns the first choice's message
        content. This decoder requires nonblank text but does not check
        ``finish_reason``, tool calls or refusals. Server workflows apply shared
        text validation afterward; this is not the embedded completion parser.

        Returns:
            The first choice's text with surrounding whitespace removed.

        Raises:
            RuntimeError: A generation model is not configured.
            InvalidProviderResponseError: Choices, message or text are invalid.
        """
        if self._generation_model is None:
            raise RuntimeError("OpenAI generation provider is not configured")
        payload = await post_json(
            self._client,
            f"{self._base_url}/chat/completions",
            headers=self._headers(),
            body={
                "model": self._generation_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "max_completion_tokens": self._max_new_tokens,
                "stream": False,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid chat-completion response",
            )

        choices = cast("dict[str, object]", payload).get("choices")
        if not isinstance(choices, list) or not choices:
            raise InvalidProviderResponseError(
                "Chat response contained no choices",
            )

        first = cast("list[object]", choices)[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid chat choice",
            )
        message = cast("dict[str, object]", first).get("message")
        if not isinstance(message, dict):
            raise InvalidProviderResponseError(
                "Chat response contained no message",
            )
        content = cast("dict[str, object]", message).get("content")
        if not isinstance(content, str) or not content.strip():
            raise InvalidProviderResponseError(
                "Chat response contained no text",
            )
        return content.strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
