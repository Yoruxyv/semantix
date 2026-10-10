"""Built-in provider requirements and model-based selection metadata.

ProviderName defines stripped, case-preserving names shared with registration;
name validity does not establish that a provider exists or supports a capability.
``app.providers.registry`` owns custom registration and metadata resolution.
Built-in selectors here reject custom names rather than resolving the registry.

Required fields are checked only for recognized selected built-in capabilities.
Settings owns numeric bounds and URL normalization; these checks do no network
I/O. Hugging Face/OpenAI/Gemini embedding needs its key, base URL, model and
dimensions; hosted generation also supports Anthropic and needs key/URL/model.
Ollama needs URL and selected model/dimensions without a required API key. Mock
needs embedding dimensions, uses stable-token-hash-v1/mock-prefix-v1 model IDs
and requires no credentials. Configuration strings do not prove model behavior.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from pydantic import SecretStr, StringConstraints

if TYPE_CHECKING:
    from app.core.config import Settings

PROVIDER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,49}$"
ProviderName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=50,
        pattern=PROVIDER_NAME_PATTERN,
    ),
]
EmbeddingProviderName = ProviderName
GenerationProviderName = ProviderName
MOCK_EMBEDDING_MODEL_ID = "stable-token-hash-v1"
MOCK_GENERATION_MODEL_ID = "mock-prefix-v1"


def validate_provider_name(value: str) -> str:
    """Strip whitespace and validate a case-preserving registration name.

    The first character is ASCII alphanumeric; the remaining characters may also
    include dot, underscore, hyphen or colon, up to 50 characters total.

    Args:
        value: Provider name to normalize, without a registry lookup.

    Returns:
        Stripped name with its original case.

    Raises:
        ValueError: The stripped name does not match the shared name pattern.
    """
    normalized = value.strip()
    if re.fullmatch(PROVIDER_NAME_PATTERN, normalized) is None:
        raise ValueError(
            "Provider names must be 1-50 characters and contain only letters, "
            "digits, '.', '_', '-', or ':'"
        )
    return normalized


def validate_provider_configuration(settings: Settings) -> None:
    """Check required fields for the selected recognized built-in capabilities.

    Embedding checks precede generation checks; the first missing/blank requirement
    raises. Unknown/custom names are left to registry selection, not rejected here.
    Settings field validation owns positive numeric bounds and URL policies; the
    dimension helper here checks presence only. This does not probe credentials,
    remote models or connectivity, or validate custom metadata.

    Args:
        settings: Parsed server settings with independent provider selections.

    Raises:
        ValueError: A recognized selected built-in lacks a required field.
    """
    _validate_embedding_provider(settings)
    _validate_generation_provider(settings)


def selected_embedding_dimensions(settings: Settings) -> int:
    """Select the configured dimension of a recognized built-in embedding provider.

    Args:
        settings: Settings whose selected built-in configuration was validated.

    Returns:
        Configured component count, without inspecting an actual embedding.

    Raises:
        RuntimeError: The provider is custom or its dimension is missing.
    """
    match settings.embedding_provider:
        case "huggingface":
            value = settings.hf_embedding_dimensions
        case "openai":
            value = settings.openai_embedding_dimensions
        case "gemini":
            value = settings.gemini_embedding_dimensions
        case "ollama":
            value = settings.ollama_embedding_dimensions
        case "mock":
            value = settings.mock_embedding_dimensions
        case _:
            raise RuntimeError(
                "Custom embedding metadata is resolved by the provider registry"
            )

    if value is None:
        raise RuntimeError("Selected embedding dimensions were not validated")
    return value


def selected_embedding_space(settings: Settings) -> str:
    """Build the built-in cache space identity as provider:model.

    Mock uses its fixed embedding model ID. Dimensions are a separate binding input;
    endpoint, credentials and external model revisions are not included in this
    string. Equal identities alone do not verify semantic compatibility.

    Args:
        settings: Settings whose selected built-in model was validated.

    Returns:
        Provider/model identity; custom spaces come from registry metadata.

    Raises:
        RuntimeError: The provider is custom or its model is missing.
    """
    match settings.embedding_provider:
        case "huggingface":
            model = settings.hf_embedding_model
        case "openai":
            model = settings.openai_embedding_model
        case "gemini":
            model = settings.gemini_embedding_model
        case "ollama":
            model = settings.ollama_embedding_model
        case "mock":
            model = MOCK_EMBEDDING_MODEL_ID
        case _:
            raise RuntimeError(
                "Custom embedding metadata is resolved by the provider registry"
            )

    if model is None:
        raise RuntimeError("Selected embedding model was not validated")
    return f"{settings.embedding_provider}:{model}"


def selected_generation_configuration(settings: Settings) -> dict[str, object]:
    """Select built-in fields consumed by generation configuration fingerprinting.

    The mapping contains provider, model, max_new_tokens and max_response_bytes in
    that order. Mock uses its fixed generation model ID. API keys and base URLs are
    excluded, but caller-supplied model text is not sanitized for arbitrary logging.
    This mapping is not inherently secret-safe or proof of actual provider behavior.

    Args:
        settings: Settings whose selected built-in generation model was validated.

    Returns:
        A new dictionary of the four existing configuration fields.

    Raises:
        RuntimeError: The provider is custom or its model is missing.
    """
    match settings.generation_provider:
        case "huggingface":
            model = settings.hf_generation_model
        case "openai":
            model = settings.openai_generation_model
        case "anthropic":
            model = settings.anthropic_generation_model
        case "gemini":
            model = settings.gemini_generation_model
        case "ollama":
            model = settings.ollama_generation_model
        case "mock":
            model = MOCK_GENERATION_MODEL_ID
        case _:
            raise RuntimeError(
                "Custom generation metadata is resolved by the provider registry"
            )

    if model is None:
        raise RuntimeError("Selected generation model was not validated")

    return {
        "provider": settings.generation_provider,
        "model": model,
        "max_new_tokens": settings.generation_max_new_tokens,
        "max_response_bytes": settings.provider_max_response_bytes,
    }


def _validate_embedding_provider(settings: Settings) -> None:
    match settings.embedding_provider:
        case "huggingface":
            _require_secret(settings.hf_api_key, "HF_API_KEY")
            _require_text(
                settings.hf_inference_base_url,
                "HF_INFERENCE_BASE_URL",
            )
            _require_text(
                settings.hf_embedding_model,
                "HF_EMBEDDING_MODEL",
            )
            _require_dimensions(
                settings.hf_embedding_dimensions,
                "HF_EMBEDDING_DIMENSIONS",
            )
        case "openai":
            _require_secret(settings.openai_api_key, "OPENAI_API_KEY")
            _require_text(settings.openai_base_url, "OPENAI_BASE_URL")
            _require_text(
                settings.openai_embedding_model,
                "OPENAI_EMBEDDING_MODEL",
            )
            _require_dimensions(
                settings.openai_embedding_dimensions,
                "OPENAI_EMBEDDING_DIMENSIONS",
            )
        case "gemini":
            _require_secret(settings.gemini_api_key, "GEMINI_API_KEY")
            _require_text(settings.gemini_base_url, "GEMINI_BASE_URL")
            _require_text(
                settings.gemini_embedding_model,
                "GEMINI_EMBEDDING_MODEL",
            )
            _require_dimensions(
                settings.gemini_embedding_dimensions,
                "GEMINI_EMBEDDING_DIMENSIONS",
            )
        case "ollama":
            _require_text(settings.ollama_base_url, "OLLAMA_BASE_URL")
            _require_text(
                settings.ollama_embedding_model,
                "OLLAMA_EMBEDDING_MODEL",
            )
            _require_dimensions(
                settings.ollama_embedding_dimensions,
                "OLLAMA_EMBEDDING_DIMENSIONS",
            )
        case "mock":
            _require_dimensions(
                settings.mock_embedding_dimensions,
                "MOCK_EMBEDDING_DIMENSIONS",
            )


def _validate_generation_provider(settings: Settings) -> None:
    match settings.generation_provider:
        case "huggingface":
            _require_secret(settings.hf_api_key, "HF_API_KEY")
            _require_text(settings.hf_chat_base_url, "HF_CHAT_BASE_URL")
            _require_text(
                settings.hf_generation_model,
                "HF_GENERATION_MODEL",
            )
        case "openai":
            _require_secret(settings.openai_api_key, "OPENAI_API_KEY")
            _require_text(settings.openai_base_url, "OPENAI_BASE_URL")
            _require_text(
                settings.openai_generation_model,
                "OPENAI_GENERATION_MODEL",
            )
        case "anthropic":
            _require_secret(
                settings.anthropic_api_key,
                "ANTHROPIC_API_KEY",
            )
            _require_text(
                settings.anthropic_base_url,
                "ANTHROPIC_BASE_URL",
            )
            _require_text(
                settings.anthropic_generation_model,
                "ANTHROPIC_GENERATION_MODEL",
            )
        case "gemini":
            _require_secret(settings.gemini_api_key, "GEMINI_API_KEY")
            _require_text(settings.gemini_base_url, "GEMINI_BASE_URL")
            _require_text(
                settings.gemini_generation_model,
                "GEMINI_GENERATION_MODEL",
            )
        case "ollama":
            _require_text(settings.ollama_base_url, "OLLAMA_BASE_URL")
            _require_text(
                settings.ollama_generation_model,
                "OLLAMA_GENERATION_MODEL",
            )
        case "mock":
            pass


def _require_secret(
    value: SecretStr | None,
    environment_name: str,
) -> None:
    if value is None or not value.get_secret_value().strip():
        raise ValueError(f"{environment_name} is required for the selected provider")


def _require_text(
    value: str | None,
    environment_name: str,
) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{environment_name} is required for the selected provider")


def _require_dimensions(
    value: int | None,
    environment_name: str,
) -> None:
    if value is None:
        raise ValueError(f"{environment_name} is required for the selected provider")
