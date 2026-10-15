"""Development-only setup policy leaves ordinary runtime behavior untouched."""

from __future__ import annotations

import asyncio
import os

import pytest

from app.core.config import Settings
from app.infrastructure import migrate
from scripts import dev_storage


def test_memory_plan_needs_no_database_credentials() -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
    )
    assert dev_storage.plan(settings) == {"postgres": False, "redis": False}


@pytest.mark.parametrize(
    "feature",
    [
        "cache_backend",
        "evaluation_dataset_storage",
        "evaluation_run_history_storage",
        "coordination_backend",
    ],
)
def test_independent_postgres_selections_are_detected(feature: str) -> None:
    values = {
        feature: "pgvector" if feature == "cache_backend" else "postgres",
        "database_url": "postgresql://runtime:fixture-value@postgres:5432/semantix",
        "evaluation_run_history_retention_days": 3,
        "evaluation_run_history_max_per_namespace": 10,
        "evaluation_run_history_cleanup_batch_size": 5,
    }
    settings = Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "allowed_origins": ["http://localhost:4173"],
            "database_migration_mode": "external",
            **values,
        }
    )
    assert dev_storage.plan(settings)["postgres"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://semantix:fixture-value@postgres/semantix",
        "postgresql://runtime:replace-password@postgres/semantix",
        "postgresql://runtime:fixture-value@postgres.example.invalid/semantix",
        "postgresql://runtime:fixture-value@postgres/other",
        "postgresql://runtime:fixture-value@postgres:9999/semantix",
        "postgresql://runtime:fixture-value@postgres/semantix?sslmode=disable",
    ],
)
def test_unsafe_managed_postgres_configuration_is_refused(url: str) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        database_migration_mode="external",
        cache_backend="pgvector",
        database_url=url,
    )
    with pytest.raises(ValueError, match=r"runtime|Local|PostgreSQL|Configure"):
        dev_storage.plan(settings)


def test_external_tls_url_is_preserved_and_not_provisioned() -> None:
    url = "postgresql://runtime:fixture-value@external.example/semantix?sslmode=verify-full"
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        database_migration_mode="external",
        cache_backend="pgvector",
        database_url=url,
    )
    assert not dev_storage.plan(settings)["postgres"]
    assert settings.database_dsn == url


@pytest.mark.parametrize(
    "url",
    [
        "redis://redis:6379/1",
        "rediss://redis:6379/0",
        "redis://runtime:fixture-value@redis:6379/0",
    ],
)
def test_local_redis_policy_cannot_be_weakened_or_guessed(url: str) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        cache_backend="redis",
        redis_url=url,
    )
    with pytest.raises(ValueError, match="Local Redis"):
        dev_storage.plan(settings)


def test_redis_and_independent_postgres_are_both_selected() -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        cache_backend="redis",
        redis_url="redis://redis:6379/0",
        coordination_backend="postgres",
        database_url="postgresql://runtime:fixture-value@postgres/semantix",
        database_migration_mode="external",
    )
    assert dev_storage.plan(settings) == {"postgres": True, "redis": True}


def test_operator_environment_must_not_enter_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "private-fixture-value")
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
    )
    with pytest.raises(ValueError, match="separately") as caught:
        dev_storage.plan(settings)
    assert "private-fixture-value" not in str(caught.value)


async def test_external_database_cannot_be_marked_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        database_migration_mode="external",
        cache_backend="pgvector",
        database_url="postgresql://runtime:fixture-value@external.example/semantix",
    )
    with pytest.raises(ValueError, match="recognized local"):
        await dev_storage.setup(settings, fresh={"postgres": True, "redis": False})


async def test_existing_postgres_does_not_call_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        database_migration_mode="external",
        cache_backend="pgvector",
        database_url="postgresql://runtime:fixture-value@postgres/semantix",
    )
    calls: list[str] = []

    async def validate(active: Settings) -> None:
        calls.append("validate")

    async def forbidden() -> None:
        pytest.fail("existing database must never migrate")

    monkeypatch.setattr(dev_storage, "validate_postgres", validate)
    monkeypatch.setattr(migrate, "run", forbidden)
    await dev_storage.setup(settings, fresh={"postgres": False, "redis": False})
    assert calls == ["validate"]
    assert "MIGRATION_DATABASE_URL" not in os.environ


@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_fresh_setup_failure_removes_operator_environment_and_propagates(
    monkeypatch: pytest.MonkeyPatch, failure_type: type[BaseException]
) -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        allowed_origins=["http://localhost:4173"],
        database_migration_mode="external",
        cache_backend="pgvector",
        database_url="postgresql://runtime:fixture-value@postgres/semantix",
    )

    async def fail() -> None:
        assert os.environ["DATABASE_RUNTIME_ROLE"] == "runtime"
        assert os.environ["MIGRATION_DATABASE_URL"] != settings.database_dsn
        raise failure_type("injected startup failure")

    monkeypatch.setattr(migrate, "run", fail)
    with pytest.raises(failure_type, match="injected"):
        await dev_storage.setup(
            settings,
            fresh={"postgres": True, "redis": False},
            migration_url="postgresql://fixture_bootstrap:fixture-operator@postgres:5432/semantix",
        )
    assert "MIGRATION_DATABASE_URL" not in os.environ
    assert "DATABASE_RUNTIME_ROLE" not in os.environ
