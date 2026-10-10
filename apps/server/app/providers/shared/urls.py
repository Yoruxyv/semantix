"""URL normalization policies shared by provider configuration.

These are structural checks, not DNS/address filtering, SSRF protection,
service authentication or reachability probes. Hosted and Ollama policies differ.
"""

from urllib.parse import urlparse


def normalize_hosted_provider_url(
    value: str | None,
) -> str | None:
    """Normalize an optional absolute HTTPS base URL, allowing endpoint paths.

    Strip surrounding whitespace and trailing slashes before parsing. Require a
    hostname and valid parsed port; reject embedded credentials and nonempty query
    or fragment content. Paths/path parameters are not otherwise rejected.

    Args:
        value: Optional configured URL; None or whitespace-only text becomes None.

    Returns:
        Normalized URL text, without DNS resolution or canonicalizing the hostname.

    Raises:
        ValueError: URL parsing, authority/port or the hosted policy is invalid.
    """
    if value is None or not value.strip():
        return None

    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Provider base URLs contain an invalid port") from exc

    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Provider base URLs must be absolute HTTPS URLs "
            "without embedded credentials"
        )
    return normalized


def normalize_ollama_url(value: str) -> str:
    """Normalize a required HTTP/HTTPS origin for Ollama.

    Strip surrounding whitespace and trailing slashes before parsing. Require a
    hostname and valid parsed port, with no credentials, non-root path, path
    parameters, query or fragment content. Blank text fails the origin policy.
    HTTP is permitted; the origin need not resolve to a local/private address.

    Args:
        value: Configured Ollama origin.

    Returns:
        Normalized origin without probing the endpoint.

    Raises:
        ValueError: URL parsing, authority/port or the origin policy is invalid.
    """
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("OLLAMA_BASE_URL contains an invalid port") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "OLLAMA_BASE_URL must be an absolute HTTP or HTTPS origin "
            "without credentials, paths, queries, or fragments"
        )
    return normalized
