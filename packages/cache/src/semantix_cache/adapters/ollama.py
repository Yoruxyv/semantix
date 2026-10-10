"""Optional Ollama adapters. Clients are explicit and borrowed.

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
    httpx,
    positive_integer,
    request_text,
)
from ._parsing import (
    ollama_text,
    ollama_vector,
)

__all__ = ["OllamaEmbeddingAdapter", "OllamaGenerationAdapter"]


class OllamaEmbeddingAdapter(HTTPAdapter):
    """Embed through an explicitly configured Ollama origin and model.

    No credentials, model installation or server process management are supplied.
    An HTTP/HTTPS origin may be remote; locality and privacy depend on deployment.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        model: str,
        embedding_space: EmbeddingSpace,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure one embedding integration without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient, never closed by this adapter.
            model: Explicit provider model identifier; not inferred from the environment.
            embedding_space: Validated copy of immutable identity and dimensions.
                Identity must distinguish compatible model, revision and preprocessing.
            base_url: HTTP/HTTPS origin without path, credentials, query or fragment.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL, limits or space
                metadata fail constructor validation.
        """
        super().__init__(
            client=client,
            model=model,
            base_url=base_url,
            headers={},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=EmbeddingError,
            local=True,
        )
        self._embedding_space = checked_space(embedding_space)

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._embedding_space

    async def embed(self, text: str) -> Sequence[float]:
        """POST ``model``, one text ``input`` and space ``dimensions`` to ``/api/embed``.

        Require exactly one entry in ``embeddings`` with finite nonboolean
        components, exact dimensions and valid nonzero magnitude. HTTP failures
        become EmbeddingError; an Ollama process and suitable model must already
        be available at the configured origin.

        Returns:
            Validated float components at provider scale; the cache normalizes them.

        Raises:
            CacheValidationError: Text is blank or outside 1-2000 characters.
            CacheClosedError: The adapter has been sealed.
            EmbeddingError: HTTP/deadline/JSON failure or invalid batch/vector.
        """
        self._lifecycle.check_open()
        request_text(text)
        return await self._post(
            "/api/embed",
            {
                "model": self._model,
                "input": text,
                "dimensions": self.embedding_space.dimensions,
            },
            lambda payload: ollama_vector(payload, self.embedding_space.dimensions),
        )


class OllamaGenerationAdapter(HTTPAdapter):
    """Pass generate to the cache; the application owns final-response approval."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        model: str,
        max_new_tokens: int = 512,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        """Configure the generation callback without making a provider request.

        Args:
            client: Borrowed HTTPX AsyncClient; adapter close never closes it.
            model: Explicit generation model identifier.
            max_new_tokens: Positive integer generation budget sent in the
                provider-specific field documented on ``generate``.
            base_url: HTTP/HTTPS origin without path, credentials, query or fragment.
            timeout_seconds: Finite positive total request/parse deadline, also
                supplied as the per-request HTTPX timeout.
            max_response_bytes: Positive integer limit on the buffered JSON body.

        Raises:
            CacheConfigurationError: Client, model, URL or limits fail
                constructor validation.
        """
        super().__init__(
            client=client,
            model=model,
            base_url=base_url,
            headers={},
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=GenerationError,
            local=True,
        )
        self._max_new_tokens = positive_integer(max_new_tokens)

    async def generate(self, prompt: str) -> str:
        """POST ``model`` and ``prompt`` to ``/api/generate`` with ``stream=False``.

        Set ``options.num_predict``. Require ``done is True`` and a missing/null
        or ``"stop"`` done_reason, then validate nonblank, bounded ``response``
        text. Pass this bound method as the cache's ``generate`` callback;
        output approval and the Ollama deployment remain application-owned.

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
            "/api/generate",
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": self._max_new_tokens},
            },
            ollama_text,
        )
