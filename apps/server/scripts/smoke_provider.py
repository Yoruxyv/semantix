import asyncio
import sys
from typing import Literal

import httpx

from app.core.config import get_settings
from app.providers.factory import (
    create_embedding_provider,
    create_generation_provider,
)

Capability = Literal["embedding", "generation"]


async def smoke(
    capability: Capability,
    text: str,
) -> None:
    settings = get_settings()
    timeout = httpx.Timeout(settings.provider_timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if capability == "embedding":
            embedding_provider = create_embedding_provider(
                client,
                settings,
            )
            vector = await embedding_provider.create_embedding(text)
            print(
                "embedding_provider="
                f"{settings.embedding_provider} "
                f"dimensions={len(vector)}"
            )
            return

        generation_provider = create_generation_provider(
            client,
            settings,
        )
        response = await generation_provider.generate(text)
        print(f"generation_provider={settings.generation_provider}")
        print(response)


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {
        "embedding",
        "generation",
    }:
        raise SystemExit(
            'Usage: python scripts/smoke_provider.py <embedding|generation> "text"'
        )

    capability: Capability = "embedding" if sys.argv[1] == "embedding" else "generation"
    asyncio.run(smoke(capability, sys.argv[2]))


if __name__ == "__main__":
    main()
