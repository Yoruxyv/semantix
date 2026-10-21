import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from app import lifecycle
from app.cache.application.service import SemanticCache
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.core.config import Settings
from app.core.exceptions import (
    CacheStorageError,
    ProviderRequestError,
    QueryShuttingDownError,
)
from app.factory import create_app
from app.observability.metrics import RuntimeMetrics
from app.providers.registry import (
    EmbeddingMetadata,
    ProviderBuildContext,
    ProviderRegistration,
    ProviderRegistry,
)
from app.query.application.service import QueryService
from app.query.domain.policies import QueryCachePolicy
from semantix_cache import CacheEntry as PackageEntry
from semantix_cache import EmbeddingSpace
from semantix_cache.stores._backends.sqlite.database import Database
from semantix_cache.stores._backends.sqlite.worker import Job, Worker
from semantix_cache.stores.sqlite import SQLiteStore


@dataclass
class RetainedProvider:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    client: httpx.AsyncClient | None = None
    task: asyncio.Task[object] | None = None
    resist_cancellation: bool = False
    error: Exception | None = None
    calls: int = 0
    client_closed_on_return: bool | None = None

    async def create_embedding(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        self.task = asyncio.current_task()
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if not self.resist_cancellation:
                raise
            await self.release.wait()
        self.client_closed_on_return = (
            None if self.client is None else self.client.is_closed
        )
        if self.error is not None:
            raise self.error
        return "fixture-generated-answer"


@asynccontextmanager
async def running_app(
    provider: RetainedProvider, *, backend_settings: dict[str, object] | None = None
) -> AsyncIterator[FastAPI]:
    registry = ProviderRegistry()

    def build(context: ProviderBuildContext) -> RetainedProvider:
        provider.client = context.client
        return provider

    registry.register(
        ProviderRegistration(
            name="shutdown-fixture",
            capabilities=frozenset({"embedding", "generation"}),
            builder=build,
            embedding_metadata=EmbeddingMetadata(
                dimensions=4, space="shutdown-fixture"
            ),
            generation_metadata={"fixture": "deterministic"},
        )
    )
    settings = Settings.model_validate(
        {
            "embedding_provider": "shutdown-fixture",
            "generation_provider": "shutdown-fixture",
            "cache_backend": "memory",
            "coordination_backend": "memory",
            "evaluation_dataset_storage": "session",
            "evaluation_run_history_storage": "disabled",
            "prompt_typo_correction_enabled": False,
            "auth_mode": "disabled",
            "allowed_origins": ["http://localhost"],
            "log_level": "ERROR",
            **(backend_settings or {}),
        }
    )
    application = create_app(settings, provider_registry=registry)
    async with application.router.lifespan_context(application):
        yield application


@pytest.mark.asyncio
async def test_lifespan_drains_resolution_after_all_callers_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the preserved real-lifespan event ledger with real MemoryStore writes."""
    provider = RetainedProvider()
    context = running_app(provider)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    metrics = cast(RuntimeMetrics, application.state.runtime_metrics)
    recorded = metrics.record_request_started
    starts = 0
    three_started = asyncio.Event()

    def observe_start() -> None:
        nonlocal starts
        recorded()
        starts += 1
        if starts == 3:
            three_started.set()

    monkeypatch.setattr(metrics, "record_request_started", observe_start)
    policy = QueryCachePolicy(namespace="shutdown-test")
    callers = [asyncio.create_task(service.execute("fixture-shutdown", policy=policy))]
    await provider.started.wait()
    callers.extend(
        asyncio.create_task(service.execute("fixture-shutdown", policy=policy))
        for _ in range(2)
    )
    await three_started.wait()
    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 2
    for caller in callers:
        caller.cancel()
    results = await asyncio.gather(*callers, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    shared = provider.task
    assert shared is not None
    assert not shared.done()
    stopping = asyncio.Event()

    async def stop() -> None:
        stopping.set()
        await context.__aexit__(None, None, None)

    shutdown = asyncio.create_task(stop())
    await stopping.wait()
    try:
        assert provider.client is not None
        assert not provider.client.is_closed
        assert not shared.done()
        assert not shutdown.done()
    finally:
        provider.release.set()
        await asyncio.gather(shared, shutdown, return_exceptions=True)
    shared.result()
    shutdown.result()
    assert provider.calls == 1
    assert provider.client_closed_on_return is False
    assert provider.client.is_closed
    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 0
    with pytest.raises(CacheStorageError):
        await application.state.semantic_cache.stats(namespace=policy.namespace)


@pytest.mark.asyncio
async def test_shutdown_rejects_new_http_queries_safely() -> None:
    provider = RetainedProvider()
    async with running_app(provider) as application:
        service = cast(QueryService, application.state.query_service)
        await service.aclose(grace_seconds=0)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/query", json={"prompt": "fixture-new"}
            )
        assert response.status_code == 503
        assert response.json() == {
            "error": "query_shutting_down",
            "detail": "Query service is shutting down.",
        }
        assert provider.calls == 0


@pytest.mark.asyncio
async def test_expiry_and_repeated_shutdown_cancellation_keep_resources_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "QUERY_SHUTDOWN_GRACE_SECONDS", 0)
    provider = RetainedProvider(resist_cancellation=True)
    context = running_app(provider)
    close_calls = 0
    exit_client = httpx.AsyncClient.__aexit__

    async def counted_exit(
        client: httpx.AsyncClient,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        nonlocal close_calls
        if client is provider.client:
            close_calls += 1
        await exit_client(client, exc_type, exc_value, traceback)

    # async with captures __aexit__ before entering, so install the observer first.
    monkeypatch.setattr(httpx.AsyncClient, "__aexit__", counted_exit)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    assert provider.client is not None
    caller = asyncio.create_task(service.execute("fixture-resistant"))
    await provider.started.wait()
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await provider.cancelled.wait()
        assert not shutdown.done()
        assert not provider.client.is_closed
        assert close_calls == 0
        for _ in range(2):
            shutdown.cancel()
            rejected = asyncio.create_task(service.execute("fixture-after-seal"))
            with pytest.raises(QueryShuttingDownError):
                await rejected
            assert not shutdown.done()
            assert not provider.client.is_closed
    finally:
        provider.release.set()
        await asyncio.gather(shutdown, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    assert provider.task is not None
    assert provider.task.done()
    provider.task.result()
    assert provider.client_closed_on_return is False
    assert provider.client.is_closed
    assert close_calls == 1
    await service.aclose(grace_seconds=0)
    assert close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["generation", "write"])
@pytest.mark.parametrize("cancel_shutdown", [False, True])
async def test_shutdown_settles_and_exposes_resolution_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str, cancel_shutdown: bool
) -> None:
    provider = RetainedProvider()
    context = running_app(provider)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    error = (
        ProviderRequestError("fixture-generation")
        if failure == "generation"
        else CacheStorageError("fixture-write")
    )
    if failure == "generation":
        provider.error = error
    else:
        cache = cast(SemanticCache, application.state.semantic_cache)

        async def failed_write(*args: object, **kwargs: object) -> None:
            raise error

        monkeypatch.setattr(cache, "store", failed_write)
    caller = asyncio.create_task(service.execute("fixture-failure"))
    await provider.started.wait()
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    stopping = asyncio.Event()

    async def stop() -> None:
        stopping.set()
        await context.__aexit__(None, None, None)

    shutdown = asyncio.create_task(stop())
    await stopping.wait()
    assert provider.client is not None
    assert not provider.client.is_closed
    if cancel_shutdown:
        shutdown.cancel()
        rejected = asyncio.create_task(service.execute("fixture-after-seal"))
        with pytest.raises(QueryShuttingDownError):
            await rejected
    provider.release.set()
    with pytest.raises(
        asyncio.CancelledError if cancel_shutdown else ExceptionGroup
    ) as caught:
        await shutdown
    group = caught.value.__cause__ if cancel_shutdown else caught.value
    assert isinstance(group, ExceptionGroup)
    assert group.exceptions == (error,)
    assert provider.task is not None
    assert provider.task.done()
    assert provider.task.exception() is error
    assert provider.client_closed_on_return is False
    assert provider.client.is_closed
    with pytest.raises(ExceptionGroup):
        await service.aclose(grace_seconds=0)


@pytest.mark.asyncio
async def test_shutdown_waits_for_bypass_response_threshold_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RetainedProvider()
    provider.release.set()
    context = running_app(provider)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    cache = cast(SemanticCache, application.state.semantic_cache)
    reading = asyncio.Event()
    release = asyncio.Event()
    read_threshold = cache.read_similarity_threshold

    async def blocked_threshold() -> float:
        reading.set()
        await release.wait()
        assert provider.client is not None
        assert not provider.client.is_closed
        return await read_threshold()

    monkeypatch.setattr(cache, "read_similarity_threshold", blocked_threshold)
    caller = asyncio.create_task(
        service.execute(
            "fixture-bypass",
            policy=QueryCachePolicy(read_enabled=False, write_enabled=False),
        )
    )
    await reading.wait()
    stopping = asyncio.Event()

    async def stop() -> None:
        stopping.set()
        await context.__aexit__(None, None, None)

    shutdown = asyncio.create_task(stop())
    await stopping.wait()
    try:
        assert not shutdown.done()
        assert provider.client is not None
        assert not provider.client.is_closed
        with pytest.raises(QueryShuttingDownError):
            await service.execute("fixture-after-seal")
    finally:
        release.set()
        await asyncio.gather(caller, shutdown, return_exceptions=True)
    result = caller.result()
    shutdown.result()
    assert result.provider_called
    assert not result.cache_hit
    assert provider.client.is_closed


@pytest.mark.asyncio
async def test_expiry_cancels_and_joins_cooperative_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "QUERY_SHUTDOWN_GRACE_SECONDS", 0)
    provider = RetainedProvider()
    context = running_app(provider)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    caller = asyncio.create_task(service.execute("fixture-expiry"))
    await provider.started.wait()
    await context.__aexit__(None, None, None)
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert provider.cancelled.is_set()
    assert provider.task is not None
    assert provider.task.cancelled()
    assert provider.client is not None
    assert provider.client.is_closed
    assert not service._coalescer._in_flight
    assert not service._coalescer._cleanup_tasks
    assert service._active_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("grace", [-1.0, float("nan"), float("inf")])
async def test_invalid_service_grace_preserves_admission(grace: float) -> None:
    provider = RetainedProvider()
    provider.release.set()
    async with running_app(provider) as application:
        service = cast(QueryService, application.state.query_service)
        with pytest.raises(ValueError, match="finite and nonnegative"):
            await service.aclose(grace_seconds=grace)
        assert (await service.execute("fixture-still-open")).provider_called


@pytest.mark.asyncio
async def test_cancellation_resistant_write_settles_before_store_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "QUERY_SHUTDOWN_GRACE_SECONDS", 0)
    provider = RetainedProvider()
    provider.release.set()
    context = running_app(provider)
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    cache = cast(SemanticCache, application.state.semantic_cache)
    writing, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    write = cache.store
    written = False

    async def blocked_write(*args: object, **kwargs: object) -> None:
        nonlocal written
        writing.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        await write("fixture-write", "fixture-generated-answer", [1.0, 0.0, 0.0, 0.0])
        written = True
        assert (await cache.stats()).size == 1

    monkeypatch.setattr(cache, "store", blocked_write)
    caller = asyncio.create_task(service.execute("fixture-write"))
    await writing.wait()
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await cancelled.wait()
        assert not shutdown.done()
        assert provider.client is not None
        assert not provider.client.is_closed
        assert (await cache.stats()).size == 0
    finally:
        release.set()
        await shutdown
    assert written
    assert provider.task is not None
    provider.task.result()
    assert provider.client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["within_budget", "expiry", "cancel"])
async def test_sqlite_native_work_settles_before_lifespan_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_testsuite_property: Callable[[str, object], None],
    outcome: str,
) -> None:
    """Preserve the original held-worker regression under the approved terminal policy."""
    space = EmbeddingSpace(identity="shutdown-fixture", dimensions=4)
    path = tmp_path / "owned.db"
    await SQLiteStore.initialize_schema(path, embedding_space=space)
    close_budget = 0.05 if outcome == "expiry" else 5.0
    monkeypatch.setattr(lifecycle, "QUERY_SHUTDOWN_GRACE_SECONDS", 0)
    loop = asyncio.get_running_loop()
    entered, closing = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    put = Database.put
    close = SQLiteStore.aclose
    physical_close = Worker._close_connection
    native_owner: list[int] = []
    disposed: list[int] = []
    close_attempts: list[int] = []

    def verify_physical_close(worker: Worker) -> None:
        connection = worker.connection
        assert connection is not None
        physical_close(worker)
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            _ = connection.in_transaction
        disposed.append(threading.get_ident())

    def blocked_write(
        database: Database, job: Job, entry: PackageEntry, ttl: float | None
    ) -> None:
        _ = job.connection.in_transaction
        native_owner.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Native-work test barrier was not released")
        put(database, job, entry, ttl)

    async def observed_close(active: SQLiteStore) -> None:
        close_attempts.append(1)
        closing.set()
        await close(active)

    monkeypatch.setattr(Database, "put", blocked_write)
    monkeypatch.setattr(Worker, "_close_connection", verify_physical_close)
    monkeypatch.setattr(SQLiteStore, "aclose", observed_close)
    provider = RetainedProvider()
    provider.release.set()
    context = running_app(
        provider,
        backend_settings={
            "cache_backend": "sqlite",
            "cache_sqlite_path": str(path),
            "cache_sqlite_close_timeout_seconds": close_budget,
        },
    )
    application = await context.__aenter__()
    service = cast(QueryService, application.state.query_service)
    cache = cast(SemanticCache, application.state.semantic_cache)
    store = cast(OfficialStoreBackend, cache._backend).store
    assert isinstance(store, SQLiteStore)
    caller = asyncio.create_task(service.execute("fixture-native-write"))
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
        assert not store._worker.pool._shutdown
        assert provider.client is not None
        assert not shutdown.done()
        assert not provider.client.is_closed
        assert service._shutdown_task is not None
        assert not service._coalescer._in_flight
        if outcome == "within_budget":
            release.set()
            await shutdown
            assert store._worker.connection is None
            assert not store._worker.pending
        else:
            if outcome == "cancel":
                shutdown.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await shutdown
            else:
                with pytest.raises(CacheStorageError, match="shutdown budget expired"):
                    await shutdown
            assert store._worker.pending
            assert store._worker.connection is not None
            assert store._worker.cleanup is None
            assert not store._worker.pool._shutdown
            assert not disposed
        record_testsuite_property(
            "sqlite_shutdown_" + outcome,
            json.dumps(
                {
                    "native_pending": len(store._worker.pending),
                    "query_tasks": len(service._coalescer._in_flight),
                    "http_client_closed": provider.client.is_closed,
                    "close_attempts": len(close_attempts),
                    "physical_close_count": len(disposed),
                    "outcome": outcome,
                },
                sort_keys=True,
            ),
        )
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        attempts_at_settlement = len(close_attempts)
        pending = tuple(store._worker.pending)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            assert (await store.inspect_entries()).total == 0
        assert len(close_attempts) == attempts_at_settlement
        await close(store)
        assert store._worker.connection is None
        assert store._worker.cleanup is not None
        assert store._worker.cleanup.done()
        assert all(not thread.is_alive() for thread in store._worker.pool._threads)
        assert disposed == native_owner
        record_testsuite_property(
            "fixture_cleanup_" + outcome, "CLOSED on original worker; executor joined"
        )
