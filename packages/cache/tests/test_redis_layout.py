"""Redis leaves preserve borrowed-resource, deadline and subclass boundaries."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import DataError, ResponseError

from examples.store_conformance.cases import entry
from semantix_cache import CacheClosedError, CacheStoreError
from semantix_cache.inspection import InspectionPage
from semantix_cache.stores import redis as module
from semantix_cache.stores.redis import RedisStore

from . import test_redis
from .test_inspection import snapshot
from .test_redis_faults import assert_redacted

redis_client = test_redis.redis_client
redis_store = test_redis.redis_store
pytestmark = pytest.mark.redis


@pytest.mark.parametrize("failure", ["cancel", "driver", "programming"])
async def test_inspection_leaf_failure_keeps_one_operation_and_borrowed_client(
    redis_store: RedisStore, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls = 0
    marker = "synthetic-inspection-driver-details"

    async def fail(client: Redis, **arguments: object) -> InspectionPage:
        nonlocal calls
        calls += 1
        assert client is redis_store._client
        assert redis_store._state.active == 1
        assert arguments["script"] == module._INSPECT
        assert arguments["keys"] == redis_store._config.keys
        assert arguments["descriptor"] == redis_store._config.descriptor
        assert arguments["namespace"] == "default"
        assert arguments["offset"] == 0
        assert arguments["limit"] == 20
        assert await client.ping()
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "driver":
            raise ResponseError(marker)
        raise DataError("visible programming error")

    with monkeypatch.context() as patch:
        patch.setattr(module, "_inspect_page", fail)
        expected = (
            asyncio.CancelledError
            if failure == "cancel"
            else CacheStoreError
            if failure == "driver"
            else DataError
        )
        with pytest.raises(expected) as caught:
            await redis_store.inspect_entries(namespace="default")
        if failure == "driver":
            assert_redacted(caught.value, marker)
    assert calls == 1
    assert redis_store._state.active == 0
    assert not redis_store._workers
    assert not redis_store._client.connection_pool._in_use_connections
    await redis_store.validate_schema()
    assert await redis_store._client.ping()


async def test_public_subclass_search_batches_keep_one_readonly_operation(
    redis_store: RedisStore, redis_client: Redis
) -> None:
    values = [entry("record " + str(i), namespace="alpha") for i in range(101)]
    for value in values:
        await redis_store.put(value)
    await redis_store.put(entry("record foreign", namespace="beta"))
    before = await snapshot(redis_store)
    pages: list[tuple[int, int, int]] = []

    class ObservedStore(RedisStore):
        async def _inspect(self, **arguments: Any) -> InspectionPage:
            pages.append((arguments["offset"], arguments["limit"], self._state.active))
            return await super()._inspect(**arguments)

    async with await ObservedStore.connect(
        url=os.environ["REDIS_TEST_URL"],
        embedding_space=redis_store.embedding_space,
        key_prefix=redis_store._config.prefix,
        default_ttl_seconds=None,
    ) as owned:
        assert type(owned) is ObservedStore
        await owned.validate_schema()
        page = await owned.inspect_entries(
            namespace="alpha", search="record", offset=100, limit=1
        )
        assert page.total == 101
        assert len(page.items) == 1
        assert pages == [(0, 100, 1), (100, 100, 1)]
        assert page.items[0].response is None
        key = page.items[0].cache_key
        assert await owned.inspect_entry(key, namespaces=("beta",)) is None
        detail = await owned.inspect_entry(key, namespaces=("alpha",))
        assert detail is not None
        assert detail.response == next(v.response for v in values if v.cache_key == key)
        assert pages[-2:] == [(0, 1, 1), (0, 1, 1)]
        assert owned._state.active == 0
        assert not owned._workers
    assert owned._cleanup is not None
    assert owned._cleanup.done()
    with pytest.raises(CacheClosedError):
        await owned.validate_schema()
    assert await redis_client.ping()
    assert await snapshot(redis_store) == before
