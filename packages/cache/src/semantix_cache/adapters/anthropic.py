"""First-party Anthropic generation with a caller-owned HTTP client.

Anthropic has no native embedding API; pair generation with any supported built-in
or custom embedding adapter. The 0.1.0 adapter is covered by deterministic contract
and regression tests; first-party live verification remains pending.

See https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-providers.md#010-verification.
"""

from ..errors import GenerationError
from ._http import (
    HTTPAdapter,
    configured_key,
    httpx,
    positive_integer,
    request_text,
)
from ._parsing import anthropic_text

__all__ = ["AnthropicGenerationAdapter"]


class AnthropicGenerationAdapter(HTTPAdapter):
    """First-party Messages generation, usable as the cache's async callback.

    Pass ``generate=adapter.generate``; the application owns final-response
    approval and adapter/client lifetime. HTTPX requires the ``anthropic``
    or ``providers`` extra, without an Anthropic SDK. Inherited deadlines,
    response bounds and closure apply, with no automatic retry or redirect.
    Cancellation propagates. First-party live verification remains pending;
    this class adds no embedding capability.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_new_tokens: int = 512,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure the generation callback without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient; adapter close never closes it.
            api_key: Explicit ASCII credential sent in ``x-api-key``.
            model: Explicit generation model identifier.
            max_new_tokens: Positive integer generation budget sent in the
                provider-specific field documented on ``generate``.
            base_url: HTTPS API root preceding ``/v1/messages``.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL, credentials or limits fail
                constructor validation.
        """
        super().__init__(
            client=client,
            model=model,
            base_url=base_url,
            headers={
                "x-api-key": configured_key(api_key),
                "anthropic-version": "2023-06-01",
            },
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=GenerationError,
        )
        self._max_new_tokens = positive_integer(max_new_tokens)

    async def generate(self, prompt: str) -> str:
        """POST a user message and ``max_tokens`` to ``/v1/messages``.

        Use ``x-api-key`` and ``anthropic-version: 2023-06-01``. Require
        ``stop_reason`` to be ``end_turn`` or ``stop_sequence`` and reject any
        ``tool_use`` block. Join nonblank text blocks, excluding thought-marked
        blocks, and validate the completed text bound. No embedding API is added.

        Returns:
            Completed, trimmed text of at most 100000 characters, not rich SDK objects.

        Raises:
            CacheValidationError: Prompt is blank or outside 1-2000 characters.
            CacheClosedError: The adapter has been sealed.
            GenerationError: HTTP/deadline/JSON failure or invalid, incomplete or
                unsupported completed-text output, including a caller-closed client.
        """
        self._lifecycle.check_open()
        request_text(prompt)
        return await self._post(
            "/v1/messages",
            {
                "model": self._model,
                "max_tokens": self._max_new_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            anthropic_text,
        )
