from collections.abc import Sequence
from urllib.parse import quote

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


class GeminiProvider:
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
        self._embedding_model = (
            None if embedding_model is None else self._model_name(embedding_model)
        )
        self._generation_model = (
            None if generation_model is None else self._model_name(generation_model)
        )
        self._embedding_dimensions = embedding_dimensions
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
        if self._embedding_model is None or self._embedding_dimensions is None:
            raise RuntimeError("Gemini embedding provider is not configured")
        model_path = quote(
            self._embedding_model,
            safe="",
        )
        payload = await post_json(
            self._client,
            (f"{self._base_url}/models/{model_path}:embedContent"),
            headers=self._headers(),
            body={
                "model": f"models/{self._embedding_model}",
                "content": {
                    "parts": [
                        {
                            "text": text,
                        },
                    ],
                },
                "embedContentConfig": {
                    "outputDimensionality": self._embedding_dimensions,
                },
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid embedding response",
            )

        embedding = payload.get("embedding")
        if not isinstance(embedding, dict):
            raise InvalidProviderResponseError(
                "Embedding response contained no embedding",
            )

        vector = parse_vector(
            embedding.get("values"),
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
        if self._generation_model is None:
            raise RuntimeError("Gemini generation provider is not configured")
        model_path = quote(
            self._generation_model,
            safe="",
        )
        payload = await post_json(
            self._client,
            (f"{self._base_url}/models/{model_path}:generateContent"),
            headers=self._headers(),
            body={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": prompt,
                            },
                        ],
                    },
                ],
                "generationConfig": {
                    "maxOutputTokens": self._max_new_tokens,
                },
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid generation response",
            )

        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise InvalidProviderResponseError(
                "Generation response contained no candidates",
            )

        first = candidates[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid generation candidate",
            )
        content = first.get("content")
        if not isinstance(content, dict):
            raise InvalidProviderResponseError(
                "Generation response contained no content",
            )
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise InvalidProviderResponseError(
                "Generation response contained no parts",
            )

        text_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())

        if not text_parts:
            raise InvalidProviderResponseError(
                "Generation response contained no text",
            )
        return "\n".join(text_parts)

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _model_name(value: str) -> str:
        return value.removeprefix("models/")
