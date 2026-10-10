"""Server Anthropic Messages integration for generation only.

Application lifespan owns the injected HTTP client; these adapters never close it.
Constructors expect deployment-validated configuration. ``post_json`` applies the
retry policy, byte limit and deadline derived from the client's read timeout;
provider-specific parsing occurs after that transport call and is not retried.
Cancellation propagates during HTTP waits without guaranteeing remote rollback.
See ``app.providers.shared.transport`` and ``docs/guides/providers.md``.
"""

from typing import cast

import httpx

from app.core.exceptions import InvalidProviderResponseError
from app.providers.shared.transport import (
    DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    RetryFactory,
    create_retry_factory,
    post_json,
)

RETRY_ATTEMPTS = 3
RETRY_MULTIPLIER_SECONDS = 0.5
RETRY_MAX_WAIT_SECONDS = 4.0
DEFAULT_RETRY_FACTORY = create_retry_factory(
    attempts=RETRY_ATTEMPTS,
    multiplier_seconds=RETRY_MULTIPLIER_SECONDS,
    max_wait_seconds=RETRY_MAX_WAIT_SECONDS,
)
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider:
    """Generation-only Anthropic Messages adapter; no embedding method is provided.

    Pair this selection with a separate embedding-capable provider.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        generation_model: str,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        """Capture Messages API settings and application-owned transport.

        Args:
            client: Borrowed async HTTP client.
            api_key: Credential sent in ``x-api-key``.
            base_url: Validated API root preceding ``/v1/messages``.
            generation_model: Explicit Messages model identifier.
            max_new_tokens: Generation budget sent as ``max_tokens``.
            retry_factory: Per-request policy; the default retries eligible
                transport failures for up to three attempts.
            max_response_bytes: Shared transport's buffered response byte limit.
        """
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._generation_model = generation_model
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def generate(self, prompt: str) -> str:
        """POST a user message to ``/v1/messages`` with version ``2023-06-01``.

        Send the configured model and ``max_tokens`` with ``x-api-key`` and
        ``anthropic-version`` headers. Extract nonblank text only from content
        blocks whose type is ``text``; other blocks are skipped. This server
        decoder does not validate ``stop_reason`` or reject a mixed tool-use
        response. Shared server text validation follows in calling workflows.

        Returns:
            Trimmed text blocks joined with newlines.

        Raises:
            InvalidProviderResponseError: Content is missing/invalid or contains
                no nonblank text blocks.
        """
        payload = await post_json(
            self._client,
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "Content-Type": "application/json",
            },
            body={
                "model": self._generation_model,
                "max_tokens": self._max_new_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid message response",
            )

        content = cast("dict[str, object]", payload).get("content")
        if not isinstance(content, list) or not content:
            raise InvalidProviderResponseError(
                "Message response contained no content",
            )

        text_blocks: list[str] = []
        for block in cast("list[object]", content):
            if (
                not isinstance(block, dict)
                or cast("dict[str, object]", block).get("type") != "text"
            ):
                continue
            text = cast("dict[str, object]", block).get("text")
            if isinstance(text, str) and text.strip():
                text_blocks.append(text.strip())

        if not text_blocks:
            raise InvalidProviderResponseError(
                "Message response contained no text",
            )
        return "\n".join(text_blocks)
