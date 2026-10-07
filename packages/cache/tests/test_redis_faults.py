"""Redis state, race, deadline and redaction probes on disposable resources."""

import asyncio
import json
import os
import time
import traceback
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest
from redis._parsers.resp2 import _AsyncRESP2Parser
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.connection import Connection
from redis.exceptions import (
    AuthenticationError,
    BusyLoadingError,
    DataError,
    OutOfMemoryError,
    ReadOnlyError,
    ResponseError,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from examples.store_conformance.cases import entry
from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache._semantics import nearest_index, normalized_vector
from semantix_cache.stores import redis as module
from semantix_cache.stores.redis import RedisStore, _micros
from tests import redis_infrastructure_smoke as infrastructure
from tests.test_redis import SPACE, block_lookup, client
from tests.test_redis import redis_client as redis_client  # noqa: PLC0414 -- pytest fixture
from tests.test_redis import redis_store as redis_store  # noqa: PLC0414 -- pytest fixture


@pytest.mark.parametrize(
    "vector",
    [
        b"short",
        np.array([0.0, 0.0], dtype="<f8").tobytes(),
        np.array([float("nan"), 1.0], dtype="<f8").tobytes(),
        np.array([float("inf"), 1.0], dtype="<f8").tobytes(),
    ],
)
async def test_all_eligible_vectors_validated(
    redis_store: RedisStore, redis_client: Redis, vector: bytes
) -> None:
    good, bad = entry("good"), entry("bad", vector=(0, 1))
    await redis_store.put(good)
    await redis_store.put(bad)
    await redis_client.hset(
        redis_store._config.keys[1], "default|" + bad.cache_key + ":v", vector
    )
    with pytest.raises(CacheStoreError):
        await redis_store.find_nearest((1, 0), namespace="default")
    assert await redis_store.find_nearest((1, 0), namespace="foreign") is None


@pytest.mark.parametrize(
    "payload", [b"invalid", b"\xff", b'{"cache_key":"x","cache_key":"y"}', b"[]"]
)
async def test_payload_corruption_is_error(
    redis_store: RedisStore, redis_client: Redis, payload: bytes
) -> None:
    value = entry("payload")
    await redis_store.put(value)
    await redis_client.hset(
        redis_store._config.keys[1], "default|" + value.cache_key + ":p", payload
    )
    with pytest.raises(CacheStoreError):
        await redis_store.find_nearest((1, 0), namespace="default")


async def test_unknown_fields_and_counter_corruption(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    meta, entries, lru = redis_store._config.keys
    await redis_client.hset(entries, "orphan", b"value")
    with pytest.raises(CacheStoreError):
        await redis_store.validate_schema()
    with pytest.raises(CacheStoreError):
        await redis_store.initialize_schema(initialization_client=redis_client)
    await redis_client.delete(entries)
    for value in ("bad", "-1", "9007199254740992"):
        await redis_client.hset(meta, "access_counter", value)
        with pytest.raises(CacheStoreError):
            await redis_store.put(entry("counter"))
        assert await redis_client.hget(meta, "status") == b"ready"
    await redis_client.hset(meta, "access_counter", "0")
    await redis_store.validate_schema()
    assert await redis_client.zcard(lru) == 0


async def test_exact_revisions_overflow_and_binding_history(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    for date in (datetime(1900, 1, 1, tzinfo=UTC), datetime(2400, 1, 1, tzinfo=UTC)):
        value = entry("timestamp", created_at=date)
        await redis_store.put(value)
        match = await redis_store.find_nearest((1, 0), namespace="default")
        assert match
        assert match.entry.created_at == date
        await redis_store.put(value)
        newer = await redis_store.find_nearest((1, 0), namespace="default")
        assert newer
        assert newer.entry.created_at == date + timedelta(microseconds=1)
        await redis_store.delete_entry(value.cache_key, namespace="default")
    maximum = entry("maximum", created_at=datetime.max.replace(tzinfo=UTC))
    await redis_store.put(maximum)
    before = await redis_client.hgetall(redis_store._config.keys[0])
    with pytest.raises(CacheStoreError):
        await redis_store.put(maximum)
    assert await redis_client.hgetall(redis_store._config.keys[0]) == before


async def test_counter_resequence_and_rejected_confirmation_no_writes(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    a, b = entry("old"), entry("recent")
    await redis_store.put(a)
    await redis_store.put(b)
    meta, entries, lru = redis_store._config.keys
    member = "default|" + a.cache_key
    await redis_client.hset(meta, "access_counter", "9007199254740990")
    before = (
        await redis_client.hgetall(meta),
        await redis_client.hgetall(entries),
        await redis_client.zrange(lru, 0, -1, withscores=True),
    )
    assert not await redis_store.record_hit(
        a.cache_key,
        namespace="default",
        expected_created_at=a.created_at - timedelta(microseconds=1),
    )
    after = (
        await redis_client.hgetall(meta),
        await redis_client.hgetall(entries),
        await redis_client.zrange(lru, 0, -1, withscores=True),
    )
    assert before == after
    assert await redis_store.record_hit(
        a.cache_key, namespace="default", expected_created_at=a.created_at
    )
    assert await redis_client.hget(meta, "access_counter") == b"3"
    assert await redis_client.zrange(lru, 0, -1) == [
        ("default|" + b.cache_key).encode(),
        member.encode(),
    ]


@pytest.mark.parametrize("ttl", [0.1234567, 0.0005, 0.0000001])
async def test_fractional_and_submicrosecond_ttl(
    redis_store: RedisStore, redis_client: Redis, ttl: float
) -> None:
    value = entry("fractional")
    before = await redis_client.time()
    await redis_store.put(value, ttl_seconds=ttl)
    expires = await redis_client.hget(
        redis_store._config.keys[1], "default|" + value.cache_key + ":e"
    )
    if expires is not None:
        numerator, denominator = ttl.as_integer_ratio()
        assert (
            int(expires)
            >= before[0] * 1000000 + before[1] + numerator * 1000000 // denominator
        )
    await asyncio.sleep(ttl + 0.01)
    assert await redis_store.find_nearest((1, 0), namespace="default") is None
    assert not await redis_store.record_hit(
        value.cache_key, namespace="default", expected_created_at=value.created_at
    )


async def test_exact_logical_boundary_and_physical_deadline(
    redis_store: RedisStore, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = entry("boundary")
    await redis_store.put(value, ttl_seconds=5.123456)
    member = "default|" + value.cache_key
    entries = redis_store._config.keys[1]
    expiry = cast(bytes, await redis_client.hget(entries, member + ":e"))
    physical = await redis_client.execute_command(  # type: ignore[no-untyped-call]
        "HPEXPIRETIME", entries, "FIELDS", 1, member + ":a"
    )
    assert physical == [(int(expiry) + 999) // 1000]
    assert await redis_store.record_hit(
        value.cache_key, namespace="default", expected_created_at=value.created_at
    )
    assert (
        await redis_client.execute_command(  # type: ignore[no-untyped-call]
            "HPEXPIRETIME", entries, "FIELDS", 1, member + ":a"
        )
        == physical
    )
    # Freeze only the test script's observed TIME to prove the inclusive predicate.
    monkeypatch.setattr(
        module,
        "_READ",
        module._READ.replace(
            "local now=clock()", "local now='" + str(int(expiry) - 1) + "'"
        ),
    )
    assert await redis_store.find_nearest((1, 0), namespace="default") is not None
    monkeypatch.setattr(
        module, "_READ", module._READ.replace(str(int(expiry) - 1), expiry.decode())
    )
    assert await redis_store.find_nearest((1, 0), namespace="default") is None
    monkeypatch.setattr(
        module,
        "_WRITE",
        module._WRITE.replace(
            "local now=clock()", "local now='" + expiry.decode() + "'"
        ),
    )
    before = await redis_client.hgetall(redis_store._config.keys[0])
    assert not await redis_store.record_hit(
        value.cache_key, namespace="default", expected_created_at=value.created_at
    )
    assert await redis_client.hgetall(redis_store._config.keys[0]) == before


async def test_replacement_expiry_transitions_and_tombstones(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    value = entry("transition")
    await redis_store.put(value, ttl_seconds=5)
    await redis_store.put(value)
    key = redis_store._config.keys[1]
    assert await redis_client.execute_command(  # type: ignore[no-untyped-call]
        "HPEXPIRETIME", key, "FIELDS", 1, "default|" + value.cache_key + ":e"
    ) == [-1]
    await redis_store.put(value, ttl_seconds=0.01)
    await asyncio.sleep(0.03)
    assert await redis_client.hgetall(key) == {}
    assert await redis_client.zcard(redis_store._config.keys[2]) == 1
    await redis_store.put(entry("new"))
    assert await redis_client.zcard(redis_store._config.keys[2]) == 1


@pytest.mark.parametrize("mutation", ["replace", "delete", "clear", "expire"])
async def test_snapshot_and_winner_fetch_races(
    redis_store: RedisStore,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    value = entry("race")
    await redis_store.put(value)
    original = redis_client.eval_ro
    calls = 0

    async def intercepted(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal calls
        calls += 1
        if args[9] == "winner":
            if mutation == "replace":
                await redis_store.put(value)
            elif mutation == "delete":
                await redis_store.delete_entry(value.cache_key, namespace="default")
            elif mutation == "clear":
                await redis_store.clear(namespace="default")
            else:
                await redis_client.hset(
                    redis_store._config.keys[1],
                    "default|" + value.cache_key + ":e",
                    "1",
                )
        return await original(script, numkeys, *args)

    monkeypatch.setattr(redis_client, "eval_ro", intercepted)
    assert await redis_store.find_nearest((1, 0), namespace="default") is None
    assert calls == 2


@pytest.mark.parametrize(
    "error_type",
    [
        AuthenticationError,
        BusyLoadingError,
        RedisConnectionError,
        ReadOnlyError,
        OutOfMemoryError,
        ResponseError,
        RedisTimeoutError,
    ],
)
async def test_expected_error_redaction(
    redis_store: RedisStore,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    marker = "synthetic-secret-url-prompt-response-vector-endpoint"

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise error_type(marker)

    monkeypatch.setattr(redis_store._client, "eval", fail)
    expected = CacheTimeoutError if error_type is RedisTimeoutError else CacheStoreError
    with pytest.raises(expected) as caught:
        await redis_store.put(entry("redaction"))
    error = caught.value
    assert marker not in str(error) + repr(error) + "".join(
        traceback.format_exception(error)
    )
    assert error.__context__ is None
    assert marker not in str(error.__cause__)
    assert error.__cause__ is not None
    assert error.__cause__.__context__ is None


async def test_programming_error_is_not_translated(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise DataError("visible programming fault")

    monkeypatch.setattr(redis_store._client, "eval", fail)
    with pytest.raises(DataError, match="visible programming fault"):
        await redis_store.put(entry("bug"))


@pytest.mark.parametrize("after_write", [False, True])
async def test_lua_failure_status(
    redis_store: RedisStore,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    after_write: bool,
) -> None:
    script = module._WRITE
    needle = "redis.call('HSET',meta,'status','mutating')"
    injection = "error('synthetic failure',0)"
    script = script.replace(
        needle, needle + "\n" + injection if after_write else injection + "\n" + needle
    )
    monkeypatch.setattr(module, "_WRITE", script)
    with pytest.raises(CacheStoreError):
        await redis_store.put(entry("lua fault"))
    status = await redis_client.hget(redis_store._config.keys[0], "status")
    assert status == (b"mutating" if after_write else b"ready")
    if after_write:
        with pytest.raises(CacheStoreError):
            await redis_store.find_nearest((1, 0), namespace="default")


async def test_uncertain_acknowledgement_not_replayed(
    redis_store: RedisStore, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = entry("uncertain")
    await redis_store.put(value)
    original = redis_client.eval
    calls = 0

    async def sent_then_failed(script: str, numkeys: int, *args: Any) -> Any:
        nonlocal calls
        calls += 1
        await original(script, numkeys, *args)
        raise RedisConnectionError("lost synthetic acknowledgement")

    monkeypatch.setattr(redis_client, "eval", sent_then_failed)
    with pytest.raises(CacheStoreError):
        await redis_store.record_hit(
            value.cache_key, namespace="default", expected_created_at=value.created_at
        )
    assert calls == 1
    assert (
        await redis_client.hget(
            redis_store._config.keys[1], "default|" + value.cache_key + ":h"
        )
        == b"1"
    )


@pytest.mark.parametrize("dispatched", [False, True])
async def test_cancel_before_send_and_after_dispatch(
    redis_store: RedisStore,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: bool,
) -> None:
    value = entry("cancel")
    original = redis_client.eval
    sent = asyncio.Event()

    async def gated(script: str, numkeys: int, *args: Any) -> Any:
        if dispatched:
            await original(script, numkeys, *args)
        sent.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(redis_client, "eval", gated)
    task = asyncio.create_task(redis_store.put(value))
    await asyncio.wait_for(sent.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = await redis_client.hexists(
        redis_store._config.keys[1], "default|" + value.cache_key + ":r"
    )
    assert stored is dispatched


async def test_owned_close_borrowed_open_and_data_survives(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    await redis_store.put(entry("survives"))
    await redis_store.aclose()
    assert await redis_client.ping()
    owned = await RedisStore.connect(
        url=os.environ["REDIS_TEST_URL"],
        embedding_space=SPACE,
        key_prefix=redis_store._config.prefix,
        default_ttl_seconds=None,
    )
    await owned.validate_schema()
    assert await owned.find_nearest((1, 0), namespace="default") is not None
    await asyncio.gather(owned.aclose(), owned.aclose(), owned.aclose())
    assert owned._cleanup
    assert owned._cleanup.done()
    with pytest.raises(CacheClosedError):
        await owned.validate_schema()
    assert await redis_client.exists(redis_store._config.keys[0]) == 1


async def test_close_cancellation_retains_one_cleanup(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = await RedisStore.connect(
        url=os.environ["REDIS_TEST_URL"], embedding_space=SPACE
    )
    entered, release = asyncio.Event(), asyncio.Event()
    original = owned._client.aclose
    calls = 0

    async def gated(close_connection_pool: bool | None = None) -> None:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        await original(close_connection_pool=close_connection_pool)

    monkeypatch.setattr(owned._client, "aclose", gated)
    task = asyncio.create_task(owned.aclose())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    task2 = asyncio.create_task(owned.aclose())
    task2.cancel()
    await asyncio.gather(task2, return_exceptions=True)
    assert owned._cleanup is not None
    assert not owned._cleanup.done()
    release.set()
    await owned.aclose()
    assert calls == 1
    assert all(
        connection._writer is None
        for connection in owned._client.connection_pool._available_connections
    )


@pytest.mark.parametrize(
    "url", ["redis://127.0.0.1:1", "redis://127.0.0.1:16379/0?retry=10"]
)
async def test_owned_startup_failure_safe(url: str) -> None:
    error = (
        CacheConfigurationError if "?" in url else (CacheStoreError, CacheTimeoutError)
    )
    with pytest.raises(error):
        await RedisStore.connect(
            url=url, embedding_space=SPACE, connect_timeout_seconds=0.1
        )


async def test_real_acl_failure_before_business_writes(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    name = "redis_test_" + uuid4().hex
    await redis_client.acl_setuser(
        name,
        enabled=True,
        nopass=True,
        keys=[redis_store._config.prefix + ":*"],
        commands=["+@all", "-hpexpireat"],
    )
    restricted = client(os.environ["REDIS_TEST_URL"])
    restricted.connection_pool.connection_kwargs["username"] = name
    store = RedisStore(
        client=restricted,
        embedding_space=SPACE,
        key_prefix=redis_store._config.prefix,
        default_ttl_seconds=None,
    )
    try:
        with pytest.raises(CacheStoreError):
            await store.put(entry("acl"), ttl_seconds=5)
        assert (
            await redis_client.hget(redis_store._config.keys[0], "status") == b"ready"
        )
        assert await redis_client.hlen(redis_store._config.keys[1]) == 0
    finally:
        await store.aclose()
        await restricted.aclose()
        await redis_client.acl_deluser(name)


async def test_concurrent_distinct_writes_and_eviction_confirmation(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    # All namespaces compete for this test's binding capacity.
    redis_store._config = replace(redis_store._config, capacity=2)
    await redis_client.hset(redis_store._config.keys[0], "capacity", "2")
    values = [
        entry("distinct " + str(i), namespace="a" if i % 2 else "b") for i in range(16)
    ]
    await asyncio.gather(*(redis_store.put(value) for value in values))
    residents = await redis_client.zrange(redis_store._config.keys[2], 0, -1)
    assert len(residents) == 2
    # Concurrent writes need not complete in caller order; race the actual LRU.
    oldest = residents[0]
    assert isinstance(oldest, bytes)
    namespace, oldest_key = oldest.decode("ascii").split("|")
    winner = await redis_store.find_nearest((1, 0), namespace=namespace)
    assert winner is not None
    assert winner.entry.cache_key == oldest_key
    results = await asyncio.gather(
        redis_store.record_hit(
            winner.entry.cache_key,
            namespace=winner.entry.namespace,
            expected_created_at=winner.entry.created_at,
        ),
        redis_store.put(entry("evict", namespace="other")),
    )
    assert isinstance(results[0], bool)
    assert await redis_client.zcard(redis_store._config.keys[2]) == 2


async def test_native_lost_read_has_zero_business_retries(
    redis_store: RedisStore, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = entry("native retry")
    await redis_store.put(value)
    original = Connection.read_response
    failures = 0

    async def read(connection: Connection, *args: Any, **kwargs: Any) -> Any:
        nonlocal failures
        response = await original(connection, *args, **kwargs)
        if response == 1 and failures == 0:
            failures += 1
            raise RedisConnectionError("synthetic acknowledgement lost after real read")
        return response

    monkeypatch.setattr(Connection, "read_response", read)
    with pytest.raises(CacheStoreError):
        await redis_store.record_hit(
            value.cache_key, namespace="default", expected_created_at=value.created_at
        )
    assert failures == 1
    assert (
        await redis_client.hget(
            redis_store._config.keys[1], "default|" + value.cache_key + ":h"
        )
        == b"1"
    )


async def test_real_paused_write_operation_deadline(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    redis_store._config = replace(redis_store._config, timeout=0.02)
    await redis_client.execute_command("CLIENT", "PAUSE", 200, "WRITE")  # type: ignore[no-untyped-call]
    with pytest.raises(CacheTimeoutError):
        await redis_store.put(entry("paused"))
    await asyncio.sleep(0.25)
    redis_store._config = replace(redis_store._config, timeout=30)
    await redis_store.validate_schema()


@pytest.mark.parametrize(
    "boundary", ["get_connection", "send_packed_command", "read_response"]
)
async def test_cancelled_real_client_boundaries(
    redis_store: RedisStore,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    entered = asyncio.Event()
    cls: Any
    if boundary == "get_connection":
        cls, method = ConnectionPool, "get_connection"
    elif boundary == "send_packed_command":
        cls, method = asyncio.StreamWriter, "drain"
    else:
        cls, method = _AsyncRESP2Parser, "read_response"
    original = getattr(cls, method)

    async def gate(resource: object, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()
        return await original(resource, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cls, method, gate)
        task = asyncio.create_task(redis_store.put(entry("boundary gate")))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not redis_client.connection_pool._in_use_connections
    assert await redis_client.ping()


async def test_owned_close_deadline_closes_real_transports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = await RedisStore.connect(
        url=os.environ["REDIS_TEST_URL"],
        embedding_space=SPACE,
        close_timeout_seconds=0.02,
    )

    async def delayed(writer: asyncio.StreamWriter) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", delayed)
    with pytest.raises(CacheTimeoutError):
        await owned.aclose()
    assert all(
        connection._writer is None
        for connection in owned._client.connection_pool._available_connections
    )
    with pytest.raises(CacheTimeoutError):
        await owned.aclose()


@pytest.mark.parametrize("cleanup_timeout", [False, True])
async def test_startup_cancellation_cleans_created_client(
    monkeypatch: pytest.MonkeyPatch, cleanup_timeout: bool
) -> None:
    entered = asyncio.Event()
    clients: list[Redis] = []
    original = cast(Callable[..., Awaitable[object]], Redis.execute_command)

    async def ping(active: Redis, *args: Any, **kwargs: Any) -> Any:
        clients.append(active)
        await original(active, *args, **kwargs)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(Redis, "execute_command", ping)
    task = asyncio.create_task(
        RedisStore.connect(
            url=os.environ["REDIS_TEST_URL"],
            embedding_space=SPACE,
            close_timeout_seconds=0.02 if cleanup_timeout else 30,
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    if cleanup_timeout:

        async def delayed(writer: asyncio.StreamWriter) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", delayed)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(clients) == 1
    assert all(
        connection._writer is None
        for connection in clients[0].connection_pool._available_connections
    )


async def test_real_authentication_redaction(redis_client: Redis) -> None:
    name = "redis_test_" + uuid4().hex
    await redis_client.acl_setuser(
        name,
        enabled=True,
        passwords=["+synthetic-correct"],
        commands=["+ping"],
        keys=["*"],
    )
    bad = client(os.environ["REDIS_TEST_URL"])
    bad.connection_pool.connection_kwargs.update(
        username=name,
        password="synthetic-wrong-marker",  # noqa: S106 -- synthetic auth fault
    )
    store = RedisStore(client=bad, embedding_space=SPACE)
    try:
        with pytest.raises(CacheStoreError) as caught:
            await store.validate_schema()
        assert caught.value.__context__ is None
        assert "synthetic-wrong-marker" not in "".join(
            traceback.format_exception(caught.value)
        )
    finally:
        await store.aclose()
        await bad.aclose()
        await redis_client.acl_deluser(name)


async def test_float64_storage_negative_score_and_deterministic_tie(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    first = entry(
        "first tie",
        vector=(0.1234567890123456, 0.9876543210987654),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    second = entry("second tie", vector=first.embedding, created_at=first.created_at)
    await redis_store.put(first)
    await redis_store.put(second)
    vector = normalized_vector(first.embedding, dimensions=2)
    blob = await redis_client.hget(
        redis_store._config.keys[1], "default|" + first.cache_key + ":v"
    )
    assert blob == vector.astype("<f8", copy=False).tobytes()
    query = normalized_vector((-1.0, 0.0), dimensions=2)
    _, score = nearest_index(query, cast(Sequence[Sequence[float]], [tuple(vector)]))
    match = await redis_store.find_nearest((-1, 0), namespace="default")
    assert match
    assert match.entry.cache_key == first.cache_key
    assert match.similarity_score == score
    assert score < 0
    await redis_client.hset(
        redis_store._config.keys[1],
        "default|" + second.cache_key + ":r",
        _micros(first.created_at),
    )
    tied = await redis_store.find_nearest((-1, 0), namespace="default")
    assert tied
    assert tied.entry.cache_key == min(first.cache_key, second.cache_key)


async def test_valid_maximum_unicode_response_roundtrips(
    redis_store: RedisStore,
) -> None:
    value = entry("unicode", response="\U0001f600" * 100000)
    await redis_store.put(value)
    match = await redis_store.find_nearest((1, 0), namespace="default")
    assert match
    assert match.entry.response == value.response


async def test_store_deadline_retains_numeric_worker_and_admission(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await redis_store.put(entry("numeric deadline"))
    # Leave enough time for a real socket snapshot and thread admission on all runners.
    redis_store._config = replace(redis_store._config, timeout=0.5)
    async with block_lookup(redis_store, monkeypatch) as entered:
        task = asyncio.create_task(
            redis_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(CacheTimeoutError):
            await task
        with pytest.raises(CacheBusyError):
            await redis_store.aclose()
        waiting = asyncio.create_task(
            redis_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        redis_store._config = replace(redis_store._config, timeout=30)
    assert not redis_store._workers
    assert redis_store._worker_slot._value == 1


async def test_winner_decode_is_in_operation_deadline(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await redis_store.put(entry("decode deadline"))
    redis_store._config = replace(redis_store._config, timeout=0.05)
    original = module._decode

    def decode(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_decode", decode)
    with pytest.raises(CacheTimeoutError):
        await redis_store.find_nearest((1, 0), namespace="default")


def assert_redacted(error: BaseException, marker: str) -> None:
    assert marker not in str(error) + repr(error) + "".join(
        traceback.format_exception(error)
    )
    assert error.__context__ is None
    cause = error.__cause__
    assert isinstance(cause, RuntimeError)
    assert marker not in str(cause) + repr(cause) + "".join(
        traceback.format_exception(cause)
    )
    assert cause.__cause__ is None
    assert cause.__context__ is None


@pytest.mark.parametrize("phase", ["startup", "runtime"])
async def test_native_invalid_response_redacted(phase: str) -> None:
    marker = "synthetic-raw-response-" + uuid4().hex
    bad_command = b"PING" if phase == "startup" else b"EVAL_RO"
    malformed_replies = 0

    async def reply(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal malformed_replies
        try:
            async with asyncio.timeout(5):
                while header := await reader.readline():
                    assert header.startswith(b"*")
                    command = []
                    for _ in range(int(header[1:])):
                        field = await reader.readline()
                        assert field.startswith(b"$")
                        length = int(field[1:])
                        command.append((await reader.readexactly(length + 2))[:-2])
                    if command[0].upper() == bad_command:
                        malformed_replies += 1
                        writer.write(marker.encode() + b"\r\n")
                    elif command[0].upper() == b"PING":
                        writer.write(b"+PONG\r\n")
                    else:
                        writer.write(b"+OK\r\n")
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(reply, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        store: RedisStore | None = None

        async def operation() -> None:
            nonlocal store
            store = await RedisStore.connect(
                url="redis://127.0.0.1:" + str(port),
                embedding_space=SPACE,
                connect_timeout_seconds=2,
                operation_timeout_seconds=2,
            )
            if phase == "runtime":
                await store.validate_schema()

        try:
            with pytest.raises(CacheStoreError) as caught:
                await operation()
            assert malformed_replies == 1
            assert_redacted(caught.value, marker)
        finally:
            if store is not None:
                await store.aclose()


async def test_deeply_nested_payload_redacted(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    value = entry("nested payload")
    await redis_store.put(value)
    marker = "synthetic-corrupt-payload-" + uuid4().hex
    payload = b"[" * 1200 + json.dumps(marker).encode() + b"]" * 1200
    assert len(payload) < 1230000
    await redis_client.hset(
        redis_store._config.keys[1], "default|" + value.cache_key + ":p", payload
    )
    with pytest.raises(CacheStoreError) as caught:
        await redis_store.find_nearest((1, 0), namespace="default")
    assert_redacted(caught.value, marker)
    await redis_store.put(value)
    valid = await redis_store.find_nearest((1, 0), namespace="default")
    assert valid
    assert valid.entry.response == value.response


async def test_infrastructure_initial_readiness_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = client()
    entered, release = asyncio.Event(), asyncio.Event()
    initialized = False
    closed = 0
    original_close = active.aclose

    async def ping() -> bool:
        entered.set()
        return release.is_set()

    async def initialize(store: RedisStore, *, initialization_client: Redis) -> None:
        nonlocal initialized
        assert release.is_set()
        assert initialization_client is active
        initialized = True
        raise RuntimeError("Stop after initial readiness")

    async def close(close_connection_pool: bool | None = None) -> None:
        nonlocal closed
        closed += 1
        await original_close(close_connection_pool=close_connection_pool)

    monkeypatch.setattr(infrastructure, "owned", lambda container: None)
    monkeypatch.setattr(infrastructure, "client", lambda url: active)
    monkeypatch.setattr(active, "ping", ping)
    monkeypatch.setattr(active, "aclose", close)
    monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    task = asyncio.create_task(infrastructure.restart("semantix-redis-test", "unused"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not initialized
        release.set()
        with pytest.raises(RuntimeError, match="Stop after initial readiness"):
            await asyncio.wait_for(task, 2)
        assert initialized
        assert closed == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await original_close(close_connection_pool=True)


async def test_infrastructure_readiness_failure_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = client()
    attempts = 0
    closed = 0
    original_close = active.aclose

    async def ping() -> bool:
        nonlocal attempts
        attempts += 1
        raise RedisConnectionError("Synthetic unavailable disposable Redis")

    async def sleep(delay: float) -> None:
        pass

    async def close(close_connection_pool: bool | None = None) -> None:
        nonlocal closed
        closed += 1
        await original_close(close_connection_pool=close_connection_pool)

    monkeypatch.setattr(infrastructure, "owned", lambda container: None)
    monkeypatch.setattr(infrastructure, "client", lambda url: active)
    monkeypatch.setattr(active, "ping", ping)
    monkeypatch.setattr(active, "aclose", close)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="Disposable Redis did not become ready"):
        await infrastructure.restart("semantix-redis-test", "unused")
    assert attempts == 50
    assert closed == 1


@pytest.mark.parametrize("ownership_changed", [False, True])
async def test_fault_cleanup_survives_client_close_failure(
    monkeypatch: pytest.MonkeyPatch, ownership_changed: bool
) -> None:
    active = client()
    original_close = active.aclose
    name = ""
    inspections = 0
    removals: list[str] = []

    def docker(*args: str) -> str:
        nonlocal name, inspections
        if args[0] == "run":
            name = args[args.index("--name") + 1]
            return "synthetic-container-id"
        if args[0] == "inspect":
            assert args[-1] == name
            inspections += 1
            label = (
                "foreign" if ownership_changed and inspections > 1 else "redis-store"
            )
            return json.dumps({"semantix.disposable": label})
        if args[0] == "port":
            assert args[1] == name
            return "127.0.0.1:1"
        assert args == ("rm", "--force", "--volumes", name)
        removals.append(name)
        return name

    async def ready(resource: Redis) -> None:
        assert resource is active

    async def initialize(store: RedisStore, *, initialization_client: Redis) -> None:
        assert initialization_client is active

    async def command(*args: Any, **kwargs: Any) -> bytes:
        return b"OK"

    async def put(*args: Any, **kwargs: Any) -> None:
        raise CacheStoreError("Synthetic read-only refusal")

    async def close(close_connection_pool: bool | None = None) -> None:
        await original_close(close_connection_pool=close_connection_pool)
        raise OSError("Synthetic client-close failure")

    monkeypatch.setattr(infrastructure, "docker", docker)
    monkeypatch.setattr(infrastructure, "client", lambda url: active)
    monkeypatch.setattr(infrastructure, "ready", ready)
    monkeypatch.setattr(active, "execute_command", command)
    monkeypatch.setattr(active, "aclose", close)
    monkeypatch.setattr(RedisStore, "initialize_schema", initialize)
    monkeypatch.setattr(RedisStore, "put", put)
    expected = AssertionError if ownership_changed else OSError
    with pytest.raises(expected) as caught:
        await infrastructure.fault_container("readonly")
    assert inspections == 2
    assert removals == ([] if ownership_changed else [name])
    if not ownership_changed:
        assert str(caught.value) == "Synthetic client-close failure"
