from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import CoordinationStorageError, SharedRateLimitExceeded
from app.factory import create_app
from app.middleware.rate_limit import app_rate_limit, limiter

RATE_LIMITED_PATH = "/api/v1/cache/stats"


def settings(
    rate_limit: str,
    *,
    trusted_proxy_cidrs: list[str] | None = None,
) -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        rate_limit=rate_limit,
        trusted_proxy_cidrs=trusted_proxy_cidrs or [],
    )


def assert_rate_limited(response_status: int, payload: object) -> None:
    assert response_status == 429
    assert payload == {
        "error": "rate_limit_exceeded",
        "detail": "Too many requests. Please try again later.",
    }


def test_injected_app_settings_control_the_route_limit() -> None:
    with TestClient(
        create_app(settings("1/minute")),
        client=("203.0.113.10", 50_000),
    ) as client:
        assert client.get(RATE_LIMITED_PATH).status_code == 200
        response = client.get(RATE_LIMITED_PATH)

    assert_rate_limited(response.status_code, response.json())


def test_untrusted_forwarded_address_cannot_evade_the_limit() -> None:
    with TestClient(
        create_app(settings("1/minute", trusted_proxy_cidrs=["172.28.0.0/24"])),
        client=("203.0.113.10", 50_000),
    ) as client:
        first = client.get(
            RATE_LIMITED_PATH,
            headers={"X-Forwarded-For": "198.51.100.10"},
        )
        second = client.get(
            RATE_LIMITED_PATH,
            headers={"X-Forwarded-For": "198.51.100.11"},
        )

    assert first.status_code == 200
    assert_rate_limited(second.status_code, second.json())


def test_trusted_proxy_clients_receive_independent_limits() -> None:
    with TestClient(
        create_app(settings("2/minute", trusted_proxy_cidrs=["172.28.0.0/24"])),
        client=("172.28.0.5", 50_000),
    ) as client:
        statuses = [
            client.get(
                RATE_LIMITED_PATH, headers={"X-Forwarded-For": address}
            ).status_code
            for address in (
                "198.51.100.10",
                "198.51.100.10",
                "198.51.100.10",
                "198.51.100.11",
                "198.51.100.11",
            )
        ]

    assert statuses == [200, 200, 429, 200, 200]


def test_production_gateway_requires_authenticated_host_proxy() -> None:
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    nginx_config = (frontend / "nginx.conf").read_text(encoding="utf-8")
    assert "map_hash_bucket_size 128;" in nginx_config
    assert (
        'map "$remote_addr|$http_x_semantix_host_proxy_token" $semantix_forwarded_for {'
        in nginx_config
    )
    assert "default $remote_addr;" in nginx_config
    assert "include /etc/nginx/host-proxy.conf;" in nginx_config
    assert all(
        not line.strip() or line.lstrip().startswith("#")
        for line in (frontend / "host-proxy.disabled.conf")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert (
        nginx_config.count("proxy_set_header X-Forwarded-For $semantix_forwarded_for;")
        == 3
    )
    assert nginx_config.count('proxy_set_header X-Real-IP "";') == 3
    assert nginx_config.count('proxy_set_header Forwarded "";') == 3
    assert nginx_config.count('proxy_set_header X-Semantix-Host-Proxy-Token "";') == 3
    assert "$proxy_add_x_forwarded_for" not in nginx_config

    with TestClient(
        create_app(settings("2/minute", trusted_proxy_cidrs=["172.28.0.0/24"])),
        client=("172.28.0.2", 50_000),
    ) as client:
        statuses = [
            client.get(
                RATE_LIMITED_PATH,
                headers={"X-Forwarded-For": "172.28.0.1"},
            ).status_code
            for _ in range(4)
        ]

    assert statuses == [200, 200, 429, 429]


def test_limiter_state_and_settings_are_scoped_per_application() -> None:
    first_app = create_app(settings("1/minute"))
    second_app = create_app(settings("2/minute"))

    with TestClient(first_app, client=("203.0.113.10", 50_000)) as first:
        assert first.get(RATE_LIMITED_PATH).status_code == 200
        assert first.get(RATE_LIMITED_PATH).status_code == 429

    with TestClient(second_app, client=("203.0.113.10", 50_000)) as second:
        assert second.get(RATE_LIMITED_PATH).status_code == 200
        assert second.get(RATE_LIMITED_PATH).status_code == 200
        assert second.get(RATE_LIMITED_PATH).status_code == 429


@pytest.mark.asyncio
async def test_postgres_limiter_uses_one_authority_without_local_fallback() -> None:
    class FakeCoordination:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str, int, int]] = []
            self.unavailable = False

        async def allow_request(
            self, address: str, route: str, quota: str, amount: int, seconds: int
        ) -> bool:
            if self.unavailable:
                raise CoordinationStorageError
            self.calls.append((address, route, quota, amount, seconds))
            return len(self.calls) == 1

    @limiter.limit(app_rate_limit)
    async def limited(request: Request) -> str:
        return "accepted"

    application = FastAPI()
    application.state.settings = settings("1/minute").model_copy(
        update={"coordination_backend": "postgres"}
    )
    coordinator = FakeCoordination()
    application.state.coordination = coordinator
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/cache/stats",
            "headers": [],
            "client": ("198.51.100.10", 50000),
            "app": application,
            "route": SimpleNamespace(path="/api/v1/cache/stats"),
        }
    )

    assert await limited(request=request) == "accepted"
    with pytest.raises(SharedRateLimitExceeded):
        await limited(request=request)
    assert coordinator.calls == [
        ("198.51.100.10", "/api/v1/cache/stats", "1/minute", 1, 60),
        ("198.51.100.10", "/api/v1/cache/stats", "1/minute", 1, 60),
    ]
    coordinator.unavailable = True
    with pytest.raises(CoordinationStorageError):
        await limited(request=request)
