"""Redis-owned setup and integration checks; only explicitly disposable Redis."""

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, tzinfo
from typing import cast
from uuid import uuid4

import numpy as np
import pytest
from numpy.typing import NDArray
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from examples.store_conformance import SPACE as CONFORMANCE_SPACE
from examples.store_conformance import (
    HitMetadata,
    StoreCase,
    StoreConformance,
    StoreFactory,
)
from semantix_cache import (
    CacheConfigurationError,
    CacheStore,
    CacheStoreError,
    EmbeddingSpace,
)
from semantix_cache.stores import redis as redis_module
from semantix_cache.stores.redis import RedisStore, _datetime, _micros

SPACE = EmbeddingSpace(identity="redis-test-v1", dimensions=2)


def client(url: str = "redis://127.0.0.1:16379/0") -> Redis:
    return Redis.from_url(
        url,
        retry=Retry(NoBackoff(), 0),
        protocol=2,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
        max_connections=32,
    )


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    url = os.environ.get("REDIS_TEST_URL")
    if not url:
        pytest.skip("Set REDIS_TEST_URL to disposable Redis 8.10.2")
    active = client(url)
    try:
        yield active
    finally:
        await active.aclose(close_connection_pool=True)


@pytest.fixture
async def redis_store(redis_client: Redis) -> AsyncIterator[RedisStore]:
    store = RedisStore(
        client=redis_client,
        embedding_space=SPACE,
        key_prefix="redis_test_" + uuid4().hex,
        default_ttl_seconds=None,
    )
    await store.initialize_schema(initialization_client=redis_client)
    try:
        yield store
    finally:
        await store.aclose()
        await redis_client.delete(*store._config.keys)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_size": 0},
        {"max_size": True},
        {"max_size": 5001},
        {"key_prefix": "unsafe*"},
        {"key_prefix": "unsafe{tag}"},
        {"default_ttl_seconds": 0},
        {"default_ttl_seconds": float("nan")},
        {"operation_timeout_seconds": 0},
        {"close_timeout_seconds": float("inf")},
        {"embedding_space": EmbeddingSpace(identity="wide", dimensions=16001)},
        {
            "max_size": 5000,
            "embedding_space": EmbeddingSpace(identity="wide", dimensions=15360),
        },
    ],
)
def test_configuration(kwargs: dict[str, object]) -> None:
    options = {"client": client(), "embedding_space": SPACE, **kwargs}
    with pytest.raises(CacheConfigurationError):
        RedisStore(**options)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"decode_responses": True},
        {"protocol": 3},
        {"retry": Retry(NoBackoff(), 1)},
        {"socket_timeout": None},
        {"parser_class": object},
    ],
)
def test_borrowed_policy(kwargs: dict[str, object]) -> None:
    active = Redis(
        retry=Retry(NoBackoff(), 0),
        protocol=2,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    active.connection_pool.connection_kwargs.update(kwargs)
    with pytest.raises(CacheConfigurationError):
        RedisStore(client=active, embedding_space=SPACE)


def test_exact_datetime_roundtrip() -> None:

    for date in (datetime(1900, 1, 1, tzinfo=UTC), datetime.max.replace(tzinfo=UTC)):
        assert _datetime(_micros(date).encode()) == date

    class MissingOffset(tzinfo):
        def utcoffset(self, value: datetime | None) -> None:
            return None

        def dst(self, value: datetime | None) -> None:
            return None

        def tzname(self, value: datetime | None) -> None:
            return None

    for invalid in (
        datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        datetime(2020, 1, 1, tzinfo=MissingOffset()),
    ):
        with pytest.raises(ValueError, match="aware datetime"):
            _micros(invalid)


async def test_fresh_idempotent_concurrent_schema(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    await asyncio.gather(
        *[
            redis_store.initialize_schema(initialization_client=redis_client)
            for _ in range(8)
        ]
    )
    await redis_store.validate_schema()
    keys = redis_store._config.keys
    assert await redis_client.exists(keys[0]) == 1
    assert await redis_client.exists(*keys[1:]) == 0
    assert await redis_client.hget(keys[0], "last_revision_us") == b""


@pytest.mark.parametrize("position", [0, 1, 2])
async def test_wrong_types(
    redis_store: RedisStore, redis_client: Redis, position: int
) -> None:
    key = redis_store._config.keys[position]
    await redis_client.delete(key)
    await redis_client.set(key, b"foreign")
    with pytest.raises(CacheStoreError):
        await redis_store.validate_schema()
    with pytest.raises(CacheStoreError):
        await redis_store.initialize_schema(initialization_client=redis_client)
    assert await redis_client.get(key) == b"foreign"


async def test_no_adoption_and_configuration_mismatch(redis_client: Redis) -> None:
    prefix = "redis_test_" + uuid4().hex
    store = RedisStore(client=redis_client, embedding_space=SPACE, key_prefix=prefix)
    keys = store._config.keys
    try:
        with pytest.raises(CacheStoreError):
            await store.validate_schema()
        await redis_client.hset(keys[1], mapping={"foreign": b"data"})
        with pytest.raises(CacheStoreError):
            await store.initialize_schema(initialization_client=redis_client)
        await redis_client.delete(keys[1])
        await store.initialize_schema(initialization_client=redis_client)
        changed = RedisStore(
            client=redis_client, embedding_space=SPACE, key_prefix=prefix, max_size=501
        )
        with pytest.raises(CacheStoreError):
            await changed.validate_schema()
        await redis_client.hset(keys[0], "status", "mutating")
        with pytest.raises(CacheStoreError):
            await store.initialize_schema(initialization_client=redis_client)
        assert await redis_client.hget(keys[0], "status") == b"mutating"
    finally:
        await store.aclose()
        await redis_client.delete(*keys)


@asynccontextmanager
async def block_lookup(
    store: CacheStore, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[asyncio.Event]:
    entered = asyncio.Event()
    released = threading.Event()
    loop = asyncio.get_running_loop()
    original = redis_module._score

    def score(
        query: NDArray[np.float64], rows: object, dimensions: int, namespace: str
    ) -> tuple[bytes, bytes, float] | None:
        loop.call_soon_threadsafe(entered.set)
        if not released.wait(timeout=10):
            raise RuntimeError("Conformance worker was not released")
        return original(query, rows, dimensions, namespace)

    with monkeypatch.context() as patch:
        patch.setattr(redis_module, "_score", score)
        try:
            yield entered
        finally:
            released.set()
            await store.find_nearest((1, 0), namespace="default")


@pytest.fixture
async def store_factory(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[StoreFactory]:
    prefix = "redis_test_" + uuid4().hex
    stores: list[RedisStore] = []

    async def factory(
        capacity: int = 32,
        ttl: float | None = None,
        *,
        space: EmbeddingSpace = CONFORMANCE_SPACE,
    ) -> StoreCase:
        store = RedisStore(
            client=redis_client,
            embedding_space=space,
            key_prefix=prefix,
            max_size=capacity,
            default_ttl_seconds=ttl,
        )
        await store.initialize_schema(initialization_client=redis_client)
        stores.append(store)
        entries = store._config.keys[1]

        async def expire() -> None:
            data = cast(dict[bytes, bytes], await redis_client.hgetall(entries))
            for field, value in data.items():
                if field.endswith(b":e") and value:
                    await redis_client.hset(entries, field, b"1")

        async def metadata(key: str, namespace: str) -> HitMetadata | None:
            member = namespace + "|" + key
            values = await redis_client.hmget(
                entries, member + ":e", member + ":h", member + ":a"
            )
            expiry, count, accessed = values
            now = await redis_client.time()
            if count is None or (expiry and int(expiry) <= now[0] * 1000000 + now[1]):
                return None
            return HitMetadata(
                int(count), None if not accessed else _datetime(cast(bytes, accessed))
            )

        return StoreCase(
            store, expire, metadata, lambda: block_lookup(store, monkeypatch)
        )

    try:
        yield factory
    finally:
        for store in stores:
            await store.aclose()
            await redis_client.delete(*store._config.keys)


class TestRedisStore(StoreConformance):
    """All public conformance cases, including optional metadata/worker probes."""
