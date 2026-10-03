import pytest
from pydantic import ValidationError

from app.core.config import Settings

ORIGINS = ["http://localhost:5173"]


def settings(**values: object) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "hf_api_key": None,
            "cache_backend": "memory",
            "database_url": None,
            "allowed_origins": ORIGINS,
            **values,
        }
    )


def test_ollama_generation_only_requires_only_generation_fields() -> None:
    configured = settings(
        generation_provider="ollama",
        ollama_generation_model="gemma3",
    )

    assert configured.ollama_embedding_model is None
    assert configured.ollama_embedding_dimensions is None


def test_ollama_embedding_only_requires_only_embedding_fields() -> None:
    configured = settings(
        embedding_provider="ollama",
        ollama_embedding_model="embeddinggemma",
        ollama_embedding_dimensions=768,
    )

    assert configured.ollama_generation_model is None
    assert configured.embedding_dimensions == 768
    assert configured.embedding_space == "ollama:embeddinggemma"


def test_ollama_supports_both_capabilities() -> None:
    configured = settings(
        embedding_provider="ollama",
        generation_provider="ollama",
        ollama_embedding_model="embeddinggemma",
        ollama_generation_model="gemma3",
        ollama_embedding_dimensions=768,
    )

    assert configured.embedding_provider == "ollama"
    assert configured.generation_provider == "ollama"


@pytest.mark.parametrize(
    ("values", "missing_name"),
    [
        (
            {
                "generation_provider": "ollama",
                "ollama_generation_model": None,
            },
            "OLLAMA_GENERATION_MODEL",
        ),
        (
            {
                "embedding_provider": "ollama",
                "ollama_embedding_model": None,
                "ollama_embedding_dimensions": 384,
            },
            "OLLAMA_EMBEDDING_MODEL",
        ),
        (
            {
                "embedding_provider": "ollama",
                "ollama_embedding_model": "embeddinggemma",
                "ollama_embedding_dimensions": None,
            },
            "OLLAMA_EMBEDDING_DIMENSIONS",
        ),
    ],
)
def test_selected_ollama_capability_requires_its_configuration(
    values: dict[str, object],
    missing_name: str,
) -> None:
    with pytest.raises(ValidationError, match=missing_name):
        settings(**values)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434",
        "http://ollama:11434",
        "https://ollama.internal",
    ],
)
def test_accepts_safe_ollama_origins(base_url: str) -> None:
    configured = settings(ollama_base_url=base_url)

    assert configured.ollama_base_url == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "localhost:11434",
        "ftp://localhost:11434",
        "http://",
        "http://user:password@localhost:11434",
        "http://localhost:11434/api",
        "http://localhost:11434?token=value",
        "http://localhost:11434#fragment",
        "http://localhost:not-a-port",
    ],
)
def test_rejects_unsafe_ollama_urls(base_url: str) -> None:
    with pytest.raises(ValidationError, match="OLLAMA_BASE_URL"):
        settings(ollama_base_url=base_url)


def test_hosted_provider_http_remains_rejected() -> None:
    with pytest.raises(ValidationError, match="absolute HTTPS"):
        settings(
            embedding_provider="openai",
            openai_api_key="openai-key",
            openai_base_url="http://api.openai.test/v1",
            openai_embedding_model="embedding-model",
            openai_embedding_dimensions=384,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "hf_inference_base_url",
        "hf_chat_base_url",
        "openai_base_url",
        "anthropic_base_url",
        "gemini_base_url",
    ],
)
@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.test:not-a-port",
        "https://api.example.test:65536",
        "https://:443/v1",
        "https://user:secret@api.example.test/v1",
        "https://api.example.test/v1?token=secret",
        "https://api.example.test/v1#fragment",
    ],
)
def test_all_hosted_provider_urls_fail_fast_when_malformed(
    field_name: str,
    base_url: str,
) -> None:
    with pytest.raises(ValidationError, match="Provider base URLs"):
        settings(**{field_name: base_url})


def test_unselected_ollama_models_are_not_required() -> None:
    configured = settings()

    assert configured.ollama_embedding_model is None
    assert configured.ollama_generation_model is None


def test_mock_providers_require_no_credentials() -> None:
    configured = settings(mock_embedding_dimensions=32)

    assert configured.embedding_dimensions == 32
    assert configured.embedding_space == "mock:stable-token-hash-v1"
    assert configured.configured_secrets() == ()


def test_provider_response_limit_defaults_to_four_mibibytes() -> None:
    configured = settings()

    assert configured.provider_max_response_bytes == 4_194_304


def test_provider_response_limit_is_configurable() -> None:
    configured = settings(provider_max_response_bytes=8_388_608)

    assert configured.provider_max_response_bytes == 8_388_608


def test_provider_response_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="provider_max_response_bytes"):
        settings(provider_max_response_bytes=0)


def test_evaluation_timeout_is_bounded() -> None:
    configured = settings(evaluation_timeout_seconds=45)

    assert configured.evaluation_timeout_seconds == 45

    with pytest.raises(ValidationError, match="evaluation_timeout_seconds"):
        settings(evaluation_timeout_seconds=0)
    with pytest.raises(ValidationError, match="evaluation_timeout_seconds"):
        settings(evaluation_timeout_seconds=3_601)


def test_evaluation_import_limits_are_bounded_and_configurable() -> None:
    configured = settings(
        evaluation_dataset_max_cases=75,
        evaluation_dataset_max_decoded_bytes=65_536,
        evaluation_max_workload_queries=300,
    )

    assert configured.evaluation_dataset_max_cases == 75
    assert configured.evaluation_dataset_max_decoded_bytes == 65_536
    assert configured.evaluation_max_workload_queries == 300

    with pytest.raises(ValidationError, match="evaluation_dataset_max_cases"):
        settings(evaluation_dataset_max_cases=0)
    with pytest.raises(
        ValidationError,
        match="evaluation_dataset_max_decoded_bytes",
    ):
        settings(evaluation_dataset_max_decoded_bytes=1_023)
    with pytest.raises(
        ValidationError,
        match="evaluation_max_workload_queries",
    ):
        settings(evaluation_max_workload_queries=2_501)


@pytest.mark.parametrize("port", ["not-a-port", "-1", "65536"])
def test_database_url_rejects_invalid_ports(port: str) -> None:
    with pytest.raises(ValidationError, match=r"DATABASE_URL.*port"):
        settings(
            cache_backend="pgvector",
            database_url=(f"postgresql://user:secret@database:{port}/semantix"),
        )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:secret@localhost/semantix",
        "postgresql://user:secret@[::1]:5432/semantix",
        (
            "postgresql://user%40example:p%3Ass%2Fword@"
            "database:5432/semantix?sslmode=require"
        ),
    ],
)
def test_database_url_preserves_valid_boundary_cases(
    database_url: str,
) -> None:
    configured = settings(
        cache_backend="pgvector",
        database_url=database_url,
    )

    assert configured.database_dsn == database_url


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test/path",
        "https://example.test/;params",
        "https://example.test?query=yes",
        "https://example.test#fragment",
        "https://user:password@example.test",
        "https://example.test:not-a-port",
        "https://example.test:-1",
        "https://example.test:65536",
        "https://:443",
    ],
)
def test_cors_origins_reject_non_origin_urls(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS origin"):
        settings(allowed_origins=[origin])


@pytest.mark.parametrize(
    ("origin", "normalized"),
    [
        ("http://localhost", "http://localhost"),
        ("http://localhost:5173/", "http://localhost:5173"),
        ("http://[::1]", "http://[::1]"),
        ("https://[2001:db8::1]:8443/", "https://[2001:db8::1]:8443"),
    ],
)
def test_cors_origins_preserve_valid_boundary_cases(
    origin: str,
    normalized: str,
) -> None:
    configured = settings(allowed_origins=[origin])

    assert configured.allowed_origins == [normalized]
