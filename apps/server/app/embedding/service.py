"""Normalize provider embeddings through the package's shared semantic boundary.

Provider selection/space metadata belongs to ``app.providers.registry`` and
cache binding. This service validates vector shape and magnitude, not model
compatibility, provenance or provider availability.
"""

from app.core.exceptions import EmbeddingError
from app.providers.protocols import EmbeddingProvider
from semantix_cache._semantics import normalized_vector


class EmbeddingService:
    """Delegate embedding creation to a borrowed provider and normalize its output.

    Construction performs no provider calls. The application owns provider resources;
    this service does not close them. Text is forwarded unchanged to the provider.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        dimensions: int,
    ) -> None:
        """Require a positive configured vector dimension without probing the provider.

        Args:
            provider: Borrowed embedding implementation selected by the application.
            dimensions: Required component count for every returned embedding.

        Raises:
            ValueError: dimensions is less than one.
        """
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be greater than zero")
        self._provider = provider
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        """Return a unit vector after shared float64 shape, component and norm checks.

        The package helper requires the configured length, real non-boolean components,
        finite values and a finite norm greater than float64 epsilon. Invalid vectors
        are rejected rather than padded, clipped or repaired. Normalization is subject
        to floating-point precision. Only ValueError from that helper is translated;
        provider exceptions and cancellation propagate.

        Args:
            text: Text passed unchanged to the selected embedding provider.

        Returns:
            Normalized components as a list of Python floats.

        Raises:
            EmbeddingError: Shared semantic validation rejects the provider vector.
        """
        output = await self._provider.create_embedding(text)
        try:
            vector = normalized_vector(output, dimensions=self._dimensions)
        except ValueError:
            raise EmbeddingError("Embedding output is invalid") from None
        return [float(value) for value in vector]
