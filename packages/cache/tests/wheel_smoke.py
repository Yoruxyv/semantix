"""Run in a clean environment containing only the built wheel and runtime deps."""

import asyncio
import importlib
import importlib.util
from collections.abc import Sequence
from pathlib import Path

import semantix_cache
from semantix_cache import AsyncSemanticCache, EmbeddingSpace, MemoryStore


class Adapter:
    embedding_space = EmbeddingSpace(identity="wheel-smoke-v1", dimensions=2)

    async def embed(self, text: str) -> Sequence[float]:
        return (1.0, 0.0)


async def main() -> None:
    adapter = Adapter()

    async def generate(prompt: str) -> str:
        return "completed"

    async with (
        MemoryStore(embedding_space=adapter.embedding_space) as store,
        AsyncSemanticCache(embedder=adapter, store=store) as cache,
    ):
        miss = await cache.resolve("first", generate=generate)
        hit = await cache.resolve("similar", generate=generate)
        assert miss.cache_written and miss.provider_called
        assert hit.cache_hit and hit.generation_skipped
        assert await cache.get("similar") is not None
        assert await cache.clear() == 1
    assert semantix_cache.__file__ is not None
    location = Path(semantix_cache.__file__)
    assert "site-packages" in location.parts
    assert location.with_name("py.typed").is_file()
    for name in (
        "semantix",
        "app",
        "backend",
        "fastapi",
        "uvicorn",
        "starlette",
        "slowapi",
        "asyncpg",
        "redis",
        "httpx",
        "pydantic_settings",
        "dotenv",
        "semantix_client",
    ):
        assert importlib.util.find_spec(name) is None, name

    importlib.import_module("semantix_cache.stores")
    try:
        importlib.import_module("semantix_cache.stores.pgvector")
    except ImportError as exc:
        assert "semantix-cache[pgvector]" in str(exc)
        assert "docs/embedded-storage.md" in str(exc)
    else:
        raise AssertionError("PostgreSQL store imported without its optional driver")

    try:
        importlib.import_module("semantix_cache.stores.redis")
    except ImportError as exc:
        assert "semantix-cache[redis]" in str(exc)
    else:
        raise AssertionError("Redis store imported without its optional driver")

    for provider in ("openai", "huggingface", "gemini", "ollama", "anthropic"):
        try:
            importlib.import_module("semantix_cache.adapters." + provider)
        except ImportError as exc:
            assert "semantix-cache[providers]" in str(exc)
            assert "docs/embedded-providers.md" in str(exc)
        else:
            raise AssertionError("Optional adapter imported without HTTP dependencies")
    print("Minimal wheel and actionable optional-dependency errors verified")


if __name__ == "__main__":
    asyncio.run(main())
