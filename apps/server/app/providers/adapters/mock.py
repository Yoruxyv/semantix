"""Deterministic, network-free providers for development and test composition.

Token hashing and synthetic responses exercise cache mechanics; they do not
model a real provider's semantic quality. No HTTP client or model is needed.
"""

import asyncio
import hashlib
import logging
import math
import re
from collections.abc import Sequence

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MOCK_GENERATION_PREFIX = "[mock provider]"
logger = logging.getLogger(__name__)


class MockEmbeddingProvider:
    """Deterministic local embedding provider for tests and demos."""

    def __init__(self, dimensions: int) -> None:
        """Configure the output vector length.

        Args:
            dimensions: Positive number of hash buckets and vector components.

        Raises:
            ValueError: Dimensions are zero or negative.
        """
        if dimensions <= 0:
            raise ValueError("Mock embedding dimensions must be positive")
        self._dimensions = dimensions

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
        """Hash case-folded ASCII-alphanumeric tokens into signed vector buckets.

        With no matching tokens, hash the entire case-folded text instead. SHA-256
        fixes each token's bucket and sign; repeated tokens accumulate. Normalize
        to unit length, or return the first basis vector if contributions cancel.

        Returns:
            A stable unit vector with the configured number of components.
        """
        tokens = TOKEN_PATTERN.findall(text.casefold())
        if not tokens:
            tokens = [text.casefold()]

        vector = [0.0] * self._dimensions
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self._dimensions
            direction = 1.0 if digest[8] & 1 else -1.0
            vector[index] += direction

        magnitude = math.sqrt(sum(component * component for component in vector))
        if magnitude == 0:
            vector[0] = 1.0
            return vector
        return [component / magnitude for component in vector]


class MockGenerationProvider:
    """Deterministic local generation provider for tests and demos."""

    _generation_delay_seconds = 0.0

    async def generate(self, prompt: str) -> str:
        """Return the mock prefix followed by the original prompt.

        An optional delay supplied by MockProvider uses cancellable asyncio sleep.
        When delayed, static start/finish log messages omit prompt content, and
        cancellation propagates through the sleep.
        """
        if self._generation_delay_seconds:
            logger.info("Mock generation started")
            try:
                await asyncio.sleep(self._generation_delay_seconds)
            finally:
                logger.info("Mock generation finished")
        return f"{MOCK_GENERATION_PREFIX} {prompt}"


class MockProvider(MockEmbeddingProvider, MockGenerationProvider):
    """Dual-capability deterministic provider used by startup composition."""

    def __init__(self, dimensions: int, *, delay_seconds: float = 0) -> None:
        """Combine deterministic embedding and generation with optional latency.

        Args:
            dimensions: Positive embedding vector length.
            delay_seconds: Artificial generation sleep duration; zero disables it.

        Raises:
            ValueError: Dimensions are zero or negative.
        """
        super().__init__(dimensions)
        self._generation_delay_seconds = delay_seconds
