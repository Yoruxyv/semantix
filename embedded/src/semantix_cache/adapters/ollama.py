"""Optional Ollama adapters. Clients are explicit and borrowed."""

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
