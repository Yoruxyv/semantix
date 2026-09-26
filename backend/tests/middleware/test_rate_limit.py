from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app

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
        create_app(settings("1/minute", trusted_proxy_cidrs=["172.28.0.0/24"])),
        client=("172.28.0.5", 50_000),
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
    assert second.status_code == 200


def test_production_gateway_uses_observed_peer_for_one_rate_limit_bucket() -> None:
    nginx_config = (
        Path(__file__).resolve().parents[3] / "frontend" / "nginx.conf"
    ).read_text(encoding="utf-8")
    assert nginx_config.count("proxy_set_header X-Forwarded-For $remote_addr;") == 3
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
