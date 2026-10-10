"""Structural boundaries for provider adapters and server embedding consumers."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Adapter boundary for model vectors in a registered embedding space.

    ``EmbeddingService`` consumes this interface, validates dimensions and
    finite/nonzero values, then normalizes vectors before cache or benchmark use.
    Runtime protocol checks identify method presence, not output validity.
    """

    async def create_embedding(self, text: str) -> Sequence[float]:
        """Return the model vector for text, before server service normalization."""
        ...


class EmbeddingGenerator(Protocol):
    """Embedding service boundary consumed by cache and benchmark workflows.

    Application composition supplies ``EmbeddingService`` for validated,
    normalized vectors. Its ``embed`` method differs from the adapter's
    ``create_embedding``; the two interfaces are not interchangeable.
    """

    async def embed(self, text: str) -> Sequence[float]:
        """Return a vector suitable for the consumer's similarity comparisons."""
        ...


@runtime_checkable
class GenerationProvider(Protocol):
    """Adapter boundary for provider-specific generation and decoded text.

    Implementations own request and response formats and translate provider
    failures to server error contracts. Query and benchmark workflows apply
    shared text validation. Runtime protocol checks do not validate outputs.
    """

    async def generate(self, prompt: str) -> str:
        """Generate and decode text for a prompt using the provider's own schema."""
        ...
