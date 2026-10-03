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


class OpenAIProvider:
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

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise InvalidProviderResponseError(
                "Embedding response contained no data",
            )

        first = data[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid embedding item",
            )

        vector = parse_vector(
            first.get("embedding"),
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
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

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise InvalidProviderResponseError(
                "Chat response contained no choices",
            )

        first = choices[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid chat choice",
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise InvalidProviderResponseError(
                "Chat response contained no message",
            )
        content = message.get("content")
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
