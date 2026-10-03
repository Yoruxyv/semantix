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
        if dimensions <= 0:
            raise ValueError("Mock embedding dimensions must be positive")
        self._dimensions = dimensions

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
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
        super().__init__(dimensions)
        self._generation_delay_seconds = delay_seconds
