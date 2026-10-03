import httpx
import pytest

from app.core.config import Settings
from app.providers.adapters.anthropic import AnthropicProvider
from app.providers.adapters.huggingface import HuggingFaceProvider
from app.providers.adapters.mock import (
    MockEmbeddingProvider,
    MockGenerationProvider,
)
from app.providers.adapters.ollama import OllamaProvider
from app.providers.factory import (
    create_embedding_provider,
    create_generation_provider,
    create_provider_bundle,
)

ORIGINS = ["http://localhost:5173"]


def ollama_settings(**values: object) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": "ollama",
            "generation_provider": "ollama",
            "ollama_embedding_model": "embeddinggemma",
            "ollama_generation_model": "gemma3",
            "ollama_embedding_dimensions": 768,
            "hf_api_key": None,
            "cache_backend": "memory",
            "allowed_origins": ORIGINS,
            **values,
        }
    )


@pytest.mark.asyncio
async def test_selects_ollama_for_each_capability() -> None:
    configured = ollama_settings()

    async with httpx.AsyncClient() as client:
        embedding = create_embedding_provider(client, configured)
        generation = create_generation_provider(client, configured)

    assert isinstance(embedding, OllamaProvider)
    assert isinstance(generation, OllamaProvider)


@pytest.mark.asyncio
async def test_reuses_ollama_when_selected_for_both_capabilities() -> None:
    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(client, ollama_settings())

    assert isinstance(bundle.embedding_provider, OllamaProvider)
    assert bundle.embedding_provider is bundle.generation_provider
    assert bundle.embedding_dimensions == 768


@pytest.mark.asyncio
async def test_supports_hosted_embedding_with_ollama_generation() -> None:
    configured = ollama_settings(
        embedding_provider="huggingface",
        hf_api_key="hf-key",
    )

    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(client, configured)

    assert isinstance(bundle.embedding_provider, HuggingFaceProvider)
    assert isinstance(bundle.generation_provider, OllamaProvider)


@pytest.mark.asyncio
async def test_supports_ollama_embedding_with_hosted_generation() -> None:
    configured = ollama_settings(
        generation_provider="anthropic",
        anthropic_api_key="anthropic-key",
        anthropic_generation_model="claude-model",
    )

    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(client, configured)

    assert isinstance(bundle.embedding_provider, OllamaProvider)
    assert isinstance(bundle.generation_provider, AnthropicProvider)


@pytest.mark.asyncio
async def test_selects_network_free_mock_providers() -> None:
    configured = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        mock_embedding_dimensions=32,
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=ORIGINS,
    )

    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(client, configured)

    assert isinstance(bundle.embedding_provider, MockEmbeddingProvider)
    assert isinstance(bundle.generation_provider, MockGenerationProvider)
    assert bundle.embedding_dimensions == 32
