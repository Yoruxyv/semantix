from collections.abc import Sequence
from urllib.parse import quote

import httpx
import numpy as np

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


def _rows(
    value: object,
    *,
    dimensions: int,
) -> list[list[float]] | None:
    direct = parse_vector(value, dimensions=dimensions)
    if direct is not None:
        return [direct]

    if not isinstance(value, list) or not value:
        return None

    if len(value) == 1:
        nested = _rows(
            value[0],
            dimensions=dimensions,
        )
        if nested is not None:
            return nested

    result: list[list[float]] = []
    for item in value:
        row = parse_vector(
            item,
            dimensions=dimensions,
        )
        if row is None:
            return None
        result.append(row)

    return result or None


class HuggingFaceProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        inference_base_url: str | None,
        chat_base_url: str | None,
        embedding_model: str | None,
        generation_model: str | None,
        embedding_dimensions: int | None,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._inference_base_url = (
            None if inference_base_url is None else inference_base_url.rstrip("/")
        )
        self._chat_base_url = (
            None if chat_base_url is None else chat_base_url.rstrip("/")
        )
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
        if (
            self._inference_base_url is None
            or self._embedding_model is None
            or self._embedding_dimensions is None
        ):
            raise RuntimeError("Hugging Face embedding provider is not configured")
        model_path = quote(
            self._embedding_model,
            safe="/",
        )
        endpoint = (
            f"{self._inference_base_url}/{model_path}/pipeline/feature-extraction"
        )
        payload = await post_json(
            self._client,
            endpoint,
            headers=self._headers(),
            body={
                "inputs": [text],
                "normalize": True,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        rows = _rows(
            payload,
            dimensions=self._embedding_dimensions,
        )
        if rows is None:
            raise InvalidProviderResponseError(
                "Invalid embedding shape",
            )

        vector = np.mean(
            np.asarray(rows, dtype=np.float64),
            axis=0,
        )
        if (
            vector.shape != (self._embedding_dimensions,)
            or not np.isfinite(vector).all()
        ):
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return [float(component) for component in vector]

    async def generate(self, prompt: str) -> str:
        if self._chat_base_url is None or self._generation_model is None:
            raise RuntimeError("Hugging Face generation provider is not configured")
        payload = await post_json(
            self._client,
            f"{self._chat_base_url}/chat/completions",
            headers=self._headers(),
            body={
                "model": self._generation_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "max_tokens": self._max_new_tokens,
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

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise InvalidProviderResponseError(
                "Invalid chat choice",
            )

        message = first_choice.get("message")
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
