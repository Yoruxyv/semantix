"""Construct selected server adapters with borrowed application HTTP transport.

``registry`` owns capability declarations and metadata resolution. This module
invokes builders and checks their structural provider interfaces; adapters
retain ownership of their wire formats. Application lifespan owns the client,
including cleanup after construction failure. The factory does not manage
additional resources allocated by custom builders.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.providers.adapters.anthropic import AnthropicProvider
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.huggingface import HuggingFaceProvider
from app.providers.adapters.mock import MockProvider
from app.providers.adapters.ollama import OllamaProvider
from app.providers.adapters.openai import OpenAIProvider
from app.providers.configuration import (
    MOCK_EMBEDDING_MODEL_ID,
    MOCK_GENERATION_MODEL_ID,
    ProviderName,
)
from app.providers.protocols import EmbeddingProvider, GenerationProvider
from app.providers.registry import (
    EmbeddingMetadata,
    ProviderBuildContext,
    ProviderCapability,
    ProviderInstance,
    ProviderRegistration,
    ProviderRegistry,
    ResolvedProviderSelection,
    SafeMetadataValue,
)


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """Constructed adapters with their selected provider names and metadata.

    Embedding dimensions and space configure the embedding service and cache;
    generation configuration contributes to benchmark identity. These values
    come from registry selection, not introspection of adapter output. The bundle
    does not own or close the injected HTTP client.
    """

    embedding_provider: EmbeddingProvider
    generation_provider: GenerationProvider
    embedding_provider_name: ProviderName
    generation_provider_name: ProviderName
    embedding_dimensions: int
    embedding_space: str
    generation_configuration: Mapping[str, SafeMetadataValue]


def create_default_provider_registry(settings: Settings) -> ProviderRegistry:
    """Register built-in adapters without selecting or constructing them.

    Args:
        settings: Configuration captured by builders and metadata resolvers.

    Returns:
        A fresh, unfrozen registry for Hugging Face, OpenAI, Anthropic, Gemini,
        Ollama and mock providers. Anthropic declares generation only; the
        others declare both capabilities. Custom registrations can be added
        before application creation. Selected metadata is evaluated later.
    """
    registry = ProviderRegistry()
    registry.register(
        _registration(
            "huggingface",
            settings,
            _create_huggingface,
            embedding_dimensions=settings.hf_embedding_dimensions,
            embedding_model=settings.hf_embedding_model,
            generation_model=settings.hf_generation_model,
            secrets=_secrets(settings.hf_api_key),
        )
    )
    registry.register(
        _registration(
            "openai",
            settings,
            _create_openai,
            embedding_dimensions=settings.openai_embedding_dimensions,
            embedding_model=settings.openai_embedding_model,
            generation_model=settings.openai_generation_model,
            secrets=_secrets(settings.openai_api_key),
        )
    )
    registry.register(
        _registration(
            "anthropic",
            settings,
            _create_anthropic,
            capabilities=frozenset({"generation"}),
            generation_model=settings.anthropic_generation_model,
            secrets=_secrets(settings.anthropic_api_key),
        )
    )
    registry.register(
        _registration(
            "gemini",
            settings,
            _create_gemini,
            embedding_dimensions=settings.gemini_embedding_dimensions,
            embedding_model=settings.gemini_embedding_model,
            generation_model=settings.gemini_generation_model,
            secrets=_secrets(settings.gemini_api_key),
        )
    )
    registry.register(
        _registration(
            "ollama",
            settings,
            _create_ollama,
            embedding_dimensions=settings.ollama_embedding_dimensions,
            embedding_model=settings.ollama_embedding_model,
            generation_model=settings.ollama_generation_model,
        )
    )
    registry.register(
        _registration(
            "mock",
            settings,
            _create_mock,
            embedding_dimensions=settings.mock_embedding_dimensions,
            embedding_model=MOCK_EMBEDDING_MODEL_ID,
            generation_model=MOCK_GENERATION_MODEL_ID,
        )
    )
    return registry


def create_embedding_provider(
    client: httpx.AsyncClient,
    settings: Settings,
) -> EmbeddingProvider:
    """Resolve built-in selections and construct only the embedding adapter.

    Both configured provider names and their metadata are resolved against a
    fresh default registry. For custom registrations, use application bootstrap
    or ``create_provider_bundle`` with an explicit selection.

    Args:
        client: Borrowed HTTP client; the caller retains ownership.
        settings: Provider selections, credentials and construction limits.

    Returns:
        The selected built-in embedding provider.

    Raises:
        ValueError: Either selection or its metadata is invalid.
        TypeError: The builder result lacks the embedding provider interface.
    """
    selection = create_default_provider_registry(settings).resolve(
        settings.embedding_provider,
        settings.generation_provider,
    )
    return _build_embedding_provider(
        selection.embedding,
        _build_context(client, settings),
    )


def create_generation_provider(
    client: httpx.AsyncClient,
    settings: Settings,
) -> GenerationProvider:
    """Resolve built-in selections and construct only the generation adapter.

    Both configured provider names and their metadata are resolved against a
    fresh default registry. For custom registrations, use application bootstrap
    or ``create_provider_bundle`` with an explicit selection.

    Args:
        client: Borrowed HTTP client; the caller retains ownership.
        settings: Provider selections, credentials and construction limits.

    Returns:
        The selected built-in generation provider.

    Raises:
        ValueError: Either selection or its metadata is invalid.
        TypeError: The builder result lacks the generation provider interface.
    """
    selection = create_default_provider_registry(settings).resolve(
        settings.embedding_provider,
        settings.generation_provider,
    )
    return _build_generation_provider(
        selection.generation,
        _build_context(client, settings),
    )


def create_provider_bundle(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    selection: ResolvedProviderSelection | None = None,
) -> ProviderBundle:
    """Build both capabilities and attach the selection's resolved metadata.

    When both selections refer to the same registration, invoke its builder
    once and require the result to implement both provider protocols. Otherwise
    invoke each builder separately with the same build context and client.
    Structural checks do not validate method signatures or future outputs.

    Builder exceptions propagate. Callers retain client ownership on failure;
    custom builder resources need their own deployment cleanup.

    Args:
        client: Borrowed HTTP client, normally owned by application lifespan.
        settings: Construction limits and default selections when needed.
        selection: Previously resolved registrations and metadata, including
            custom providers. If supplied, use them without re-resolution;
            otherwise resolve both configured names in a fresh default registry.

    Returns:
        Adapters, selected names, embedding identity and generation metadata.

    Raises:
        ValueError: Default selection or its metadata is invalid.
        TypeError: A builder result lacks a selected provider interface.
    """
    resolved = selection or create_default_provider_registry(settings).resolve(
        settings.embedding_provider,
        settings.generation_provider,
    )
    context = _build_context(client, settings)
    embedding_provider: EmbeddingProvider
    generation_provider: GenerationProvider

    if resolved.embedding is resolved.generation:
        provider = resolved.embedding.builder(context)
        if not isinstance(provider, EmbeddingProvider) or not isinstance(
            provider, GenerationProvider
        ):
            raise TypeError(
                f"Provider {resolved.embedding_name!r} must implement both protocols"
            )
        embedding_provider = provider
        generation_provider = provider
    else:
        embedding_provider = _build_embedding_provider(
            resolved.embedding,
            context,
        )
        generation_provider = _build_generation_provider(
            resolved.generation,
            context,
        )

    return ProviderBundle(
        embedding_provider=embedding_provider,
        generation_provider=generation_provider,
        embedding_provider_name=resolved.embedding_name,
        generation_provider_name=resolved.generation_name,
        embedding_dimensions=resolved.embedding_metadata.dimensions,
        embedding_space=resolved.embedding_metadata.space,
        generation_configuration=resolved.generation_metadata,
    )


def _registration(
    name: ProviderName,
    settings: Settings,
    builder: Callable[[ProviderBuildContext, Settings], ProviderInstance],
    *,
    capabilities: frozenset[ProviderCapability] = frozenset(
        {"embedding", "generation"}
    ),
    embedding_dimensions: int | None = None,
    embedding_model: str | None = None,
    generation_model: str | None = None,
    secrets: tuple[SecretStr, ...] = (),
) -> ProviderRegistration:
    return ProviderRegistration(
        name=name,
        capabilities=capabilities,
        builder=lambda context: builder(context, settings),
        embedding_metadata=(
            None
            if "embedding" not in capabilities
            else lambda: _embedding_metadata(
                name,
                embedding_dimensions,
                embedding_model,
            )
        ),
        generation_metadata=lambda: _generation_metadata(
            name,
            generation_model,
            settings,
        ),
        secrets=secrets,
    )


def _embedding_metadata(
    name: ProviderName,
    dimensions: int | None,
    model: str | None,
) -> EmbeddingMetadata:
    if dimensions is None or model is None:
        raise ValueError(f"Embedding metadata for provider {name!r} is incomplete")
    return EmbeddingMetadata(dimensions=dimensions, space=f"{name}:{model}")


def _generation_metadata(
    name: ProviderName,
    model: str | None,
    settings: Settings,
) -> Mapping[str, SafeMetadataValue]:
    if model is None:
        raise ValueError(f"Generation metadata for provider {name!r} is incomplete")
    return {
        "provider": name,
        "model": model,
        "max_new_tokens": settings.generation_max_new_tokens,
        "max_response_bytes": settings.provider_max_response_bytes,
    }


def _build_embedding_provider(
    registration: ProviderRegistration,
    context: ProviderBuildContext,
) -> EmbeddingProvider:
    provider = registration.builder(context)
    if not isinstance(provider, EmbeddingProvider):
        raise TypeError(
            f"Provider {registration.name!r} does not implement EmbeddingProvider"
        )
    return provider


def _build_generation_provider(
    registration: ProviderRegistration,
    context: ProviderBuildContext,
) -> GenerationProvider:
    provider = registration.builder(context)
    if not isinstance(provider, GenerationProvider):
        raise TypeError(
            f"Provider {registration.name!r} does not implement GenerationProvider"
        )
    return provider


def _build_context(
    client: httpx.AsyncClient,
    settings: Settings,
) -> ProviderBuildContext:
    return ProviderBuildContext(
        client=client,
        provider_timeout_seconds=settings.provider_timeout_seconds,
        provider_max_response_bytes=settings.provider_max_response_bytes,
    )


def _create_huggingface(
    context: ProviderBuildContext,
    settings: Settings,
) -> HuggingFaceProvider:
    return HuggingFaceProvider(
        client=context.client,
        api_key=_secret(settings.hf_api_key, "HF_API_KEY"),
        inference_base_url=settings.hf_inference_base_url,
        chat_base_url=settings.hf_chat_base_url,
        embedding_model=settings.hf_embedding_model,
        generation_model=settings.hf_generation_model,
        embedding_dimensions=settings.hf_embedding_dimensions,
        max_new_tokens=settings.generation_max_new_tokens,
        max_response_bytes=context.provider_max_response_bytes,
    )


def _create_openai(
    context: ProviderBuildContext,
    settings: Settings,
) -> OpenAIProvider:
    return OpenAIProvider(
        client=context.client,
        api_key=_secret(settings.openai_api_key, "OPENAI_API_KEY"),
        base_url=_text(settings.openai_base_url, "OPENAI_BASE_URL"),
        embedding_model=settings.openai_embedding_model,
        generation_model=settings.openai_generation_model,
        embedding_dimensions=settings.openai_embedding_dimensions,
        max_new_tokens=settings.generation_max_new_tokens,
        max_response_bytes=context.provider_max_response_bytes,
    )


def _create_gemini(
    context: ProviderBuildContext,
    settings: Settings,
) -> GeminiProvider:
    return GeminiProvider(
        client=context.client,
        api_key=_secret(settings.gemini_api_key, "GEMINI_API_KEY"),
        base_url=_text(settings.gemini_base_url, "GEMINI_BASE_URL"),
        embedding_model=settings.gemini_embedding_model,
        generation_model=settings.gemini_generation_model,
        embedding_dimensions=settings.gemini_embedding_dimensions,
        max_new_tokens=settings.generation_max_new_tokens,
        max_response_bytes=context.provider_max_response_bytes,
    )


def _create_ollama(
    context: ProviderBuildContext,
    settings: Settings,
) -> OllamaProvider:
    return OllamaProvider(
        client=context.client,
        base_url=settings.ollama_base_url,
        embedding_model=settings.ollama_embedding_model,
        generation_model=settings.ollama_generation_model,
        embedding_dimensions=settings.ollama_embedding_dimensions,
        max_new_tokens=settings.generation_max_new_tokens,
        max_response_bytes=context.provider_max_response_bytes,
    )


def _create_anthropic(
    context: ProviderBuildContext,
    settings: Settings,
) -> AnthropicProvider:
    return AnthropicProvider(
        client=context.client,
        api_key=_secret(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        base_url=_text(settings.anthropic_base_url, "ANTHROPIC_BASE_URL"),
        generation_model=_text(
            settings.anthropic_generation_model,
            "ANTHROPIC_GENERATION_MODEL",
        ),
        max_new_tokens=settings.generation_max_new_tokens,
        max_response_bytes=context.provider_max_response_bytes,
    )


def _create_mock(_context: ProviderBuildContext, settings: Settings) -> MockProvider:
    return MockProvider(
        settings.mock_embedding_dimensions,
        delay_seconds=settings.mock_generation_delay_seconds,
    )


def _secrets(value: SecretStr | None) -> tuple[SecretStr, ...]:
    return () if value is None else (value,)


def _secret(
    value: SecretStr | None,
    environment_name: str,
) -> str:
    if value is None:
        raise RuntimeError(f"{environment_name} was not validated")
    return value.get_secret_value()


def _text(
    value: str | None,
    environment_name: str,
) -> str:
    if value is None:
        raise RuntimeError(f"{environment_name} was not validated")
    return value
