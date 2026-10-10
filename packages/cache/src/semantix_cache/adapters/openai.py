"""Optional OpenAI adapters. Clients are explicit and borrowed.

Requires HTTPX through the provider's optional extra or ``semantix-cache[providers]``;
no provider SDK is installed. Models and configuration are explicit, independently
of server settings and its registry. Each request uses the finite adapter deadline
and byte limit, with no automatic retries or redirects. Cancellation propagates.
Inherited async context management and ``aclose`` seal only the adapter, refuse
active operations and leave the caller's HTTP client open. Caller transport hooks
and remote processing remain outside these guarantees. See ``docs/embedded-providers.md``.
"""

from collections.abc import Sequence

from ..errors import EmbeddingError, GenerationError
from ..models import EmbeddingSpace
from ._http import (
    HTTPAdapter,
    checked_space,
    configured_key,
    httpx,
    positive_integer,
    request_text,
)
from ._parsing import (
    chat_text,
    openai_vector,
)

__all__ = ["OpenAIEmbeddingAdapter", "OpenAIGenerationAdapter"]


class OpenAIEmbeddingAdapter(HTTPAdapter):
    """Embed one input through OpenAI's float-vector endpoint.

    Implements the embedded EmbeddingAdapter contract with explicit space
    identity. The facade normalizes returned vectors for cosine comparison.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        embedding_space: EmbeddingSpace,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure one embedding integration without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient, never closed by this adapter.
            api_key: Explicit ASCII credential sent in Bearer authorization.
            model: Explicit provider model identifier; not inferred from the environment.
            embedding_space: Validated copy of immutable identity and dimensions.
                Identity must distinguish compatible model, revision and preprocessing.
            base_url: HTTPS API root preceding the embeddings or chat endpoint.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL, credentials, limits or space
                metadata fail constructor validation.
        """
        super().__init__(
            client=client,
            model=model,
            base_url=base_url,
            headers={"Authorization": "Bearer " + configured_key(api_key)},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=EmbeddingError,
        )
        self._embedding_space = checked_space(embedding_space)

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._embedding_space

    async def embed(self, text: str) -> Sequence[float]:
        """POST one text to ``/embeddings`` with float encoding and space dimensions.

        Send ``model``, ``input``, ``encoding_format="float"`` and ``dimensions``.
        Require exactly one data item and a finite, nonboolean vector with the
        configured length and valid nonzero magnitude. The cache normalizes it.

        Returns:
            Validated float components at provider scale, without local normalization.

        Raises:
            CacheValidationError: Text is blank or outside 1-2000 characters.
            CacheClosedError: The adapter has been sealed.
            EmbeddingError: HTTP, deadline, JSON, batch or vector validation fails,
                including a caller-closed client.
        """
        self._lifecycle.check_open()
        request_text(text)
        return await self._post(
            "/embeddings",
            {
                "model": self._model,
                "input": text,
                "encoding_format": "float",
                "dimensions": self.embedding_space.dimensions,
            },
            lambda payload: openai_vector(payload, self.embedding_space.dimensions),
        )


class OpenAIGenerationAdapter(HTTPAdapter):
    """Pass generate to the cache; the application owns final-response approval."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_new_tokens: int = 512,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure the generation callback without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient; adapter close never closes it.
            api_key: Explicit ASCII credential sent in Bearer authorization.
            model: Explicit generation model identifier.
            max_new_tokens: Positive integer generation budget sent in the
                provider-specific field documented on ``generate``.
            base_url: HTTPS API root preceding the embeddings or chat endpoint.
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
            headers={"Authorization": "Bearer " + configured_key(api_key)},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=GenerationError,
        )
        self._max_new_tokens = positive_integer(max_new_tokens)

    async def generate(self, prompt: str) -> str:
        """POST a user message to ``/chat/completions`` with ``stream=False``.

        Send ``max_completion_tokens``. Require the first choice to finish with
        ``finish_reason="stop"``, without truthy tool calls or refusal. Validate
        its message content as nonblank text of at most 100000 characters before
        stripping surrounding whitespace. Pass this bound method as the cache's
        ``generate`` callback; the application still owns response approval.

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
            "/chat/completions",
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": self._max_new_tokens,
                "stream": False,
            },
            chat_text,
        )
