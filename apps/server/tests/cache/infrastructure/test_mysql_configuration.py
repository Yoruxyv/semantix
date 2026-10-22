"""Offline settings, explicit setup and public composition contracts."""

import asyncio
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest
from asyncpg.pool import Pool
from pydantic import SecretStr, ValidationError

from app.cache.infrastructure import factory, mysql_setup
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.providers.registry import EmbeddingMetadata
from scripts.dev_storage import plan
from semantix_cache import (
    CacheClosedError,
    CacheStoreError,
    EmbeddingSpace,
    MemoryStore,
)
from semantix_cache.stores.mysql import MySQLStore


def configuration(tmp_path: Path, **changes: object) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "mock_embedding_dimensions": 4,
            "cache_backend": "mysql",
            "cache_mysql_address": "127.0.0.1",
            "cache_mysql_tls_hostname": "localhost",
            "cache_mysql_ca_file": str(tmp_path / "private-ca.pem"),
            "cache_mysql_database": "private_cache",
            "cache_mysql_user": "runtime_user",
            "cache_mysql_password": "runtime-secret-marker",
            "max_cache_size": 4,
            "allowed_origins": ["http://localhost"],
            **changes,
        }
    )


@pytest.mark.parametrize(
    "field", ["address", "tls_hostname", "ca_file", "database", "user", "password"]
)
@pytest.mark.parametrize("value", [None, "", " "])
def test_required_private_mysql_fields(
    tmp_path: Path, field: str, value: str | None
) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path, **{"cache_mysql_" + field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("address", "localhost"),
        ("address", "::1"),
        ("address", "127.000.0.1"),
        ("port", 0),
        ("port", 65536),
        ("port", True),
        ("port", 3306.0),
        ("tls_hostname", "name\0.invalid"),
        ("tls_hostname", "é.invalid"),
        ("database", "mysql"),
        ("database", "sys"),
        ("database", "Other-db"),
        ("database", "x" * 65),
        ("ca_file", "relative.pem"),
        ("user", "bad\0user"),
        ("password", "bad\0password"),
    ],
)
def test_mysql_boundaries(tmp_path: Path, field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path, **{"cache_mysql_" + field: value})


@pytest.mark.parametrize("field", ["connect", "operation", "close"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), 86401, True])
def test_mysql_budgets(tmp_path: Path, field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path, **{f"cache_mysql_{field}_timeout_seconds": value})


def test_settings_privacy_capacity_and_postgres_independence(tmp_path: Path) -> None:
    settings = configuration(tmp_path, cache_mysql_port="3306")
    assert not settings.database_required
    exposed = repr(settings) + settings.model_dump_json()
    for value in (
        "runtime-secret-marker",
        "runtime_user",
        "private_cache",
        "private-ca.pem",
    ):
        assert value not in exposed
    assert "runtime-secret-marker" in settings.configured_secrets()
    assert str(tmp_path / "private-ca.pem") in settings.configured_secrets()
    with pytest.raises(ValidationError, match="capacity"):
        configuration(tmp_path, max_cache_size=5001)
    for feature in (
        "coordination_backend",
        "evaluation_dataset_storage",
        "evaluation_run_history_storage",
    ):
        options: dict[str, object] = {
            feature: "postgres",
            "database_url": "postgresql://user@localhost/app",
            "evaluation_run_history_retention_days": 1,
            "evaluation_run_history_max_per_namespace": 10,
            "evaluation_run_history_cleanup_batch_size": 1,
        }
        assert configuration(tmp_path, **options).database_required


async def test_setup_uses_separate_credentials_and_resolved_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, object]] = []

    async def initialize(**kwargs: object) -> None:
        seen.append(kwargs)

    monkeypatch.setattr(MySQLStore, "initialize_schema", initialize)
    settings = configuration(tmp_path)
    setup_value = SecretStr("setup-secret")
    await mysql_setup.initialize_mysql(
        settings,
        metadata=EmbeddingMetadata(4, "custom:resolved"),
        setup_user=SecretStr("setup-user"),
        setup_password=setup_value,
    )
    assert seen[0]["embedding_space"] == EmbeddingSpace(
        identity="custom:resolved", dimensions=4
    )
    assert seen[0]["user"] == "setup-user"
    assert seen[0]["password"] == setup_value.get_secret_value()
    assert "runtime-secret-marker" not in seen[0].values()
    for field in ("CACHE_MYSQL_SETUP_USER", "CACHE_MYSQL_SETUP_PASSWORD"):
        monkeypatch.delenv(field, raising=False)
    monkeypatch.setattr(mysql_setup, "Settings", lambda: settings)
    with pytest.raises(CacheStorageError, match="SETUP_USER"):
        await mysql_setup.run()
    assert len(seen) == 1
    monkeypatch.setenv("CACHE_MYSQL_SETUP_USER", "explicit-user")
    explicit_value = SecretStr("explicit-password")
    monkeypatch.setenv("CACHE_MYSQL_SETUP_PASSWORD", explicit_value.get_secret_value())
    await mysql_setup.run()
    assert seen[-1]["password"] == explicit_value.get_secret_value()
    with pytest.raises(CacheStorageError, match="requires CACHE_BACKEND"):
        await mysql_setup.initialize_mysql(
            configuration(tmp_path, cache_backend="memory"),
            metadata=EmbeddingMetadata(4, "space"),
            setup_user=SecretStr("u"),
            setup_password=SecretStr("p"),
        )


async def test_setup_error_is_sanitized_and_cancellation_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def initialize(**kwargs: object) -> None:
        raise CacheStoreError("private-driver-marker")

    monkeypatch.setattr(MySQLStore, "initialize_schema", initialize)
    with pytest.raises(CacheStorageError) as caught:
        await mysql_setup.initialize_mysql(
            configuration(tmp_path),
            metadata=EmbeddingMetadata(4, "space"),
            setup_user=SecretStr("u"),
            setup_password=SecretStr("p"),
        )
    assert "private-driver-marker" not in str(caught.value)

    async def cancelled(**kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(MySQLStore, "initialize_schema", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mysql_setup.initialize_mysql(
            configuration(tmp_path),
            metadata=EmbeddingMetadata(4, "space"),
            setup_user=SecretStr("u"),
            setup_password=SecretStr("p"),
        )


async def test_connect_only_composition_and_failed_adapter_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stores: list[MemoryStore] = []
    seen: list[dict[str, object]] = []

    async def connect(**kwargs: object) -> MemoryStore:
        seen.append(kwargs)
        store = MemoryStore(
            embedding_space=EmbeddingSpace(identity="resolved", dimensions=4),
            max_size=4,
        )
        stores.append(store)
        return store

    async def no_setup(**kwargs: object) -> None:
        raise AssertionError("Runtime invoked setup")

    monkeypatch.setattr(MySQLStore, "connect", connect)
    monkeypatch.setattr(MySQLStore, "initialize_schema", no_setup)
    settings = configuration(tmp_path)
    async with factory.cache_backend_lifespan(
        settings, dimensions=4, embedding_space="resolved", pool=cast(Pool, object())
    ) as backend:
        assert isinstance(backend, OfficialStoreBackend)
        assert backend._counter_pool is None
        await backend.record_miss("alpha")
        assert (await backend.stats("alpha")).misses == 1
    assert seen[0]["user"] == "runtime_user"
    assert seen[0]["close_timeout_seconds"] == pytest.approx(30.0)
    with pytest.raises(CacheClosedError):
        await stores[0].inspect_entries()

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("adapter construction failed")

    monkeypatch.setattr(factory, "OfficialStoreBackend", broken)
    with pytest.raises(RuntimeError, match="adapter construction failed"):
        async with factory.cache_backend_lifespan(
            settings, dimensions=4, embedding_space="resolved"
        ):
            pytest.fail("Broken adapter yielded")
    with pytest.raises(CacheClosedError):
        await stores[-1].inspect_entries()


async def test_missing_driver_is_selected_backend_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = import_module

    def unavailable(name: str) -> object:
        if name == "semantix_cache.stores.mysql":
            raise ImportError("controlled missing optional driver")
        return original(name)

    monkeypatch.setattr(factory, "import_module", unavailable)
    with pytest.raises(CacheStorageError, match="server mysql extra"):
        async with factory.cache_backend_lifespan(
            configuration(tmp_path), dimensions=4, embedding_space="resolved"
        ):
            pytest.fail("Missing driver yielded")


def test_development_launcher_does_not_claim_unverified_mysql_setup(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="MySQL requires explicit operator setup"):
        plan(configuration(tmp_path))
