from typing import cast

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import Scope

from app.core.config import Settings
from app.middleware.client_address import client_address


def settings(trusted_proxy_cidrs: list[str]) -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )


def request_for(
    peer: str,
    forwarded_for: str | None,
    trusted_proxy_cidrs: list[str],
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    application = Starlette()
    application.state.settings = settings(trusted_proxy_cidrs)
    scope = cast(
        Scope,
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
            "app": application,
        },
    )
    return Request(scope)


def test_spoofed_forwarded_header_is_ignored_from_an_untrusted_peer() -> None:
    request = request_for("203.0.113.20", "198.51.100.10", ["172.28.0.0/24"])
    assert client_address(request) == "203.0.113.20"


def test_origin_is_resolved_through_trusted_proxy_hops() -> None:
    request = request_for(
        "172.28.0.5",
        "198.51.100.10, 172.28.0.8",
        ["172.28.0.0/24"],
    )
    assert client_address(request) == "198.51.100.10"


def test_gateway_observed_peer_is_authoritative() -> None:
    request = request_for("172.28.0.2", "172.28.0.1", ["172.28.0.0/24"])
    assert client_address(request) == "172.28.0.1"


def test_malformed_forwarded_header_fails_closed_to_the_peer() -> None:
    for forwarded in ("not-an-ip", "198.51.100.10,,203.0.113.50"):
        request = request_for("172.28.0.5", forwarded, ["172.28.0.0/24"])
        assert client_address(request) == "172.28.0.5"


def test_unknown_intermediate_proxy_cannot_claim_an_earlier_address() -> None:
    request = request_for(
        "172.28.0.5",
        "198.51.100.10, 203.0.113.50",
        ["172.28.0.0/24"],
    )
    assert client_address(request) == "203.0.113.50"
