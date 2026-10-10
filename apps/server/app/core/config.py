"""Validate deployment settings without opening providers or storage.

Settings reads case-insensitive environment names and ``.env`` values;
get_settings caches the resolved instance. Provider validation applies to
selected providers. Cache backend, coordination, dataset persistence and
run history are independent choices; any PostgreSQL feature requires the
runtime DATABASE_URL and shares one pool. Migration credentials belong to
deployment tooling, not Settings. ``auto`` migrates enabled coordination
and evaluation tables; official cache setup remains explicit in both modes.

AUTH_MODE=disabled grants the trusted-local-development admin. Token mode
requires unique principal names and SHA-256 token digests. A principal's
namespaces must be unique; ``*`` is allowed alone and only for admins.
Allowed CORS origins cannot be wildcards, and trusted proxy CIDRs define
which immediate peers may supply a forwarded address, not user identity.
"""

import re
from functools import lru_cache
from ipaddress import ip_network
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.limits import (
    DEFAULT_EVALUATION_DATASET_CLEANUP_BATCH_SIZE,
    DEFAULT_EVALUATION_DATASET_DEFAULT_RETENTION_DAYS,
    DEFAULT_EVALUATION_DATASET_MAX_CASES,
    DEFAULT_EVALUATION_DATASET_MAX_DECODED_BYTES,
    DEFAULT_EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE,
    DEFAULT_EVALUATION_DATASET_MAX_RETENTION_DAYS,
    DEFAULT_EVALUATION_MAX_WORKLOAD_QUERIES,
    MAX_MEMORY_CACHE_SIZE,
)
from app.providers.configuration import (
    EmbeddingProviderName,
    GenerationProviderName,
    selected_embedding_dimensions,
    selected_embedding_space,
    validate_provider_configuration,
)
from app.providers.shared.urls import (
    normalize_hosted_provider_url,
    normalize_ollama_url,
)

CacheBackendName = Literal["memory", "pgvector", "redis"]
CoordinationBackendName = Literal["memory", "postgres"]
AuthMode = Literal["disabled", "token"]
AuthRole = Literal["viewer", "operator", "admin"]
DatabaseMigrationMode = Literal["auto", "external"]
EvaluationDatasetStorageMode = Literal["session", "postgres"]
EvaluationRunHistoryStorageMode = Literal["disabled", "postgres"]
DEFAULT_PROVIDER_MAX_RESPONSE_BYTES = 4_194_304
_AUTH_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class AuthPrincipalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: AuthRole
    namespaces: list[str] = Field(min_length=1)

    @field_validator("namespaces")
    @classmethod
    def validate_namespaces(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(
            value != "*" and _AUTH_NAMESPACE.fullmatch(value) is None
            for value in normalized
        ):
            raise ValueError("Authentication namespaces contain an invalid value")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Authentication namespaces cannot contain duplicates")
        if "*" in normalized and len(normalized) != 1:
            raise ValueError("Wildcard namespace access must be configured alone")
        return normalized


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        hide_input_in_errors=True,
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    embedding_provider: EmbeddingProviderName = "huggingface"
    generation_provider: GenerationProviderName = "huggingface"

    hf_api_key: SecretStr | None = None
    hf_inference_base_url: str | None = (
        "https://router.huggingface.co/hf-inference/models"
    )
    hf_chat_base_url: str | None = "https://router.huggingface.co/v1"
    hf_embedding_model: str | None = "sentence-transformers/all-MiniLM-L6-v2"
    hf_generation_model: str | None = "Qwen/Qwen3-4B-Instruct-2507:nscale"
    hf_embedding_dimensions: int | None = Field(default=384, gt=0)

    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = "https://api.openai.com/v1"
    openai_embedding_model: str | None = None
    openai_generation_model: str | None = None
    openai_embedding_dimensions: int | None = Field(default=None, gt=0)

    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str | None = "https://api.anthropic.com"
    anthropic_generation_model: str | None = None

    gemini_api_key: SecretStr | None = None
    gemini_base_url: str | None = "https://generativelanguage.googleapis.com/v1beta"
    gemini_embedding_model: str | None = None
    gemini_generation_model: str | None = None
    gemini_embedding_dimensions: int | None = Field(default=None, gt=0)

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_embedding_model: str | None = None
    ollama_generation_model: str | None = None
    ollama_embedding_dimensions: int | None = Field(default=None, gt=0)

    mock_embedding_dimensions: int = Field(default=384, gt=0)
    mock_generation_delay_seconds: float = Field(default=0, ge=0, le=2)

    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    evaluation_timeout_seconds: float = Field(default=300.0, gt=0, le=3_600)
    evaluation_dataset_max_cases: int = Field(
        default=DEFAULT_EVALUATION_DATASET_MAX_CASES,
        ge=1,
        le=500,
    )
    evaluation_dataset_max_decoded_bytes: int = Field(
        default=DEFAULT_EVALUATION_DATASET_MAX_DECODED_BYTES,
        ge=1_024,
        le=1_048_576,
    )
    evaluation_max_workload_queries: int = Field(
        default=DEFAULT_EVALUATION_MAX_WORKLOAD_QUERIES,
        ge=1,
        le=2_500,
    )
    evaluation_dataset_storage: EvaluationDatasetStorageMode = "session"
    evaluation_dataset_max_persisted_per_namespace: int = Field(
        default=DEFAULT_EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE,
        ge=1,
        le=1_000,
    )
    evaluation_dataset_default_retention_days: int = Field(
        default=DEFAULT_EVALUATION_DATASET_DEFAULT_RETENTION_DAYS,
        ge=1,
        le=3_650,
    )
    evaluation_dataset_max_retention_days: int = Field(
        default=DEFAULT_EVALUATION_DATASET_MAX_RETENTION_DAYS,
        ge=1,
        le=3_650,
    )
    evaluation_dataset_cleanup_batch_size: int = Field(
        default=DEFAULT_EVALUATION_DATASET_CLEANUP_BATCH_SIZE,
        ge=1,
        le=1_000,
    )
    evaluation_run_history_storage: EvaluationRunHistoryStorageMode = "disabled"
    evaluation_run_history_retention_days: int | None = Field(default=None, ge=1)
    evaluation_run_history_max_per_namespace: int | None = Field(default=None, ge=1)
    evaluation_run_history_cleanup_batch_size: int | None = Field(default=None, ge=1)
    provider_max_response_bytes: int = Field(
        default=DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
        ge=1,
    )
    generation_max_new_tokens: int = Field(default=512, ge=1, le=2_048)
    prompt_typo_correction_enabled: bool = False
    prompt_typo_max_edit_distance: int = Field(default=2, ge=0, le=3)

    similarity_threshold: float = Field(default=0.92, ge=0, le=1)
    cache_backend: CacheBackendName = "memory"
    max_cache_size: int = Field(default=500, ge=1, le=100_000)
    cache_ttl_seconds: int | None = Field(default=3_600, gt=0)
    cache_pgvector_schema: str = Field(
        default="semantix_cache", pattern=r"^[a-z_][a-z0-9_]{0,62}$"
    )
    cache_pgvector_table_prefix: str = Field(
        default="workbench_", pattern=r"^[a-z_][a-z0-9_]{0,44}$"
    )
    redis_url: SecretStr | None = None
    redis_key_prefix: str = Field(
        default="semantix_workbench", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    redis_operation_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    redis_close_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    database_url: SecretStr | None = None
    database_pool_min_size: int = Field(default=1, ge=1, le=50)
    database_pool_max_size: int = Field(default=5, ge=1, le=50)
    database_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_command_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    database_migration_mode: DatabaseMigrationMode = "auto"
    coordination_backend: CoordinationBackendName = "memory"

    auth_mode: AuthMode = "disabled"
    auth_principals: list[AuthPrincipalSettings] = Field(
        default_factory=list[AuthPrincipalSettings]
    )
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = Field(default=65_536, ge=1_024, le=10_485_760)

    allowed_origins: list[str] = Field(min_length=1)
    rate_limit: str = Field(
        default="20/minute",
        pattern=r"^\d+/(second|minute|hour|day)$",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("embedding_provider", mode="before")
    @classmethod
    def reject_generation_only_embedding_provider(cls, value: object) -> object:
        if value == "anthropic":
            raise ValueError(
                "Anthropic supports generation only and cannot be used "
                "as EMBEDDING_PROVIDER"
            )
        return value

    @field_validator(
        "hf_inference_base_url",
        "hf_chat_base_url",
        "openai_base_url",
        "anthropic_base_url",
        "gemini_base_url",
    )
    @classmethod
    def normalize_provider_base_url(cls, value: str | None) -> str | None:
        return normalize_hosted_provider_url(value)

    @field_validator("ollama_base_url")
    @classmethod
    def normalize_ollama_base_url(cls, value: str) -> str:
        return normalize_ollama_url(value)

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            origin = value.strip().rstrip("/")
            parsed = urlparse(origin)
            if origin == "*":
                raise ValueError("Wildcard CORS origins are forbidden")
            try:
                _ = parsed.port
            except ValueError as exc:
                raise ValueError("CORS origin contains an invalid port") from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.hostname is None
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("CORS origins must not contain credentials")
            if parsed.path or parsed.params or parsed.query or parsed.fragment:
                raise ValueError(
                    "CORS origins must not contain a path, parameters, "
                    "query, or fragment"
                )
            normalized.append(origin)
        if len(normalized) != len(set(normalized)):
            raise ValueError("ALLOWED_ORIGINS must not contain duplicates")
        return normalized

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            network = ip_network(value.strip(), strict=False)
            normalized.append(str(network))
        if len(normalized) != len(set(normalized)):
            raise ValueError("TRUSTED_PROXY_CIDRS must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_selected_configuration(self) -> "Settings":
        """Enforce dependencies among provider, storage and authentication choices.

        PostgreSQL selections require a runtime DSN and ordered pool bounds;
        Redis selection validates its URL and bounded vector capacity. Dataset
        retention must be ordered, and durable run history requires explicit
        retention, namespace capacity and cleanup limits. Token mode requires
        principals with unique names/digests and admin-only wildcard scope.

        Returns:
            The validated settings instance, without connecting to dependencies.

        Raises:
            ValueError: Selected settings violate a cross-field invariant or a
                required provider/storage/authentication setting is missing.
        """
        validate_provider_configuration(self)

        if (
            self.cache_backend == "memory"
            and self.max_cache_size > MAX_MEMORY_CACHE_SIZE
        ):
            raise ValueError(
                f"MAX_CACHE_SIZE cannot exceed {MAX_MEMORY_CACHE_SIZE} when "
                "CACHE_BACKEND=memory; use CACHE_BACKEND=pgvector for larger "
                "persistent caches"
            )

        if self.cache_backend == "redis":
            self._validate_redis_configuration()

        if self.database_required:
            self._require_secret(self.database_url, "DATABASE_URL")
            self._validate_database_url()
            if self.database_pool_min_size > self.database_pool_max_size:
                raise ValueError(
                    "DATABASE_POOL_MIN_SIZE cannot exceed DATABASE_POOL_MAX_SIZE"
                )
        if (
            self.evaluation_dataset_default_retention_days
            > self.evaluation_dataset_max_retention_days
        ):
            raise ValueError(
                "EVALUATION_DATASET_DEFAULT_RETENTION_DAYS cannot exceed "
                "EVALUATION_DATASET_MAX_RETENTION_DAYS"
            )

        if self.evaluation_run_history_storage == "postgres":
            required_history_settings = {
                "EVALUATION_RUN_HISTORY_RETENTION_DAYS": (
                    self.evaluation_run_history_retention_days
                ),
                "EVALUATION_RUN_HISTORY_MAX_PER_NAMESPACE": (
                    self.evaluation_run_history_max_per_namespace
                ),
                "EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE": (
                    self.evaluation_run_history_cleanup_batch_size
                ),
            }
            missing = [
                name
                for name, value in required_history_settings.items()
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} must be configured when "
                    "EVALUATION_RUN_HISTORY_STORAGE=postgres"
                )

        if self.auth_mode == "token":
            if not self.auth_principals:
                raise ValueError("AUTH_PRINCIPALS is required when AUTH_MODE=token")
            names = [principal.name for principal in self.auth_principals]
            hashes = [principal.token_sha256 for principal in self.auth_principals]
            if len(names) != len(set(names)):
                raise ValueError("AUTH_PRINCIPALS names must be unique")
            if len(hashes) != len(set(hashes)):
                raise ValueError("AUTH_PRINCIPALS token hashes must be unique")
            if any(
                "*" in principal.namespaces and principal.role != "admin"
                for principal in self.auth_principals
            ):
                raise ValueError("Wildcard namespace access requires the admin role")

        return self

    @property
    def embedding_dimensions(self) -> int:
        return selected_embedding_dimensions(self)

    @property
    def embedding_space(self) -> str:
        """Return a built-in provider's model-based cache identity.

        Custom provider identities come from registry metadata, not this helper.

        Raises:
            RuntimeError: The provider is custom or its model was not validated.
        """
        return selected_embedding_space(self)

    @property
    def database_dsn(self) -> str:
        """Reveal the validated runtime DSN only for connection creation.

        Raises:
            RuntimeError: No database URL was supplied; callers must first require
                a PostgreSQL feature. The returned value is secret, not log data.
        """
        if self.database_url is None:
            raise RuntimeError("DATABASE_URL was not validated")
        return self.database_url.get_secret_value()

    @property
    def database_required(self) -> bool:
        """Report whether cache, dataset, history or coordination needs PostgreSQL."""
        return (
            self.cache_backend == "pgvector"
            or self.evaluation_dataset_storage == "postgres"
            or self.evaluation_run_history_storage == "postgres"
            or self.coordination_backend == "postgres"
        )

    def configured_secrets(self) -> tuple[str, ...]:
        """Collect configured credentials and URL forms for logging redaction.

        Returns:
            Secret provider keys, database/Redis URLs and extracted password forms.
            Registry secrets are added separately by the factory. This is not an
            allowlist for serializing settings or discovering caller bearer tokens.
        """
        secrets = (
            self.hf_api_key,
            self.openai_api_key,
            self.anthropic_api_key,
            self.gemini_api_key,
            self.database_url,
            self.redis_url,
        )
        configured = [
            secret.get_secret_value()
            for secret in secrets
            if secret is not None and secret.get_secret_value()
        ]
        if self.database_url is not None:
            parsed = urlparse(self.database_url.get_secret_value())
            if parsed.password:
                configured.append(parsed.password)
        if self.redis_url is not None:
            parsed = urlparse(self.redis_url.get_secret_value())
            if parsed.password:
                configured.extend((parsed.password, unquote(parsed.password)))
        return tuple(configured)

    def _validate_redis_configuration(self) -> None:
        self._require_secret(self.redis_url, "REDIS_URL")
        if self.redis_url is None:
            raise ValueError("REDIS_URL is required")
        try:
            parsed = urlparse(self.redis_url.get_secret_value())
            port = parsed.port
        except ValueError:
            raise ValueError("REDIS_URL is invalid") from None
        if (
            parsed.scheme not in {"redis", "rediss"}
            or not parsed.hostname
            or parsed.fragment
            or parsed.query
            or port == 0
        ):
            raise ValueError(
                "REDIS_URL must identify a direct standalone Redis primary"
            )
        if (
            self.max_cache_size > 5000
            or self.max_cache_size * self.embedding_dimensions * 8 > 64 * 1024 * 1024
        ):
            raise ValueError(
                "Redis capacity must be <=5000 and vector projection <=64 MiB"
            )

    def _validate_database_url(self) -> None:
        if self.database_url is None:
            return
        parsed = urlparse(self.database_url.get_secret_value())
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("DATABASE_URL contains an invalid port") from exc
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or not parsed.hostname
            or not parsed.path.strip("/")
            or parsed.fragment
        ):
            raise ValueError(
                "DATABASE_URL must be an absolute PostgreSQL URL with a database name"
            )

    @staticmethod
    def _require_secret(
        value: SecretStr | None,
        environment_name: str,
    ) -> None:
        if value is None or not value.get_secret_value().strip():
            raise ValueError(
                f"{environment_name} is required for the selected provider"
            )


@lru_cache
def get_settings() -> Settings:
    """Load and cache validated environment settings for default construction.

    Environment changes are not re-read on each request; callers can inject
    an explicit Settings instance into create_app instead.
    """
    # Required fields are supplied by BaseSettings environment sources.
    return Settings()  # pyright: ignore[reportCallIssue]
