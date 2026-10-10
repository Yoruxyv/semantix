"""Optional Gemini adapters. Clients are explicit and borrowed.

Requires HTTPX through the provider's optional extra or ``semantix-cache[providers]``;
no provider SDK is installed. Models and configuration are explicit, independently
of server settings and its registry. Each request uses the finite adapter deadline
and byte limit, with no automatic retries or redirects. Cancellation propagates.
Inherited async context management and ``aclose`` seal only the adapter, refuse
active operations and leave the caller's HTTP client open. Caller transport hooks
and remote processing remain outside these guarantees. See ``docs/embedded-providers.md``.
"""

from collections.abc import Sequence
from urllib.parse import quote

from ..errors import EmbeddingError, GenerationError
from ..models import EmbeddingSpace
from ._http import (
    HTTPAdapter,
    checked_space,
    configured_key,
    configured_text,
    httpx,
    positive_integer,
    request_text,
)
from ._parsing import (
    gemini_text,
    mapping,
    vector,
)

__all__ = ["GeminiEmbeddingAdapter", "GeminiGenerationAdapter"]


class GeminiEmbeddingAdapter(HTTPAdapter):
    """Embed Gemini content parts into an explicitly configured vector space.

    Model names accept an optional ``models/`` prefix. Dimensions are requested
    and validated, without silently truncating or padding provider output.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        embedding_space: EmbeddingSpace,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure one embedding integration without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient, never closed by this adapter.
            api_key: Explicit ASCII credential sent in ``x-goog-api-key``.
            model: Explicit model identifier; an optional ``models/`` prefix is removed.
            embedding_space: Validated copy of immutable identity and dimensions.
                Identity must distinguish compatible model, revision and preprocessing.
            base_url: HTTPS API root preceding the versioned model endpoints.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL, credentials, limits or space
                metadata fail constructor validation.
        """
        super().__init__(
            client=client,
            model=configured_text(model).removeprefix("models/"),
            base_url=base_url,
            headers={"x-goog-api-key": configured_key(api_key)},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=EmbeddingError,
        )
        self._embedding_space = checked_space(embedding_space)

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._embedding_space

    async def embed(self, text: str) -> Sequence[float]:
        """POST content parts to the encoded model's ``:embedContent`` endpoint.

        Send ``model="models/..."`` and top-level ``outputDimensionality`` from
        ``embedding_space``. Extract ``embedding.values`` with exact dimensions,
        finite nonboolean components and valid nonzero magnitude. Existing field
        compatibility is model-specific; a different model's support is not assumed.

        Returns:
            Validated float components at their returned scale; the cache normalizes.

        Raises:
            CacheValidationError: Text is blank or outside 1-2000 characters.
            CacheClosedError: The adapter has been sealed.
            EmbeddingError: HTTP/deadline/JSON failure or invalid embedding shape,
                dimensions or magnitude.
        """
        self._lifecycle.check_open()
        request_text(text)
        return await self._post(
            f"/models/{quote(self._model, safe='')}:embedContent",
            {
                "model": "models/" + self._model,
                "content": {"parts": [{"text": text}]},
                # gemini-embedding-001 honors the supported top-level field;
                # the newer nested config can silently return the default size.
                "outputDimensionality": self.embedding_space.dimensions,
            },
            lambda payload: vector(
                mapping(mapping(payload).get("embedding")).get("values"),
                self.embedding_space.dimensions,
            ),
        )


class GeminiGenerationAdapter(HTTPAdapter):
    """Pass generate to the cache; the application owns final-response approval."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_new_tokens: int = 512,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure the generation callback without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient; adapter close never closes it.
            api_key: Explicit ASCII credential sent in ``x-goog-api-key``.
            model: Explicit model identifier; an optional ``models/`` prefix is removed.
            max_new_tokens: Positive integer generation budget sent in the
                provider-specific field documented on ``generate``.
            base_url: HTTPS API root preceding the versioned model endpoints.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL, credentials or limits fail
                constructor validation.
        """
        super().__init__(
            client=client,
            model=configured_text(model).removeprefix("models/"),
            base_url=base_url,
            headers={"x-goog-api-key": configured_key(api_key)},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=GenerationError,
        )
        self._max_new_tokens = positive_integer(max_new_tokens)

    async def generate(self, prompt: str) -> str:
        """POST user parts to the encoded model's ``:generateContent`` endpoint.

        Set ``generationConfig.maxOutputTokens``. Require the first candidate's
        ``finishReason="STOP"`` and reject function-call parts. Exclude parts with
        ``thought is True``; join remaining nonblank text parts with newlines and
        validate the completed text bound. This bound method can serve as the
        cache's application-owned generation callback.

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
            f"/models/{quote(self._model, safe='')}:generateContent",
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": self._max_new_tokens},
            },
            gemini_text,
        )
