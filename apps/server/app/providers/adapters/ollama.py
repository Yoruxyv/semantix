"""Server Ollama embedding and non-streaming generation integration.

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


class OllamaProvider:
    """Ollama adapter for local embedding and generation APIs."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        embedding_model: str | None,
        generation_model: str | None,
        embedding_dimensions: int | None,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        """Capture an Ollama origin, model settings and borrowed HTTP transport.

        This adapter does not install models or manage the Ollama process.

        Args:
            client: Application-owned async HTTP client.
            base_url: Deployment-validated HTTP/HTTPS origin. Origin validation
                does not restrict it to loopback or guarantee local/private traffic.
            embedding_model: Already available embedding model, or ``None``.
            generation_model: Already available generation model, or ``None``.
            embedding_dimensions: Requested and expected vector length, or ``None``.
            max_new_tokens: Generation budget sent as ``options.num_predict``.
            retry_factory: Per-request policy; the default retries eligible
                transport failures for up to three attempts.
            max_response_bytes: Shared transport's buffered response byte limit.
        """
        self._client = client
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
        """POST ``model``, one text ``input`` and ``dimensions`` to ``/api/embed``.

        Require exactly one entry in ``embeddings``, containing a finite numeric
        vector of the configured length without booleans. Magnitude validation
        and normalization occur later in EmbeddingService.

        Returns:
            The single model vector without local normalization.

        Raises:
            RuntimeError: Embedding model or dimensions are not configured.
            InvalidProviderResponseError: The batch or vector is invalid.
        """
        if self._embedding_model is None or self._embedding_dimensions is None:
            raise RuntimeError("Ollama embedding provider is not configured")

        payload = await post_json(
            self._client,
            f"{self._base_url}/api/embed",
            headers={"Content-Type": "application/json"},
            body={
                "model": self._embedding_model,
                "input": text,
                "dimensions": self._embedding_dimensions,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid Ollama embedding response",
            )

        embeddings = cast("dict[str, object]", payload).get("embeddings")
        if (
            not isinstance(embeddings, list)
            or len(cast("list[object]", embeddings)) != 1
        ):
            raise InvalidProviderResponseError(
                "Ollama embedding response contained no single vector",
            )

        vector = parse_vector(
            cast("list[object]", embeddings)[0],
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid Ollama embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
        """POST ``model`` and ``prompt`` to ``/api/generate`` with ``stream=False``.

        Set ``options.num_predict`` and extract nonblank ``response`` text. This
        server decoder does not inspect ``done``, ``done_reason`` or a separate
        provider error field; HTTP failures follow shared transport classification.
        The embedded integration independently checks completion markers.

        Returns:
            Response text with surrounding whitespace removed.

        Raises:
            RuntimeError: A generation model is not configured.
            InvalidProviderResponseError: The response object or text is invalid.
        """
        if self._generation_model is None:
            raise RuntimeError("Ollama generation provider is not configured")

        payload = await post_json(
            self._client,
            f"{self._base_url}/api/generate",
            headers={"Content-Type": "application/json"},
            body={
                "model": self._generation_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": self._max_new_tokens,
                },
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid Ollama generation response",
            )

        response = cast("dict[str, object]", payload).get("response")
        if not isinstance(response, str) or not response.strip():
            raise InvalidProviderResponseError(
                "Ollama generation response contained no text",
            )
        return response.strip()
