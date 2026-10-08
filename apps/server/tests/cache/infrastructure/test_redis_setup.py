"""Setup-command errors stay private; its borrowed store never owns the client."""

import asyncio
import traceback

import pytest
from redis.asyncio import Redis, from_url
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.cache.infrastructure import setup
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from semantix_cache import CacheValidationError
from semantix_cache.stores.redis import RedisStore

MARKER = "simulated-secret-marker"
HOST = "private-setup-host.example.invalid"
URL = f"redis://replace-user:{MARKER}@{HOST}:6379/0"


@pytest.fixture
def setup_settings() -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        cache_backend="redis",
        redis_url=URL,
        allowed_origins=["http://localhost:5173"],
    )


@pytest.fixture
def owned_client(monkeypatch: pytest.MonkeyPatch) -> Redis:
    active = from_url(
        URL,
        decode_responses=False,
        protocol=2,
        retry=Retry(NoBackoff(), 0),
        socket_timeout=30,
        socket_connect_timeout=30,
    )

    def create(*args: object, **kwargs: object) -> Redis:
        return active

    monkeypatch.setattr(setup, "from_url", create)
    return active


@pytest.fixture
def setup_calls(monkeypatch: pytest.MonkeyPatch, owned_client: Redis) -> list[str]:
    calls: list[str] = []
    original_close = RedisStore.aclose

    async def initialize(self: RedisStore, *, initialization_client: Redis) -> None:
        assert initialization_client is owned_client
        assert self._client is owned_client
        assert not self._owned
        calls.append("initialize")

    async def store_close(self: RedisStore) -> None:
        await original_close(self)
        assert self._state.closed
        calls.append("store_close")

    async def close(*, close_connection_pool: bool) -> None:
        assert close_connection_pool
        calls.append("client_close")

    monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    monkeypatch.setattr(RedisStore, "aclose", store_close)
    monkeypatch.setattr(owned_client, "aclose", close)
    return calls


def assert_private(error: BaseException) -> None:
    exposed = "".join(traceback.format_exception(error))
    for sensitive in (MARKER, HOST, URL):
        assert sensitive not in str(error)
        assert sensitive not in exposed
    assert error.__cause__ is None
    assert error.__context__ is None
    if isinstance(error, CacheStorageError):
        assert error.status_code == 500
        assert error.error_code == "cache_error"


async def test_malformed_setup_url_is_sanitized(setup_settings: Settings) -> None:
    with pytest.raises(CacheStorageError) as caught:
        await setup.initialize_redis(
            setup_settings, initialization_url=f"redis://[{HOST}]:6379/0"
        )
    assert_private(caught.value)


@pytest.mark.parametrize(
    "kind", [ValueError, OSError, RedisError, CacheValidationError]
)
async def test_initialization_failure_is_sanitized_and_client_closed(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
    kind: type[Exception],
) -> None:
    async def fail(self: RedisStore, *, initialization_client: Redis) -> None:
        raise kind(f"{MARKER} {HOST} {URL}")

    monkeypatch.setattr(RedisStore, "initialize_schema", fail)
    with pytest.raises(CacheStorageError, match="Redis setup failed") as caught:
        await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert_private(caught.value)
    assert setup_calls == ["store_close", "client_close"]


@pytest.mark.parametrize("initialization_fails", [False, True])
async def test_cleanup_failure_is_sanitized_and_preserves_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
    initialization_fails: bool,
) -> None:
    attempts = 0

    async def close(*, close_connection_pool: bool) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError(f"{MARKER} {HOST} {URL}")

    async def fail(self: RedisStore, *, initialization_client: Redis) -> None:
        raise ValueError(f"{MARKER} {HOST} {URL}")

    monkeypatch.setattr(owned_client, "aclose", close)
    if initialization_fails:
        monkeypatch.setattr(RedisStore, "initialize_schema", fail)
    with pytest.raises(CacheStorageError) as caught:
        await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert_private(caught.value)
    assert str(caught.value).startswith(
        "Redis setup failed" if initialization_fails else "Redis setup cleanup failed"
    )
    assert attempts == 1
    assert setup_calls[-1] == "store_close"


async def test_success_closes_only_the_owned_client_once(
    setup_settings: Settings, setup_calls: list[str]
) -> None:
    await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert setup_calls == ["initialize", "store_close", "client_close"]


@pytest.mark.parametrize("cancel_during", ["setup", "cleanup"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_cancellation_propagates_after_bounded_owned_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
    cancel_during: str,
    cleanup_fails: bool,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    attempts = 0

    async def initialize(self: RedisStore, *, initialization_client: Redis) -> None:
        started.set()
        await asyncio.Event().wait()

    async def close(*, close_connection_pool: bool) -> None:
        nonlocal attempts
        attempts += 1
        try:
            if cancel_during == "cleanup":
                started.set()
                await release.wait()
            if cleanup_fails:
                raise OSError(f"{MARKER} {HOST} {URL}")
        finally:
            finished.set()

    if cancel_during == "setup":
        monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    monkeypatch.setattr(owned_client, "aclose", close)
    task = asyncio.create_task(
        setup.initialize_redis(setup_settings, initialization_url=URL)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        if cancel_during == "cleanup":
            assert not finished.is_set()
            release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=1)
        assert_private(caught.value)
        assert finished.is_set()
        assert attempts == 1
        assert setup_calls[-1] == "store_close"
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_cleanup_deadline_is_safe_and_stops_the_close_task(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
) -> None:
    finished = asyncio.Event()
    setup_settings.redis_close_timeout_seconds = 0.01

    async def close(*, close_connection_pool: bool) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(owned_client, "aclose", close)
    with pytest.raises(CacheStorageError, match="Redis setup cleanup failed") as caught:
        await asyncio.wait_for(
            setup.initialize_redis(setup_settings, initialization_url=URL), timeout=1
        )
    assert_private(caught.value)
    assert finished.is_set()


async def test_programming_error_is_not_suppressed_by_expected_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
) -> None:
    original = RuntimeError("setup programming defect")

    async def fail(self: RedisStore, *, initialization_client: Redis) -> None:
        raise original

    async def close(*, close_connection_pool: bool) -> None:
        raise OSError(f"{MARKER} {HOST}")

    monkeypatch.setattr(RedisStore, "initialize_schema", fail)
    monkeypatch.setattr(owned_client, "aclose", close)
    with pytest.raises(RuntimeError) as caught:
        await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert caught.value is original
    assert_private(caught.value)


async def test_sensitive_client_construction_error_has_no_client_to_close(
    monkeypatch: pytest.MonkeyPatch, setup_settings: Settings
) -> None:
    def fail(*args: object, **kwargs: object) -> Redis:
        raise ValueError(f"{MARKER} {HOST} {URL}")

    monkeypatch.setattr(setup, "from_url", fail)
    with pytest.raises(CacheStorageError, match="Redis setup failed") as caught:
        await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert_private(caught.value)


async def test_native_store_constructor_failure_closes_its_client(
    setup_settings: Settings, setup_calls: list[str]
) -> None:
    invalid = setup_settings.model_copy(update={"redis_key_prefix": "invalid|prefix"})
    with pytest.raises(CacheStorageError, match="Redis setup failed") as caught:
        await setup.initialize_redis(invalid, initialization_url=URL)
    assert_private(caught.value)
    assert setup_calls == ["client_close"]


async def test_expected_store_close_failure_still_closes_owned_client(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    setup_calls: list[str],
) -> None:
    original_close = RedisStore.aclose

    async def close(self: RedisStore) -> None:
        await original_close(self)
        raise CacheValidationError(f"{MARKER} {HOST}")

    monkeypatch.setattr(RedisStore, "aclose", close)
    with pytest.raises(CacheStorageError, match="Redis setup cleanup failed") as caught:
        await setup.initialize_redis(setup_settings, initialization_url=URL)
    assert_private(caught.value)
    assert setup_calls == ["initialize", "store_close", "client_close"]


@pytest.mark.parametrize("resource", ["store", "client"])
@pytest.mark.parametrize("initialization_fails", [False, True])
async def test_unexpected_cleanup_error_is_visible_without_losing_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
    resource: str,
    initialization_fails: bool,
) -> None:
    defect = RuntimeError("cleanup programming defect")

    async def fail(self: RedisStore, *, initialization_client: Redis) -> None:
        raise ValueError(f"{MARKER} {HOST} {URL}")

    async def client_close(*, close_connection_pool: bool) -> None:
        raise defect

    original_close = RedisStore.aclose

    async def store_close(self: RedisStore) -> None:
        await original_close(self)
        raise defect

    if initialization_fails:
        monkeypatch.setattr(RedisStore, "initialize_schema", fail)
    if resource == "store":
        monkeypatch.setattr(RedisStore, "aclose", store_close)
    else:
        monkeypatch.setattr(owned_client, "aclose", client_close)
    if initialization_fails:
        with pytest.raises(ExceptionGroup) as grouped:
            await setup.initialize_redis(setup_settings, initialization_url=URL)
        primary, secondary = grouped.value.exceptions
        assert isinstance(primary, CacheStorageError)
        assert (
            str(primary)
            == "Redis setup failed; verify initialization authority and binding configuration"
        )
        assert secondary is defect
        exposed = "".join(traceback.format_exception(grouped.value))
        for sensitive in (MARKER, HOST, URL):
            assert sensitive not in exposed
    else:
        with pytest.raises(RuntimeError) as caught:
            await setup.initialize_redis(setup_settings, initialization_url=URL)
        assert caught.value is defect
        assert_private(caught.value)
    if resource == "store":
        assert setup_calls[-1] == "client_close"


async def test_cancellation_during_cleanup_takes_priority_over_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def fail(self: RedisStore, *, initialization_client: Redis) -> None:
        raise ValueError(f"{MARKER} {HOST} {URL}")

    async def close(*, close_connection_pool: bool) -> None:
        started.set()
        await release.wait()
        finished.set()

    monkeypatch.setattr(RedisStore, "initialize_schema", fail)
    monkeypatch.setattr(owned_client, "aclose", close)
    task = asyncio.create_task(
        setup.initialize_redis(setup_settings, initialization_url=URL)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(task, timeout=1)
    assert_private(caught.value)
    assert finished.is_set()


async def test_repeated_cancellation_waits_for_one_bounded_close(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    attempts = 0

    async def close(*, close_connection_pool: bool) -> None:
        nonlocal attempts
        attempts += 1
        started.set()
        await release.wait()
        finished.set()

    monkeypatch.setattr(owned_client, "aclose", close)
    task = asyncio.create_task(
        setup.initialize_redis(setup_settings, initialization_url=URL)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(task, timeout=1)
    assert_private(caught.value)
    assert finished.is_set()
    assert attempts == 1


async def test_cancelled_close_task_is_terminal_and_does_not_spin(
    monkeypatch: pytest.MonkeyPatch,
    setup_settings: Settings,
    owned_client: Redis,
    setup_calls: list[str],
) -> None:
    attempts = 0

    async def close(*, close_connection_pool: bool) -> None:
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError

    monkeypatch.setattr(owned_client, "aclose", close)
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(
            setup.initialize_redis(setup_settings, initialization_url=URL), timeout=1
        )
    assert_private(caught.value)
    assert attempts == 1
