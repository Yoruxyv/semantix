from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import Request

from app.core.config import Settings


def _trusted_networks(settings: Settings) -> tuple[IPv4Network | IPv6Network, ...]:
    return tuple(
        ip_network(value, strict=False) for value in settings.trusted_proxy_cidrs
    )


def _is_trusted(address: str, settings: Settings) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in _trusted_networks(settings))


def client_address(request: Request) -> str:
    peer = "unknown" if request.client is None else request.client.host
    settings: Settings = request.app.state.settings
    if not _is_trusted(peer, settings):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is None:
        return peer

    chain = [item.strip() for item in forwarded.split(",")]
    if not chain or any(not item for item in chain):
        return peer
    try:
        for item in chain:
            ip_address(item)
    except ValueError:
        return peer

    for item in reversed(chain):
        if not _is_trusted(item, settings):
            return item
    return chain[0]
