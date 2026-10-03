"""Optional OpenAI adapters. Clients are explicit and borrowed."""

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
