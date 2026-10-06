"""Maintained provider selection and bounded first-party HTTP dispatch."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypedDict

import httpx
from typing_extensions import override

from semantix_cache import CacheStoreError, EmbeddingAdapter, EmbeddingSpace
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

from .models import Options, Provider, Status

DEFAULTS: dict[Provider, tuple[str | None, str, int]] = {
    "openai": ("gpt-4.1-nano-2025-04-14", "text-embedding-3-small", 256),
    "gemini": ("gemini-3.5-flash-lite", "gemini-embedding-001", 768),
    "huggingface": (
        "Qwen/Qwen3-4B-Instruct-2507:nscale",
        "sentence-transformers/all-MiniLM-L6-v2",
        384,
    ),
    "ollama": ("gemma3:4b", "embeddinggemma", 768),
    "anthropic": (None, "deterministic-local-v1", 2),
}


ENV_KEYS: dict[Provider, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "huggingface": "HF_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": "",
}


ORIGINS: dict[Provider, tuple[str, str, int]] = {
    "openai": ("https", "api.openai.com", 443),
    "gemini": ("https", "generativelanguage.googleapis.com", 443),
    "huggingface": ("https", "router.huggingface.co", 443),
    "anthropic": ("https", "api.anthropic.com", 443),
    "ollama": ("http", "localhost", 11434),
}


class GenerationResource(Protocol):
    async def generate(self, prompt: str) -> str: ...
    async def aclose(self) -> None: ...


class EmbeddingResource(EmbeddingAdapter, Protocol):
    async def aclose(self) -> None: ...


class LocalEmbedding:
    embedding_space = EmbeddingSpace(
        identity="verifier:deterministic-local-v1:d2", dimensions=2
    )

    async def embed(self, text: str) -> Sequence[float]:  # noqa: ARG002
        return (1.0, 0.0)

    async def aclose(self) -> None:
        pass


class BoundedTransport(httpx.AsyncBaseTransport):
    """Count actual dispatches, not inferred calls; never inspect/store response bodies."""

    def __init__(
        self,
        provider: Provider,
        maximum: int,
        inner: httpx.AsyncBaseTransport,
    ) -> None:
        self.provider: Provider = provider
        self.maximum = maximum
        self.inner = inner
        self.attempts = 0
        self.status: Status = "not_attempted"
        self.unavailable = False

    @override
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        origin = (
            request.url.scheme,
            request.url.host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        if request.method != "POST" or origin != ORIGINS[self.provider]:
            self.status = "endpoint_rejected"
            raise CacheStoreError("Verifier endpoint rejected")
        if self.attempts >= self.maximum:
            self.status = "attempt_limit"
            raise CacheStoreError("Verifier HTTP attempt limit reached")
        self.attempts += 1
        try:
            response = await self.inner.handle_async_request(request)
        except httpx.TimeoutException:
            self.status = "timeout"
            raise
        except httpx.HTTPError as error:
            self.status = "transport_error"
            self.unavailable = self.provider == "ollama" and isinstance(
                error, httpx.ConnectError
            )
            raise
        category: Status = (
            "success"
            if response.status_code < 300
            else "redirect"
            if response.status_code < 400
            else "client_error"
            if response.status_code < 500
            else "server_error"
        )
        self.status = category
        self.unavailable = self.provider == "ollama" and response.status_code == 404
        return response

    @override
    async def aclose(self) -> None:
        await self.inner.aclose()


class GenerationOptions(TypedDict):
    client: httpx.AsyncClient
    model: str
    timeout_seconds: float
    max_new_tokens: int


class EmbeddingOptions(TypedDict):
    client: httpx.AsyncClient
    model: str
    embedding_space: EmbeddingSpace
    timeout_seconds: float


def adapters(
    options: Options,
    client: httpx.AsyncClient,
    key: str,
    request_timeout: float,
) -> tuple[EmbeddingResource, GenerationResource]:
    space = EmbeddingSpace(
        identity=f"verifier:{options.provider}:{options.embedding_model}:d{options.embedding_dimensions}:adapter-wire-v1",
        dimensions=options.embedding_dimensions,
    )
    shared: GenerationOptions = {
        "client": client,
        "model": options.model,
        "timeout_seconds": request_timeout,
        "max_new_tokens": 64,
    }
    embedding: EmbeddingOptions = {
        "client": client,
        "model": options.embedding_model,
        "embedding_space": space,
        "timeout_seconds": request_timeout,
    }
    if options.provider == "openai":
        return OpenAIEmbeddingAdapter(
            **embedding, api_key=key
        ), OpenAIGenerationAdapter(**shared, api_key=key)
    if options.provider == "gemini":
        return GeminiEmbeddingAdapter(
            **embedding, api_key=key
        ), GeminiGenerationAdapter(**shared, api_key=key)
    if options.provider == "huggingface":
        return HuggingFaceEmbeddingAdapter(
            **embedding, api_key=key
        ), HuggingFaceGenerationAdapter(**shared, api_key=key)
    if options.provider == "ollama":
        return OllamaEmbeddingAdapter(**embedding), OllamaGenerationAdapter(**shared)
    return LocalEmbedding(), AnthropicGenerationAdapter(**shared, api_key=key)
