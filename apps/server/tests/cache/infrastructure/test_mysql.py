"""Real MySQL composition and native-worker shutdown ownership."""

import asyncio
import os
import threading
from typing import cast

import pymysql
import pytest
from pydantic import SecretStr

from app import lifecycle
from app.cache.application.service import SemanticCache
from app.cache.infrastructure import factory
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.cache.infrastructure.mysql_setup import initialize_mysql
from app.core.config import Settings
from app.core.exceptions import CacheStorageError, ProviderRequestError
from app.providers.factory import create_default_provider_registry
from app.providers.registry import EmbeddingMetadata
from app.query.application.service import QueryService
from semantix_cache import CacheEntry, CacheStoreError
from semantix_cache.stores._backends.mysql.database import Database
from semantix_cache.stores._backends.mysql.worker import Job, Worker
from semantix_cache.stores.mysql import MySQLStore
from tests.cache.mysql_support import connection, mysql_settings, receipt
from tests.query.application.test_shutdown import RetainedProvider, running_app

__all__ = ["mysql_settings"]
pytestmark = pytest.mark.mysql


def retired(worker: Worker) -> None:
    assert worker.connection is None
    assert worker.duplicate is None
    assert worker.pool_stopped
    assert not worker.remaining
    assert worker.thread is not None
    assert not worker.thread.is_alive()
    assert worker.resources is not None
    assert worker.resources.handles_closed
    assert all(item.closed for _, item in worker.resources.files)
    assert all(item.fileno() == -1 for _, item in worker.resources.sockets)


async def test_runtime_permissions_connect_only_and_cleanup(
    mysql_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = mysql_settings
    metadata = (
        create_default_provider_registry(settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )

    async def forbidden(**kwargs: object) -> None:
        raise AssertionError("Runtime attempted initialization")

    monkeypatch.setattr(MySQLStore, "initialize_schema", forbidden)
    async with factory.cache_backend_lifespan(
        settings, dimensions=metadata.dimensions, embedding_space=metadata.space
    ) as backend:
        store = cast(MySQLStore, cast(OfficialStoreBackend, backend).store)
        await backend.record_miss("alpha")
        assert (await backend.stats("alpha")).misses == 1
        assert cast(OfficialStoreBackend, backend)._counter_pool is None
        assert settings.cache_mysql_database
        assert settings.cache_mysql_user
        assert settings.cache_mysql_password
        with (
            connection(
                database=settings.cache_mysql_database.get_secret_value(),
                user=settings.cache_mysql_user.get_secret_value(),
                password=settings.cache_mysql_password.get_secret_value(),
            ) as active,
            active.cursor() as cursor,
        ):
            with pytest.raises(pymysql.MySQLError) as caught:
                cursor.execute("CREATE TABLE unauthorized (id INT)", ())
            assert caught.value.args[0] == 1142
    await store.aclose()
    retired(store._worker)


@pytest.mark.parametrize(
    "case", ["wrong_name", "expired", "untrusted", "no_tls", "wrong_password"]
)
async def test_startup_tls_and_auth_fail_closed(
    mysql_settings: Settings, case: str
) -> None:
    config = receipt()
    changes: dict[str, object] = {}
    if case == "wrong_name":
        changes["cache_mysql_tls_hostname"] = "wrong.invalid"
    elif case == "untrusted":
        changes["cache_mysql_ca_file"] = config["untrusted_ca_file"]
    elif case in {"expired", "no_tls"}:
        changes["cache_mysql_port"] = config[case + "_port"]
    else:
        changes["cache_mysql_password"] = SecretStr("private-invalid-password")
    settings = Settings.model_validate(mysql_settings.model_dump() | changes)
    metadata = (
        create_default_provider_registry(settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )
    with pytest.raises(CacheStorageError) as caught:
        async with factory.cache_backend_lifespan(
            settings, dimensions=metadata.dimensions, embedding_space=metadata.space
        ):
            pytest.fail("Invalid TLS/authentication yielded a backend")
    assert "private-invalid-password" not in str(caught.value)
    assert "wrong.invalid" not in str(caught.value)
    assert all(item.state == "retired" for item in MySQLStore.failed_cleanups())


async def test_incompatible_binding_and_later_failure_close_store(
    mysql_settings: Settings,
) -> None:
    metadata = (
        create_default_provider_registry(mysql_settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )
    with pytest.raises(CacheStorageError):
        async with factory.cache_backend_lifespan(
            mysql_settings, dimensions=4, embedding_space="uninitialized:binding"
        ):
            pytest.fail("Runtime adopted a missing binding")
    stores: list[MySQLStore] = []

    async def fail_after_connect() -> None:
        async with factory.cache_backend_lifespan(
            mysql_settings, dimensions=4, embedding_space=metadata.space
        ) as backend:
            stores.append(cast(MySQLStore, cast(OfficialStoreBackend, backend).store))
            raise RuntimeError("later construction failure")

    with pytest.raises(RuntimeError, match="later construction"):
        await fail_after_connect()
    retired(stores[0]._worker)


@pytest.mark.parametrize("outcome", ["within_budget", "expiry", "cancel"])
async def test_mysql_native_work_settles_before_lifespan_exit(
    mysql_settings: Settings, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    settings = mysql_settings
    config = receipt()
    await initialize_mysql(
        settings,
        metadata=EmbeddingMetadata(4, "shutdown-fixture"),
        setup_user=SecretStr(str(config["user"])),
        setup_password=SecretStr(os.environ["MYSQL_TEST_PASSWORD"]),
    )
    close_budget = 0.1 if outcome == "expiry" else 5.0
    monkeypatch.setattr(lifecycle, "QUERY_SHUTDOWN_GRACE_SECONDS", 0)
    loop = asyncio.get_running_loop()
    entered, closing = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    original_put, original_close = Database.put, MySQLStore.aclose
    owners: list[int] = []
    attempts: list[int] = []

    def held(
        database: Database, job: Job, entry: CacheEntry, ttl: float | None
    ) -> None:
        owners.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(10), "Release native-work barrier"
        original_put(database, job, entry, ttl)

    async def observed(store: MySQLStore) -> None:
        attempts.append(1)
        closing.set()
        await original_close(store)

    monkeypatch.setattr(Database, "put", held)
    monkeypatch.setattr(MySQLStore, "aclose", observed)
    provider = RetainedProvider()
    provider.release.set()
    backend_settings = {
        name: value
        for name, value in settings.model_dump().items()
        if name.startswith("cache_mysql_")
    }
    backend_settings.update(
        cache_backend="mysql",
        max_cache_size=4,
        cache_ttl_seconds=60,
        cache_mysql_close_timeout_seconds=close_budget,
    )
    context = running_app(provider, backend_settings=backend_settings)
    app = await context.__aenter__()
    service = cast(QueryService, app.state.query_service)
    store = cast(
        MySQLStore,
        cast(
            OfficialStoreBackend, cast(SemanticCache, app.state.semantic_cache)._backend
        ).store,
    )
    caller = asyncio.create_task(service.execute("retained native write"))
    shutdown: asyncio.Task[bool | None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        shutdown = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.wait_for(closing.wait(), 5)
        assert store._worker.pending
        assert store._worker.cleanup is None
        assert provider.client is not None
        assert not provider.client.is_closed
        assert not service._coalescer._in_flight
        if outcome == "within_budget":
            release.set()
            await shutdown
            retired(store._worker)
        else:
            if outcome == "cancel":
                shutdown.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await shutdown
            else:
                with pytest.raises(CacheStorageError, match="shutdown budget expired"):
                    await shutdown
            assert store._worker.pending
            assert store._worker.cleanup is None
            assert not store._worker.pool_stopped
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        count = len(attempts)
        await asyncio.gather(*tuple(store._worker.pending), return_exceptions=True)
        assert len(attempts) == count, "No detached server retry continues after exit"
        assert store._worker.faulted.is_set(), (
            "Cancelled mutation remains uncertain, never replayed"
        )
        await original_close(store)
        retired(store._worker)
        assert store._worker.thread is not None
        assert owners == [store._worker.thread.ident]


@pytest.mark.parametrize("outcome", ["expiry", "cancel"])
async def test_total_close_budget_keeps_mysql_cleanup_owned(
    mysql_settings: Settings, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    metadata = (
        create_default_provider_registry(mysql_settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )
    store = await factory._connect_mysql(mysql_settings, 4, metadata.space)
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    original = Worker._close
    calls: list[int] = []

    def held(worker: Worker) -> tuple[type[Exception], str] | None:
        loop.call_soon_threadsafe(entered.set)
        calls.append(threading.get_ident())
        assert release.wait(10)
        return original(worker)

    monkeypatch.setattr(Worker, "_close", held)
    closing = asyncio.create_task(
        factory._close_mysql(store, 0.1 if outcome == "expiry" else 5)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if outcome == "expiry":
            with pytest.raises(CacheStorageError, match="shutdown budget expired"):
                await closing
        else:
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
        assert store._worker.cleanup is not None
        assert not store._worker.cleanup.done()
        assert not store._worker.pool_stopped
    finally:
        release.set()
        await asyncio.gather(closing, return_exceptions=True)
        await store.aclose()
    retired(store._worker)
    assert store._worker.thread is not None
    assert calls == [store._worker.thread.ident]


async def test_cleanup_error_is_not_automatically_retried(
    mysql_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = (
        create_default_provider_registry(mysql_settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )
    original = MySQLStore.aclose
    calls: list[MySQLStore] = []

    async def fail_after_close(store: MySQLStore) -> None:
        await original(store)
        calls.append(store)
        raise CacheStoreError("private-cleanup-marker")

    monkeypatch.setattr(MySQLStore, "aclose", fail_after_close)
    with pytest.raises(CacheStorageError, match="Official cache cleanup failed"):
        async with factory.cache_backend_lifespan(
            mysql_settings, dimensions=4, embedding_space=metadata.space
        ):
            pass
    assert len(calls) == 1
    retired(calls[0]._worker)


@pytest.mark.parametrize("failure", [False, True])
async def test_cancelled_caller_generation_drains_before_resources(
    mysql_settings: Settings, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    config = receipt()
    await initialize_mysql(
        mysql_settings,
        metadata=EmbeddingMetadata(4, "shutdown-fixture"),
        setup_user=SecretStr(str(config["user"])),
        setup_password=SecretStr(os.environ["MYSQL_TEST_PASSWORD"]),
    )
    provider = RetainedProvider(error=ProviderRequestError() if failure else None)
    options = {
        key: value
        for key, value in mysql_settings.model_dump().items()
        if key.startswith("cache_mysql_")
    }
    options.update(cache_backend="mysql", max_cache_size=4, cache_ttl_seconds=60)
    context = running_app(provider, backend_settings=options)
    app = await context.__aenter__()
    service = cast(QueryService, app.state.query_service)
    store = cast(
        MySQLStore,
        cast(
            OfficialStoreBackend, cast(SemanticCache, app.state.semantic_cache)._backend
        ).store,
    )
    caller = asyncio.create_task(service.execute("retained generation"))
    await asyncio.wait_for(provider.started.wait(), 5)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    entered = asyncio.Event()
    original = QueryService.aclose

    async def observe(active: QueryService, *, grace_seconds: float) -> None:
        entered.set()
        await original(active, grace_seconds=grace_seconds)

    monkeypatch.setattr(QueryService, "aclose", observe)
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert not shutdown.done()
        assert provider.client is not None
        assert not provider.client.is_closed
        assert store._worker.connection is not None
        assert not store._worker.pool_stopped
    finally:
        provider.release.set()
    if failure:
        with pytest.raises(
            ExceptionGroup, match="Shared query shutdown failed"
        ) as caught:
            await shutdown
        assert isinstance(caught.value.exceptions[0], ProviderRequestError)
    else:
        await shutdown
    assert provider.calls == 1
    assert provider.client_closed_on_return is False
    assert provider.client is not None
    assert provider.client.is_closed
    assert not service._coalescer._in_flight
    assert not service._coalescer._cleanup_tasks
    retired(store._worker)
