import hashlib
import math
import re
from collections.abc import Sequence

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MOCK_GENERATION_PREFIX = "[mock provider]"


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

    async def generate(self, prompt: str) -> str:
        return f"{MOCK_GENERATION_PREFIX} {prompt}"


class MockProvider(MockEmbeddingProvider, MockGenerationProvider):
    """Dual-capability deterministic provider used by startup composition."""
