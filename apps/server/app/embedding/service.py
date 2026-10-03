from app.core.exceptions import EmbeddingError
from app.providers.protocols import EmbeddingProvider
from semantix_cache._semantics import normalized_vector


class EmbeddingService:
    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        dimensions: int,
    ) -> None:
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be greater than zero")
        self._provider = provider
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        output = await self._provider.create_embedding(text)
        try:
            vector = normalized_vector(output, dimensions=self._dimensions)
        except ValueError:
            raise EmbeddingError("Embedding output is invalid") from None
        return [float(value) for value in vector]
