"""URL normalization policies shared by provider configuration."""

from urllib.parse import urlparse


def normalize_hosted_provider_url(
    value: str | None,
) -> str | None:
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
