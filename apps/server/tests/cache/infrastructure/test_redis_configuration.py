"""Registry-resolved Redis limits precede storage I/O, not provider registration."""

from collections.abc import Callable
from typing import cast

import httpx
import pytest
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.cache.infrastructure import factory, setup
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.factory import create_app
from app.providers.extension import (
    EmbeddingMetadata,
    ProviderBuildContext,
    ProviderRegistration,
    ProviderRegistry,
    create_default_provider_registry,
)
from semantix_cache import CacheClosedError, CacheConfigurationError, EmbeddingSpace
from semantix_cache.stores.redis import RedisStore

URL = "redis://unit-user:simulated-secret@private-redis.example.invalid:6379/0"


class DeterministicEmbedding:
    async def create_embedding(self, text: str) -> list[float]:
        pytest.fail("Configuration and startup must not run embedding inference")


def configuration(*, provider: str = "custom-embedding", **kwargs: object) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": provider,
            "generation_provider": "mock",
            "cache_backend": "redis",
            "redis_url": URL,
            "allowed_origins": ["http://localhost"],
            **kwargs,
        }
    )


def registry(
    settings: Settings,
    *,
    metadata: EmbeddingMetadata | Callable[[], EmbeddingMetadata],
    clients: list[httpx.AsyncClient] | None = None,
) -> ProviderRegistry:
    result = create_default_provider_registry(settings)

    def build(context: ProviderBuildContext) -> DeterministicEmbedding:
        if clients is not None:
            clients.append(context.client)
        return DeterministicEmbedding()

    result.register(
        ProviderRegistration(
            name="custom-embedding",
            capabilities=frozenset({"embedding"}),
            builder=build,
            embedding_metadata=metadata,
        )
    )
    return result


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_custom_registration_resolves_without_construction_or_io(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_client(*args: object, **kwargs: object) -> Redis:
        pytest.fail("Settings and registry resolution must not create Redis clients")

    monkeypatch.setattr(Redis, "from_url", no_client)
    settings = configuration(cache_backend=backend)
    clients: list[httpx.AsyncClient] = []
    resolved: list[EmbeddingMetadata] = []

    def metadata() -> EmbeddingMetadata:
        value = EmbeddingMetadata(dimensions=2, space="custom-embedding:v1")
        resolved.append(value)
        return value

    selected = registry(settings, metadata=metadata, clients=clients)
    application = create_app(settings, provider_registry=selected)
    assert application.state.embedding_provider_name == "custom-embedding"
    assert selected.frozen
    assert len(resolved) == 1
    assert clients == []


@pytest.mark.parametrize("provider", ["custom-embedding", "mock"])
async def test_runtime_uses_resolved_binding_and_only_connects(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(provider=provider, mock_embedding_dimensions=3)
    clients: list[httpx.AsyncClient] = []
    selected = (
        registry(
            settings,
            metadata=EmbeddingMetadata(dimensions=2, space="custom-embedding:v1"),
            clients=clients,
        )
        if provider == "custom-embedding"
        else create_default_provider_registry(settings)
    )
    expected = EmbeddingSpace(
        identity="custom-embedding:v1"
        if provider == "custom-embedding"
        else "mock:stable-token-hash-v1",
        dimensions=2 if provider == "custom-embedding" else 3,
    )
    calls: list[str] = []

    async def execute(self: Redis, *args: object, **kwargs: object) -> bytes:
        assert args == ("PING",)
        calls.append("ping")
        return b"PONG"

    async def validate(self: RedisStore) -> None:
        assert self.embedding_space == expected
        calls.append("validate")

    async def initialize(self: RedisStore, *, initialization_client: Redis) -> None:
        pytest.fail("Ordinary startup must not initialize storage")

    monkeypatch.setattr(Redis, "execute_command", execute)
    monkeypatch.setattr(RedisStore, "validate_schema", validate)
    monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    application = create_app(settings, provider_registry=selected)
    assert calls == []
    async with application.router.lifespan_context(application):
        backend = application.state.semantic_cache._backend
        assert isinstance(backend, OfficialStoreBackend)
        assert isinstance(backend.store, RedisStore)
        store = backend.store
        assert store.embedding_space == expected
        assert calls == ["ping", "validate"]
    with pytest.raises(CacheClosedError):
        await store.inspect_entries()
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    ("dimensions", "space"),
    [(2049, "custom:v1"), (16001, "custom:v1"), (2, "invalid\0space")],
)
async def test_invalid_resolved_binding_fails_before_redis_client_creation(
    dimensions: int, space: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(max_cache_size=4096)
    clients: list[httpx.AsyncClient] = []
    selected = registry(
        settings,
        metadata=EmbeddingMetadata(dimensions=dimensions, space=space),
        clients=clients,
    )

    def no_client(*args: object, **kwargs: object) -> Redis:
        pytest.fail("Invalid resolved binding must fail before Redis client creation")

    monkeypatch.setattr(Redis, "from_url", no_client)
    application = create_app(settings, provider_registry=selected)
    with pytest.raises(CacheStorageError, match="Official cache setup") as caught:
        async with application.router.lifespan_context(application):
            pytest.fail("Invalid resolved binding must not start")
    assert URL not in str(caught.value)
    assert "simulated-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.parametrize("unknown", [False, True])
def test_invalid_registry_selection_fails_before_storage(
    unknown: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration()

    def no_client(*args: object, **kwargs: object) -> Redis:
        pytest.fail("Invalid registry metadata must not reach storage")

    def invalid_metadata() -> EmbeddingMetadata:
        return cast(EmbeddingMetadata, object())

    monkeypatch.setattr(Redis, "from_url", no_client)
    selected = (
        create_default_provider_registry(settings)
        if unknown
        else registry(settings, metadata=invalid_metadata)
    )
    with pytest.raises((ValueError, TypeError), match=r"not registered|invalid value"):
        create_app(settings, provider_registry=selected)


def test_settings_preserve_capacity_limit() -> None:
    assert configuration(max_cache_size=5000).max_cache_size == 5000
    with pytest.raises(ValidationError, match="capacity must be <=5000"):
        configuration(max_cache_size=5001)


@pytest.mark.parametrize("dimensions", [2048, 2049])
async def test_setup_and_runtime_share_projection_boundary(
    dimensions: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(
        provider="mock", max_cache_size=4096, mock_embedding_dimensions=dimensions
    )
    active = Redis.from_url(
        URL,
        decode_responses=False,
        protocol=2,
        retry=Retry(NoBackoff(), 0),
        socket_timeout=30,
        socket_connect_timeout=30,
    )
    calls: list[str] = []
    original_close = active.aclose

    def create(*args: object, **kwargs: object) -> Redis:
        calls.append("client")
        return active

    async def execute(self: Redis, *args: object, **kwargs: object) -> bytes:
        assert args == ("PING",)
        calls.append("ping")
        return b"PONG"

    async def initialize(self: RedisStore, *, initialization_client: Redis) -> None:
        assert self.embedding_space.dimensions == dimensions
        assert initialization_client is active
        calls.append("initialize")

    async def validate(self: RedisStore) -> None:
        assert self.embedding_space.dimensions == dimensions
        calls.append("validate")

    async def close(*, close_connection_pool: bool) -> None:
        assert close_connection_pool
        calls.append("close")
        await original_close(close_connection_pool=True)

    monkeypatch.setattr(setup, "from_url", create)
    monkeypatch.setattr(Redis, "from_url", create)
    monkeypatch.setattr(Redis, "execute_command", execute)
    monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    monkeypatch.setattr(RedisStore, "validate_schema", validate)
    monkeypatch.setattr(active, "aclose", close)
    if dimensions == 2048:
        await setup.initialize_redis(settings, initialization_url=URL)
        assert calls == ["client", "initialize", "close"]
        calls.clear()
        async with factory.cache_backend_lifespan(
            settings, dimensions=dimensions, embedding_space="mock:stable-token-hash-v1"
        ):
            assert calls == ["client", "ping", "validate"]
        assert calls == ["client", "ping", "validate", "close"]
    else:
        with pytest.raises(CacheStorageError, match="Redis setup failed"):
            await setup.initialize_redis(settings, initialization_url=URL)
        assert calls == ["client", "close"]
        calls.clear()
        with pytest.raises(CacheStorageError, match="Official cache setup"):
            async with factory.cache_backend_lifespan(
                settings,
                dimensions=dimensions,
                embedding_space="mock:stable-token-hash-v1",
            ):
                pytest.fail("Projection above 64 MiB must be rejected")
        assert calls == []
        with pytest.raises(CacheConfigurationError):
            RedisStore(
                client=active,
                embedding_space=EmbeddingSpace(
                    identity="custom:v1", dimensions=dimensions
                ),
                max_size=4096,
            )
