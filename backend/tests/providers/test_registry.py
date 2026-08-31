import logging
from collections.abc import Sequence

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.exceptions import ProviderRequestError
from app.factory import create_app
from app.providers.adapters.mock import MockProvider
from app.providers.extension import (
    EmbeddingMetadata,
    ProviderBuildContext,
    ProviderBuilder,
    ProviderRegistration,
    ProviderRegistry,
    create_default_provider_registry,
)
from app.providers.factory import create_provider_bundle

ORIGINS = ["http://localhost:5173"]


class DualProvider:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    async def create_embedding(self, text: str) -> Sequence[float]:
        return [1.0, 0.0]

    async def generate(self, prompt: str) -> str:
        return f"custom: {prompt}"


class EmbeddingOnlyProvider:
    def __init__(self, vector: Sequence[float] = (1.0, 0.0)) -> None:
        self._vector = vector

    async def create_embedding(self, text: str) -> Sequence[float]:
        return self._vector


class GenerationOnlyProvider:
    async def generate(self, prompt: str) -> str:
        return f"generated: {prompt}"


class FailingGenerationProvider:
    async def generate(self, prompt: str) -> str:
        raise ProviderRequestError("private custom provider failure")


def settings(
    *,
    embedding_provider: str = "custom-dual",
    generation_provider: str = "custom-dual",
) -> Settings:
    return Settings(
        embedding_provider=embedding_provider,
        generation_provider=generation_provider,
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=ORIGINS,
    )


def dual_registration(
    builder: ProviderBuilder,
    *,
    name: str = "custom-dual",
    secret: SecretStr | None = None,
    embedding_space: str = "custom-dual:embedding-v1",
) -> ProviderRegistration:
    return ProviderRegistration(
        name=name,
        capabilities=frozenset({"embedding", "generation"}),
        builder=builder,
        embedding_metadata=EmbeddingMetadata(
            dimensions=2,
            space=embedding_space,
        ),
        generation_metadata={"provider": name, "model": "deterministic-v1"},
        secrets=() if secret is None else (secret,),
    )


def test_default_registry_contains_every_builtin() -> None:
    configured = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        allowed_origins=ORIGINS,
    )

    registry = create_default_provider_registry(configured)

    assert registry.names() == frozenset(
        {"huggingface", "openai", "anthropic", "gemini", "ollama", "mock"}
    )


@pytest.mark.parametrize(
    "name",
    ["", "../provider", "provider/name", "provider name", "a" * 51],
)
def test_provider_name_contract_rejects_malformed_values(name: str) -> None:
    with pytest.raises(ValidationError, match="embedding_provider"):
        settings(embedding_provider=name)


def test_settings_accept_syntactically_valid_custom_names() -> None:
    configured = settings(
        embedding_provider="company.embed-v1",
        generation_provider="company:generation_v1",
    )

    assert configured.embedding_provider == "company.embed-v1"
    assert configured.generation_provider == "company:generation_v1"


def test_registry_rejects_duplicates_and_mutation_after_resolution() -> None:
    registry = ProviderRegistry()
    registration = dual_registration(lambda context: DualProvider())
    registry.register(registration)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(registration)

    selection = registry.resolve("custom-dual", "custom-dual")

    assert selection.embedding is selection.generation
    assert registry.frozen
    with pytest.raises(RuntimeError, match="frozen"):
        registry.register(
            dual_registration(lambda context: DualProvider(), name="another")
        )


def test_default_builtin_registration_cannot_be_overridden() -> None:
    configured = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        allowed_origins=ORIGINS,
    )
    registry = create_default_provider_registry(configured)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            dual_registration(lambda context: DualProvider(), name="mock")
        )


def test_unknown_and_capability_mismatched_selection_fail_before_startup() -> None:
    configured = settings()
    registry = ProviderRegistry()
    registry.register(
        ProviderRegistration(
            name="generation-only",
            capabilities=frozenset({"generation"}),
            builder=lambda context: GenerationOnlyProvider(),
            generation_metadata={"provider": "generation-only", "model": "v1"},
        )
    )

    with pytest.raises(ValueError, match="not registered"):
        create_app(configured, provider_registry=registry)

    mismatch = settings(
        embedding_provider="generation-only",
        generation_provider="generation-only",
    )
    registry = ProviderRegistry()
    registry.register(
        ProviderRegistration(
            name="generation-only",
            capabilities=frozenset({"generation"}),
            builder=lambda context: GenerationOnlyProvider(),
            generation_metadata={"provider": "generation-only", "model": "v1"},
        )
    )
    with pytest.raises(ValueError, match="does not support embedding"):
        create_app(mismatch, provider_registry=registry)


def test_embedding_registration_requires_complete_metadata() -> None:
    with pytest.raises(ValueError, match="require embedding metadata"):
        ProviderRegistration(
            name="incomplete",
            capabilities=frozenset({"embedding"}),
            builder=lambda context: EmbeddingOnlyProvider(),
        )
    with pytest.raises(ValueError, match="greater than zero"):
        EmbeddingMetadata(dimensions=0, space="custom:v1")
    with pytest.raises(ValueError, match="must not be empty"):
        EmbeddingMetadata(dimensions=2, space=" ")


def test_custom_dual_provider_builds_once_reuses_instance_and_reports_health() -> None:
    configured = settings()
    registry = create_default_provider_registry(configured)
    builds: list[ProviderBuildContext] = []

    def build(context: ProviderBuildContext) -> DualProvider:
        builds.append(context)
        return DualProvider(context.client)

    registry.register(dual_registration(build))
    application = create_app(configured, provider_registry=registry)

    assert registry.frozen
    with TestClient(application) as client:
        first = client.post("/api/v1/query", json={"prompt": "one"})
        second = client.post("/api/v1/query", json={"prompt": "one"})
        health = client.get("/health")
        diagnostics = client.get("/api/v1/diagnostics")
        assert application.state.embedding_provider is (
            application.state.generation_provider
        )
        assert application.state.embedding_provider.client is builds[0].client

    assert len(builds) == 1
    assert first.status_code == 200
    assert first.json()["response"] == "custom: one"
    assert second.json()["cache_hit"] is True
    assert health.json() == {
        "status": "ok",
        "embedding_provider": "custom-dual",
        "generation_provider": "custom-dual",
    }
    assert diagnostics.status_code == 200
    assert diagnostics.json()["embedding_provider_category"] == "custom-dual"
    assert diagnostics.json()["generation_provider_category"] == "custom-dual"


@pytest.mark.asyncio
async def test_mixed_custom_and_builtin_providers_resolve_independently() -> None:
    custom_embedding_settings = settings(
        embedding_provider="custom-embedding",
        generation_provider="mock",
    )
    registry = create_default_provider_registry(custom_embedding_settings)
    registry.register(
        ProviderRegistration(
            name="custom-embedding",
            capabilities=frozenset({"embedding"}),
            builder=lambda context: EmbeddingOnlyProvider(),
            embedding_metadata=EmbeddingMetadata(
                dimensions=2,
                space="custom-embedding:v1",
            ),
        )
    )
    selection = registry.resolve("custom-embedding", "mock")
    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(
            client,
            custom_embedding_settings,
            selection=selection,
        )

    assert isinstance(bundle.embedding_provider, EmbeddingOnlyProvider)
    assert isinstance(bundle.generation_provider, MockProvider)

    custom_generation_settings = settings(
        embedding_provider="mock",
        generation_provider="custom-generation",
    )
    registry = create_default_provider_registry(custom_generation_settings)
    registry.register(
        ProviderRegistration(
            name="custom-generation",
            capabilities=frozenset({"generation"}),
            builder=lambda context: GenerationOnlyProvider(),
            generation_metadata={"provider": "custom-generation", "model": "v1"},
        )
    )
    selection = registry.resolve("mock", "custom-generation")
    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(
            client,
            custom_generation_settings,
            selection=selection,
        )

    assert isinstance(bundle.embedding_provider, MockProvider)
    assert isinstance(bundle.generation_provider, GenerationOnlyProvider)
    assert await bundle.generation_provider.generate("one") == "generated: one"


@pytest.mark.asyncio
async def test_different_custom_providers_build_separately_with_shared_client() -> None:
    configured = settings(
        embedding_provider="custom-embedding",
        generation_provider="custom-generation",
    )
    registry = create_default_provider_registry(configured)
    built_with: list[httpx.AsyncClient] = []

    def build_embedding(context: ProviderBuildContext) -> EmbeddingOnlyProvider:
        built_with.append(context.client)
        return EmbeddingOnlyProvider()

    def build_generation(context: ProviderBuildContext) -> GenerationOnlyProvider:
        built_with.append(context.client)
        return GenerationOnlyProvider()

    registry.register(
        ProviderRegistration(
            name="custom-embedding",
            capabilities=frozenset({"embedding"}),
            builder=build_embedding,
            embedding_metadata=EmbeddingMetadata(
                dimensions=2,
                space="custom-embedding:v1",
            ),
        )
    )
    registry.register(
        ProviderRegistration(
            name="custom-generation",
            capabilities=frozenset({"generation"}),
            builder=build_generation,
            generation_metadata={"provider": "custom-generation", "model": "v1"},
        )
    )
    selection = registry.resolve("custom-embedding", "custom-generation")

    async with httpx.AsyncClient() as client:
        bundle = create_provider_bundle(client, configured, selection=selection)
        assert built_with == [client, client]

    assert isinstance(bundle.embedding_provider, EmbeddingOnlyProvider)
    assert isinstance(bundle.generation_provider, GenerationOnlyProvider)
    assert id(bundle.embedding_provider) != id(bundle.generation_provider)
    assert bundle.embedding_space == "custom-embedding:v1"


@pytest.mark.parametrize("vector", [[1.0], [float("nan"), 0.0]])
def test_custom_embedding_still_uses_service_validation(
    vector: Sequence[float],
) -> None:
    configured = settings(
        embedding_provider="custom-embedding",
        generation_provider="mock",
    )
    registry = create_default_provider_registry(configured)
    registry.register(
        ProviderRegistration(
            name="custom-embedding",
            capabilities=frozenset({"embedding"}),
            builder=lambda context: EmbeddingOnlyProvider(vector),
            embedding_metadata=EmbeddingMetadata(
                dimensions=2,
                space="custom-embedding:v1",
            ),
        )
    )

    with TestClient(create_app(configured, provider_registry=registry)) as client:
        response = client.post("/api/v1/query", json={"prompt": "one"})

    assert response.status_code == 502
    assert response.json()["error"] == "embedding_error"


def test_custom_generation_exception_uses_existing_error_boundary() -> None:
    configured = settings(
        embedding_provider="mock",
        generation_provider="custom-generation",
    )
    registry = create_default_provider_registry(configured)
    registry.register(
        ProviderRegistration(
            name="custom-generation",
            capabilities=frozenset({"generation"}),
            builder=lambda context: FailingGenerationProvider(),
            generation_metadata={"provider": "custom-generation", "model": "v1"},
        )
    )

    with TestClient(create_app(configured, provider_registry=registry)) as client:
        response = client.post("/api/v1/query", json={"prompt": "one"})

    assert response.status_code == 502
    assert response.json() == {
        "error": "upstream_error",
        "detail": "The AI service could not process the request.",
    }
    assert "private custom provider failure" not in response.text


def test_generation_only_custom_provider_serves_query() -> None:
    configured = settings(
        embedding_provider="mock",
        generation_provider="custom-generation",
    )
    registry = create_default_provider_registry(configured)
    registry.register(
        ProviderRegistration(
            name="custom-generation",
            capabilities=frozenset({"generation"}),
            builder=lambda context: GenerationOnlyProvider(),
            generation_metadata={"provider": "custom-generation", "model": "v1"},
        )
    )

    with TestClient(create_app(configured, provider_registry=registry)) as client:
        response = client.post("/api/v1/query", json={"prompt": "one"})

    assert response.status_code == 200
    assert response.json()["response"] == "generated: one"


def test_custom_registration_secrets_join_log_redaction() -> None:
    configured = settings()
    registry = create_default_provider_registry(configured)
    registry.register(
        dual_registration(
            lambda context: DualProvider(),
            secret=SecretStr("custom-secret"),
        )
    )

    create_app(configured, provider_registry=registry)
    formatter = logging.getLogger().handlers[0].formatter
    assert formatter is not None
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failure custom-secret",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)

    assert "custom-secret" not in output
    assert "[REDACTED]" in output


def test_registered_secrets_cannot_enter_provider_identity_metadata() -> None:
    registry = ProviderRegistry()
    registry.register(
        dual_registration(
            lambda context: DualProvider(),
            secret=SecretStr("custom-secret"),
            embedding_space="custom-dual:custom-secret",
        )
    )

    with pytest.raises(ValueError, match="must not contain registered secrets"):
        registry.resolve("custom-dual", "custom-dual")


def test_empty_registered_secrets_are_ignored() -> None:
    registry = ProviderRegistry()
    registry.register(
        dual_registration(
            lambda context: DualProvider(),
            secret=SecretStr(""),
        )
    )

    assert registry.configured_secrets() == ()
