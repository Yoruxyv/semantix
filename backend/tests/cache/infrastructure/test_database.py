from typing import cast

import asyncpg
import pytest
from asyncpg.pool import Pool
from pydantic import ValidationError

from app.cache.infrastructure.database import create_pool, load_migrations
from app.core.config import Settings
from app.core.limits import MAX_MEMORY_CACHE_SIZE

ORIGINS = ["http://localhost:5173"]


def test_memory_backend_does_not_require_database_configuration() -> None:
    settings = Settings(
        cache_backend="memory",
        database_url=None,
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert settings.cache_backend == "memory"
    assert settings.database_url is None
    assert settings.evaluation_dataset_storage == "session"
    assert settings.evaluation_run_history_storage == "disabled"
    assert settings.database_required is False


def test_memory_cache_capacity_is_bounded_for_process_liveness() -> None:
    configured = Settings(
        cache_backend="memory",
        max_cache_size=MAX_MEMORY_CACHE_SIZE,
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert configured.max_cache_size == MAX_MEMORY_CACHE_SIZE

    for unsafe_size in (MAX_MEMORY_CACHE_SIZE + 1, 50_000, 100_000):
        with pytest.raises(
            ValidationError,
            match="MAX_CACHE_SIZE.*CACHE_BACKEND=memory.*pgvector",
        ):
            Settings(
                cache_backend="memory",
                max_cache_size=unsafe_size,
                hf_api_key="test-only-placeholder",
                allowed_origins=ORIGINS,
            )


def test_pgvector_retains_the_existing_cache_capacity_limit() -> None:
    configured = Settings(
        cache_backend="pgvector",
        max_cache_size=100_000,
        database_url="postgresql://user:secret@database:5432/semantix",
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert configured.max_cache_size == 100_000


def test_pgvector_requires_a_postgresql_database_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            cache_backend="pgvector",
            database_url=None,
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )

    with pytest.raises(ValidationError, match="absolute PostgreSQL URL"):
        Settings(
            cache_backend="pgvector",
            database_url="https://database.example.test/semantix",
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )


def test_postgres_evaluation_storage_requires_database_with_memory_cache() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            cache_backend="memory",
            evaluation_dataset_storage="postgres",
            database_url=None,
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )

    configured = Settings(
        cache_backend="memory",
        evaluation_dataset_storage="postgres",
        database_url="postgresql://user:secret@database:5432/semantix",
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert configured.database_required is True
    assert configured.database_dsn.endswith("/semantix")


def test_postgres_run_history_requires_database_and_explicit_bounds() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            cache_backend="memory",
            evaluation_run_history_storage="postgres",
            evaluation_run_history_retention_days=30,
            evaluation_run_history_max_per_namespace=100,
            evaluation_run_history_cleanup_batch_size=10,
            database_url=None,
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )

    with pytest.raises(
        ValidationError,
        match="EVALUATION_RUN_HISTORY_RETENTION_DAYS",
    ):
        Settings(
            cache_backend="memory",
            evaluation_run_history_storage="postgres",
            database_url="postgresql://user:secret@database:5432/semantix",
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )

    configured = Settings(
        cache_backend="memory",
        evaluation_run_history_storage="postgres",
        evaluation_run_history_retention_days=30,
        evaluation_run_history_max_per_namespace=100,
        evaluation_run_history_cleanup_batch_size=10,
        database_url="postgresql://user:secret@database:5432/semantix",
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert configured.database_required is True
    assert configured.evaluation_run_history_retention_days == 30
    assert configured.evaluation_run_history_max_per_namespace == 100
    assert configured.evaluation_run_history_cleanup_batch_size == 10


@pytest.mark.parametrize(
    ("cache_backend", "dataset_storage", "history_storage", "database_required"),
    [
        ("memory", "session", "disabled", False),
        ("memory", "postgres", "disabled", True),
        ("memory", "session", "postgres", True),
        ("pgvector", "session", "disabled", True),
        ("pgvector", "postgres", "disabled", True),
        ("pgvector", "session", "postgres", True),
    ],
)
def test_database_requirement_matrix(
    cache_backend: str,
    dataset_storage: str,
    history_storage: str,
    database_required: bool,
) -> None:
    database_url = (
        "postgresql://user:secret@database:5432/semantix" if database_required else None
    )
    configured = Settings.model_validate(
        {
            "cache_backend": cache_backend,
            "evaluation_dataset_storage": dataset_storage,
            "evaluation_run_history_storage": history_storage,
            "evaluation_run_history_retention_days": (
                30 if history_storage == "postgres" else None
            ),
            "evaluation_run_history_max_per_namespace": (
                100 if history_storage == "postgres" else None
            ),
            "evaluation_run_history_cleanup_batch_size": (
                10 if history_storage == "postgres" else None
            ),
            "database_url": database_url,
            "hf_api_key": "test-only-placeholder",
            "allowed_origins": ORIGINS,
        }
    )

    assert configured.database_required is database_required


def test_persisted_dataset_retention_bounds_are_consistent() -> None:
    configured = Settings(
        cache_backend="memory",
        evaluation_dataset_default_retention_days=30,
        evaluation_dataset_max_retention_days=365,
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert configured.evaluation_dataset_default_retention_days == 30
    assert configured.evaluation_dataset_max_retention_days == 365

    with pytest.raises(
        ValidationError,
        match="EVALUATION_DATASET_DEFAULT_RETENTION_DAYS",
    ):
        Settings(
            cache_backend="memory",
            evaluation_dataset_default_retention_days=366,
            evaluation_dataset_max_retention_days=365,
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )


def test_pgvector_pool_bounds_are_validated() -> None:
    with pytest.raises(
        ValidationError,
        match="DATABASE_POOL_MIN_SIZE cannot exceed",
    ):
        Settings(
            cache_backend="pgvector",
            database_url="postgresql://user:secret@database:5432/semantix",
            database_pool_min_size=6,
            database_pool_max_size=5,
            hf_api_key="test-only-placeholder",
            allowed_origins=ORIGINS,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "database_connect_timeout_seconds",
        "database_command_timeout_seconds",
    ],
)
def test_database_timeouts_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValidationError, match=field_name):
        Settings.model_validate(
            {
                "cache_backend": "pgvector",
                "database_url": ("postgresql://user:secret@database:5432/semantix"),
                "hf_api_key": "test-only-placeholder",
                "allowed_origins": ORIGINS,
                field_name: 0,
            }
        )


@pytest.mark.asyncio
async def test_database_pool_uses_independent_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: dict[str, object] = {}
    expected_pool = cast(Pool, object())

    async def fake_create_pool(
        *,
        dsn: str,
        min_size: int,
        max_size: int,
        timeout: float,
        command_timeout: float,
    ) -> Pool:
        configured.update(
            {
                "dsn": dsn,
                "min_size": min_size,
                "max_size": max_size,
                "timeout": timeout,
                "command_timeout": command_timeout,
            }
        )
        return expected_pool

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)

    result = await create_pool(
        "postgresql://user:secret@database:5432/semantix",
        min_size=2,
        max_size=7,
        connect_timeout=3.5,
        command_timeout=45.0,
    )

    assert result is expected_pool
    assert configured == {
        "dsn": "postgresql://user:secret@database:5432/semantix",
        "min_size": 2,
        "max_size": 7,
        "timeout": 3.5,
        "command_timeout": 45.0,
    }


def test_database_credentials_are_registered_for_log_redaction() -> None:
    settings = Settings(
        cache_backend="pgvector",
        database_url="postgresql://user:secret@database:5432/semantix",
        hf_api_key="test-only-placeholder",
        allowed_origins=ORIGINS,
    )

    assert "secret" in settings.configured_secrets()
    assert settings.database_dsn.endswith("/semantix")


def test_cache_migrations_have_unique_ordered_versions() -> None:
    migrations = load_migrations()

    assert [migration.version for migration in migrations] == ["0001"]
    assert "semantix.cache_entries" in migrations[0].sql
    assert len(migrations[0].checksum) == 64
    assert migrations[0].checksum == migrations[0].checksum.lower()
