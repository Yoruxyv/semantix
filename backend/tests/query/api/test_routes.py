from collections.abc import Sequence
from typing import get_args, get_type_hints

import pytest
from fastapi.testclient import TestClient

from app.cache.application.service import SemanticCache
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE
from app.core.config import Settings
from app.core.exceptions import ProviderRequestError
from app.core.limits import MAX_REQUEST_CACHE_TTL_SECONDS, MAX_RESPONSE_LENGTH
from app.factory import create_app
from app.query.api.router import query
from app.query.api.schemas import QueryRequest
from app.query.application.service import QueryService
from tests.support import memory_backend, unit_vector


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return unit_vector()


class Provider:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        return "answer"


class FailingProvider:
    async def generate(self, prompt: str) -> str:
        raise ProviderRequestError(
            "test-only-placeholder",
        )


class OversizedProvider:
    async def generate(self, prompt: str) -> str:
        return "x" * (MAX_RESPONSE_LENGTH + 1)


def query_service(
    provider: Provider | FailingProvider | OversizedProvider,
) -> QueryService:
    return QueryService(
        SemanticCache(
            Embeddings(),
            memory_backend(),
            0.92,
        ),
        provider,
    )


def test_query_route(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.query_service = query_service(Provider())
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"] == "answer"
    assert payload["cache_hit"] is False
    assert payload["provider_called"] is True
    assert "embedding" not in payload


def test_empty_prompt(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/query",
            json={"prompt": "   "},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("response", "client-controlled response"),
        ("embedding", [1.0, 0.0]),
        ("cache_key", "0" * 64),
        ("created_at", "2026-01-01T00:00:00Z"),
    ],
)
def test_query_route_rejects_client_supplied_cache_fields(
    settings: Settings,
    field: str,
    value: object,
) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one", field: value},
        )

    assert response.status_code == 422


def test_query_request_cache_policy_defaults_and_overrides() -> None:
    default_request = QueryRequest(prompt="one")
    assert default_request.namespace == DEFAULT_CACHE_NAMESPACE
    assert default_request.cache_policy.namespace == DEFAULT_CACHE_NAMESPACE
    assert default_request.cache_policy.read_enabled
    assert default_request.cache_policy.write_enabled
    assert default_request.cache_ttl_seconds is None

    disabled = QueryRequest(
        prompt="one",
        namespace="tenant-alpha",
        cache_enabled=False,
    )
    assert disabled.cache_policy.namespace == "tenant-alpha"
    assert not disabled.cache_policy.read_enabled
    assert not disabled.cache_policy.write_enabled

    private = QueryRequest(prompt="one", private=True)
    assert not private.cache_policy.read_enabled
    assert not private.cache_policy.write_enabled

    read_bypass = QueryRequest(
        prompt="one",
        cache_read_enabled=False,
    )
    assert not read_bypass.cache_policy.read_enabled
    assert read_bypass.cache_policy.write_enabled


@pytest.mark.parametrize(
    "cache_ttl_seconds",
    [None, 1, MAX_REQUEST_CACHE_TTL_SECONDS],
)
def test_query_route_accepts_supported_cache_ttl_values(
    settings: Settings,
    cache_ttl_seconds: int | None,
) -> None:
    app = create_app(settings)
    provider = Provider()
    payload: dict[str, object] = {"prompt": "one"}
    if cache_ttl_seconds is not None:
        payload["cache_ttl_seconds"] = cache_ttl_seconds

    with TestClient(app) as client:
        app.state.query_service = query_service(provider)
        response = client.post("/api/v1/query", json=payload)

    assert response.status_code == 200
    assert provider.call_count == 1


def test_query_route_accepts_explicit_null_cache_ttl(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.query_service = query_service(provider)
        response = client.post(
            "/api/v1/query",
            json={
                "prompt": "one",
                "cache_write_enabled": False,
                "cache_ttl_seconds": None,
            },
        )

    assert response.status_code == 200
    assert provider.call_count == 1


def test_query_route_accepts_cache_ttl_for_refresh_policy(settings: Settings) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.query_service = query_service(provider)
        response = client.post(
            "/api/v1/query",
            json={
                "prompt": "one",
                "cache_read_enabled": False,
                "cache_ttl_seconds": 60,
            },
        )

    assert response.status_code == 200
    assert provider.call_count == 1


@pytest.mark.parametrize(
    "cache_ttl_seconds",
    [0, -1, MAX_REQUEST_CACHE_TTL_SECONDS + 1, True, 1.5, "60"],
)
def test_query_route_rejects_invalid_cache_ttl_values_before_provider(
    settings: Settings,
    cache_ttl_seconds: object,
) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.query_service = query_service(provider)
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one", "cache_ttl_seconds": cache_ttl_seconds},
        )

    assert response.status_code == 422
    assert provider.call_count == 0


@pytest.mark.parametrize(
    "policy_fields",
    [
        {"cache_write_enabled": False},
        {"cache_enabled": False},
        {"private": True},
    ],
)
def test_query_route_rejects_ttl_for_non_writing_policy_before_provider(
    settings: Settings,
    policy_fields: dict[str, bool],
) -> None:
    app = create_app(settings)
    provider = Provider()

    with TestClient(app) as client:
        app.state.query_service = query_service(provider)
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one", "cache_ttl_seconds": 60, **policy_fields},
        )

    assert response.status_code == 422
    assert provider.call_count == 0


def test_query_route_depends_on_query_service() -> None:
    annotation = get_type_hints(
        query,
        include_extras=True,
    )["service"]

    assert get_args(annotation)[0] is QueryService


def test_provider_error_response_hides_api_key(
    settings: Settings,
) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.query_service = query_service(FailingProvider())
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one"},
        )

    assert response.status_code == 502
    assert response.json()["error"] == "upstream_error"
    assert "test-only-placeholder" not in response.text


def test_oversized_provider_response_uses_stable_upstream_error(
    settings: Settings,
) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.query_service = query_service(OversizedProvider())
        response = client.post(
            "/api/v1/query",
            json={"prompt": "one"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": "invalid_upstream_response",
        "detail": "The AI service returned an invalid response.",
    }
