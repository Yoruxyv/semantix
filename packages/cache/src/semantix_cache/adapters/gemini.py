"""Optional Gemini adapters. Clients are explicit and borrowed."""

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
