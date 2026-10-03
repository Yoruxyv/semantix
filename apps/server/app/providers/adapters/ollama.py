from collections.abc import Sequence

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

        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise InvalidProviderResponseError(
                "Ollama embedding response contained no single vector",
            )

        vector = parse_vector(
            embeddings[0],
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid Ollama embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
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

        response = payload.get("response")
        if not isinstance(response, str) or not response.strip():
            raise InvalidProviderResponseError(
                "Ollama generation response contained no text",
            )
        return response.strip()
