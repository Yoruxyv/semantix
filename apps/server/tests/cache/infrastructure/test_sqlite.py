"""Public SQLite composition, setup and terminal shutdown policy."""

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import cast

import pytest
from asyncpg.pool import Pool
from pydantic import ValidationError

from app import lifecycle
from app.cache.infrastructure import factory, sqlite_setup
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.factory import create_app
from app.providers.factory import create_default_provider_registry
from app.providers.registry import EmbeddingMetadata
from scripts.dev_storage import plan
from semantix_cache import CacheBusyError, CacheStoreError, EmbeddingSpace
from semantix_cache.stores._backends.sqlite.worker import Worker
from semantix_cache.stores.sqlite import SQLiteStore


def configuration(tmp_path: Path, **values: object) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "mock_embedding_dimensions": 4,
            "cache_backend": "sqlite",
            "cache_sqlite_path": str(tmp_path / "private.db"),
            "max_cache_size": 10,
            "allowed_origins": ["http://localhost"],
            "rate_limit": "10000/minute",
            **values,
        }
    )


def metadata(settings: Settings) -> EmbeddingMetadata:
    return (
        create_default_provider_registry(settings)
        .resolve(settings.embedding_provider, settings.generation_provider)
        .embedding_metadata
    )


@pytest.mark.parametrize("path", [None, "relative.db", ":memory:", "file:cache.db"])
def test_sqlite_requires_absolute_private_configuration(
    tmp_path: Path, path: str | None
) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path, cache_sqlite_path=path)


@pytest.mark.parametrize(
    "field",
    [
        "cache_sqlite_connect_timeout_seconds",
        "cache_sqlite_operation_timeout_seconds",
        "cache_sqlite_close_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1, 86401, float("nan"), float("inf")])
def test_finite_sqlite_deadlines(tmp_path: Path, field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path, **{field: value})


def test_sqlite_configuration_is_private_and_independent(tmp_path: Path) -> None:
    settings = configuration(tmp_path)
    assert not settings.database_required
    assert str(tmp_path) not in repr(settings)
    assert str(tmp_path / "private.db") in settings.configured_secrets()
    with pytest.raises(ValidationError, match="capacity"):
        configuration(tmp_path, max_cache_size=5001)
    with pytest.raises(ValueError, match="Compose is unsupported"):
        plan(settings)


@pytest.mark.parametrize(
    "feature",
    [
        "evaluation_dataset_storage",
        "evaluation_run_history_storage",
        "coordination_backend",
    ],
)
def test_sqlite_keeps_independent_postgres_requirements(
    tmp_path: Path, feature: str
) -> None:
    values: dict[str, object] = {
        feature: "postgres",
        "database_url": "postgresql://user@localhost/test",
        "evaluation_run_history_retention_days": 1,
        "evaluation_run_history_max_per_namespace": 1,
        "evaluation_run_history_cleanup_batch_size": 1,
    }
    assert configuration(tmp_path, **values).database_required
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        configuration(tmp_path, **{**values, "database_url": None})


async def test_explicit_setup_then_connect_only_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    app = create_app(settings)
    with pytest.raises(CacheStorageError):
        async with app.router.lifespan_context(app):
            pytest.fail("Uninitialized startup must fail")
    assert not (tmp_path / "private.db").exists()
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))

    async def no_automatic_setup(*args: object, **kwargs: object) -> None:
        raise AssertionError("Normal startup attempted initialization")

    monkeypatch.setattr(SQLiteStore, "initialize_schema", no_automatic_setup)
    for _ in range(2):
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            backend = app.state.semantic_cache._backend
            assert isinstance(backend.store, SQLiteStore)
            assert backend._counter_pool is None
            assert (await backend.stats(None)).size == 0
        assert backend.store._worker.connection is None
        assert all(not t.is_alive() for t in backend.store._worker.pool._threads)


@pytest.mark.parametrize("dimensions", [16001, 4096])
async def test_resolved_custom_metadata_limits_precede_file_creation(
    tmp_path: Path, dimensions: int
) -> None:
    settings = configuration(
        tmp_path, embedding_provider="custom-test", max_cache_size=5000
    )
    custom = EmbeddingMetadata(dimensions=dimensions, space="custom-binding")
    with pytest.raises(CacheStorageError):
        await sqlite_setup.initialize_sqlite(settings, metadata=custom)
    assert not (tmp_path / "private.db").exists()
    with pytest.raises(CacheStorageError):
        async with factory.cache_backend_lifespan(
            settings, dimensions=dimensions, embedding_space=custom.space
        ):
            pytest.fail("Incompatible resolved metadata must fail")
    assert not (tmp_path / "private.db").exists()


async def test_setup_rejects_foreign_missing_parent_and_policy_mismatch(
    tmp_path: Path,
) -> None:
    settings = configuration(tmp_path)
    path = tmp_path / "private.db"
    path.write_bytes(b"unmarked application data")
    before = path.read_bytes()
    with pytest.raises(CacheStorageError) as caught:
        await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    assert str(path) not in str(caught.value)
    assert path.read_bytes() == before
    missing = configuration(
        tmp_path, cache_sqlite_path=str(tmp_path / "missing" / "file.db")
    )
    with pytest.raises(CacheStorageError):
        await sqlite_setup.initialize_sqlite(missing, metadata=metadata(missing))
    assert not (tmp_path / "missing").exists()
    other = configuration(tmp_path, cache_sqlite_path=str(tmp_path / "marked.db"))
    await sqlite_setup.initialize_sqlite(other, metadata=metadata(other))
    mismatch = configuration(
        tmp_path, cache_sqlite_path=str(tmp_path / "marked.db"), max_cache_size=11
    )
    with pytest.raises(CacheStorageError):
        async with factory.cache_backend_lifespan(
            mismatch, dimensions=4, embedding_space=metadata(other).space
        ):
            pytest.fail("Binding policy mismatch must fail")


async def test_setup_command_uses_metadata_without_provider_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    monkeypatch.setattr(sqlite_setup, "Settings", lambda: settings)
    await sqlite_setup.run()
    assert (tmp_path / "private.db").is_file()
    with pytest.raises(CacheStorageError, match="requires CACHE_BACKEND=sqlite"):
        await sqlite_setup.initialize_sqlite(
            configuration(tmp_path, cache_backend="memory"), metadata=metadata(settings)
        )


async def test_later_startup_failure_closes_assigned_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    closed: list[SQLiteStore] = []
    close = SQLiteStore.aclose

    async def observed_close(store: SQLiteStore) -> None:
        await close(store)
        closed.append(store)

    def failed_service(*args: object, **kwargs: object) -> None:
        raise RuntimeError("controlled startup failure")

    monkeypatch.setattr(SQLiteStore, "aclose", observed_close)
    monkeypatch.setattr(lifecycle, "QueryService", failed_service)
    app = create_app(settings)
    with pytest.raises(RuntimeError, match="controlled startup failure"):
        async with app.router.lifespan_context(app):
            pytest.fail("Injected startup failure must propagate")
    assert len(closed) == 1
    assert closed[0]._worker.connection is None
    assert all(not t.is_alive() for t in closed[0]._worker.pool._threads)


@pytest.mark.parametrize("outcome", ["expiry", "cancel"])
async def test_total_close_budget_keeps_package_owned_native_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    settings = configuration(tmp_path)
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    store = await SQLiteStore.connect(
        tmp_path / "private.db",
        embedding_space=EmbeddingSpace(identity=metadata(settings).space, dimensions=4),
        max_size=10,
        close_timeout_seconds=0.1,
    )
    original_close = SQLiteStore.aclose
    original_physical_close = Worker._close_connection
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    attempts: list[int] = []
    physical: list[int] = []

    async def first_busy(active: SQLiteStore) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise CacheBusyError("controlled pre-close busy")
        await original_close(active)

    def held_close(worker: Worker) -> None:
        physical.append(1)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Physical-close barrier was not released")
        original_physical_close(worker)

    monkeypatch.setattr(SQLiteStore, "aclose", first_busy)
    monkeypatch.setattr(Worker, "_close_connection", held_close)
    closing = asyncio.create_task(factory._close_sqlite(store, 0.1))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if outcome == "cancel":
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
        else:
            with pytest.raises(CacheStorageError, match="shutdown budget expired"):
                await closing
        assert attempts == [1, 1]
        assert physical == [1]
        assert store._worker.cleanup is not None
        assert not store._worker.cleanup.done()
        assert store._worker.connection is not None
        assert not store._worker.pool._shutdown
    finally:
        release.set()
        await asyncio.gather(closing, return_exceptions=True)
        await original_close(store)
    assert store._worker.connection is None
    assert all(not t.is_alive() for t in store._worker.pool._threads)


async def test_native_close_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    real_close = SQLiteStore.aclose
    closed: list[SQLiteStore] = []

    async def failed_after_disposal(store: SQLiteStore) -> None:
        await real_close(store)
        closed.append(store)
        raise CacheStoreError("controlled post-disposal failure")

    monkeypatch.setattr(SQLiteStore, "aclose", failed_after_disposal)
    with pytest.raises(CacheStorageError, match="Official cache cleanup failed"):
        async with factory.cache_backend_lifespan(
            settings, dimensions=4, embedding_space=metadata(settings).space
        ):
            pass
    assert len(closed) == 1
    assert closed[0]._worker.connection is None


async def test_adapter_construction_failure_closes_connected_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    closed: list[SQLiteStore] = []
    original = SQLiteStore.aclose

    async def observed_close(store: SQLiteStore) -> None:
        await original(store)
        closed.append(store)

    def broken_adapter(*args: object, **kwargs: object) -> None:
        raise RuntimeError("controlled adapter construction failure")

    monkeypatch.setattr(SQLiteStore, "aclose", observed_close)
    monkeypatch.setattr(factory, "OfficialStoreBackend", broken_adapter)
    with pytest.raises(RuntimeError, match="controlled adapter construction failure"):
        async with factory.cache_backend_lifespan(
            settings, dimensions=4, embedding_space=metadata(settings).space
        ):
            pytest.fail("Adapter construction must fail")
    assert len(closed) == 1
    assert closed[0]._worker.connection is None
    assert all(not thread.is_alive() for thread in closed[0]._worker.pool._threads)


async def test_runtime_rejection_preserves_file_and_sanitizes_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    path = tmp_path / "private.db"
    before = path.read_bytes()
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 51, 2))
    with pytest.raises(CacheStorageError):
        await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    with pytest.raises(CacheStorageError):
        async with factory.cache_backend_lifespan(
            settings, dimensions=4, embedding_space=metadata(settings).space
        ):
            pytest.fail("Unsupported linked runtime must fail")
    assert path.read_bytes() == before


async def test_optional_import_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)

    def unavailable(name: str) -> None:
        raise ImportError("controlled missing runtime")

    monkeypatch.setattr(factory, "import_module", unavailable)
    with pytest.raises(CacheStorageError, match="supported sqlite3 runtime"):
        async with factory.cache_backend_lifespan(
            settings, dimensions=4, embedding_space="mock"
        ):
            pytest.fail("Missing SQLite module must fail")


async def test_setup_cancellation_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configuration(tmp_path)

    async def cancelled(*args: object, **kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(SQLiteStore, "initialize_schema", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))


async def test_sqlite_telemetry_does_not_borrow_unrelated_postgres_pool(
    tmp_path: Path,
) -> None:
    settings = configuration(
        tmp_path,
        evaluation_dataset_storage="postgres",
        database_url="postgresql://user@localhost/test",
    )
    await sqlite_setup.initialize_sqlite(settings, metadata=metadata(settings))
    unrelated = cast(Pool, object())
    async with factory.cache_backend_lifespan(
        settings, dimensions=4, embedding_space=metadata(settings).space, pool=unrelated
    ) as backend:
        assert cast(OfficialStoreBackend, backend)._counter_pool is None
        await backend.record_miss("alpha")
        stats = await backend.stats("alpha")
        assert stats.misses == 1
        assert stats.hits == 0
