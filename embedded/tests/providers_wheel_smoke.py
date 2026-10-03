"""Run against an installed wheel and each HTTP extra, without development deps."""

import asyncio
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypedDict

import httpx

import semantix_cache
from semantix_cache import EmbeddingAdapter, EmbeddingSpace
from semantix_cache.adapters.anthropic import AnthropicGenerationAdapter
from semantix_cache.adapters.gemini import (
    GeminiEmbeddingAdapter,
    GeminiGenerationAdapter,
)
from semantix_cache.adapters.huggingface import (
    HuggingFaceEmbeddingAdapter,
    HuggingFaceGenerationAdapter,
)
from semantix_cache.adapters.ollama import (
    OllamaEmbeddingAdapter,
    OllamaGenerationAdapter,
)
from semantix_cache.adapters.openai import (
    OpenAIEmbeddingAdapter,
    OpenAIGenerationAdapter,
)


class Options(TypedDict):
    client: httpx.AsyncClient
    api_key: str
    model: str


def handle(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/embeddings"):
        payload: object = {"data": [{"embedding": [3.0, 4.0]}]}
    elif path.endswith("/pipeline/feature-extraction"):
        payload = [[3.0, 4.0]]
    elif path.endswith(":embedContent"):
        payload = {"embedding": {"values": [3.0, 4.0]}}
    elif path.endswith("/api/embed"):
        payload = {"embeddings": [[3.0, 4.0]]}
    elif path.endswith(":generateContent"):
        payload = {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": "completed"}]}}
            ]
        }
    elif path.endswith("/api/generate"):
        payload = {"done": True, "response": "completed"}
    elif path.endswith("/v1/messages"):
        payload = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "completed"}],
        }
    else:
        payload = {
            "choices": [{"finish_reason": "stop", "message": {"content": "completed"}}]
        }
    return httpx.Response(200, json=payload)


async def main() -> None:
    space = EmbeddingSpace(identity="smoke:model:r1:d2:raw", dimensions=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        options: Options = {
            "client": client,
            "api_key": "fixture-credential-no-access",
            "model": "test-model",
        }
        embedders: tuple[EmbeddingAdapter, ...] = (
            OpenAIEmbeddingAdapter(**options, embedding_space=space),
            HuggingFaceEmbeddingAdapter(**options, embedding_space=space),
            GeminiEmbeddingAdapter(**options, embedding_space=space),
            OllamaEmbeddingAdapter(
                client=client, model="test-model", embedding_space=space
            ),
        )
        generators: tuple[Callable[[str], Awaitable[str]], ...] = (
            OpenAIGenerationAdapter(**options).generate,
            HuggingFaceGenerationAdapter(**options).generate,
            GeminiGenerationAdapter(**options).generate,
            OllamaGenerationAdapter(client=client, model="test-model").generate,
            AnthropicGenerationAdapter(**options).generate,
        )
        for adapter in embedders:
            assert tuple(await adapter.embed("test")) == (3.0, 4.0)
        for generate in generators:
            assert await generate("test") == "completed"
    assert semantix_cache.__file__ is not None
    assert "site-packages" in Path(semantix_cache.__file__).parts
    for name in (
        "app",
        "fastapi",
        "asyncpg",
        "openai",
        "anthropic",
        "huggingface_hub",
        "google",
        "ollama",
    ):
        assert importlib.util.find_spec(name) is None, name
    print(
        "Installed HTTP extra: four embedding and five generation adapters verified offline"
    )


if __name__ == "__main__":
    asyncio.run(main())
