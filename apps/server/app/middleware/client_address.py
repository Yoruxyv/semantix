"""Resolve the client key used by rate limits and session lockout tracking.

Trust is defined by deployment CIDRs and the immediate peer, not by the
presence of forwarding headers. See ``docs/operations/deployment.md`` for
the gateway and host-proxy boundary; trusted proxies must sanitize headers.
"""

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
    """Resolve an address through explicitly trusted X-Forwarded-For hops.

    Ignore forwarding headers from untrusted peers. For trusted peers, reject
    the entire chain if any address is invalid, otherwise walk right to left
    to the first untrusted address. If every hop is trusted, use the leftmost.
    Other forwarding headers are not consulted.

    Args:
        request: Request with the immediate peer and application proxy settings.

    Returns:
        Resolved address, the peer on absent or malformed forwarding data, or
        ``unknown`` when no client peer is available.
    """
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
