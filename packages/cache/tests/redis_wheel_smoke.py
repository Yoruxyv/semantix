"""Run only from an isolated installed wheel with the Redis extra."""

import asyncio
import os
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import semantix_cache
from semantix_cache import CacheEntry, EmbeddingSpace
from semantix_cache._semantics import prompt_cache_key

assert "redis" not in sys.modules
RedisStore = import_module("semantix_cache.stores.redis").RedisStore


async def main() -> None:
    prefix = "redis_wheel_" + uuid4().hex
    space = EmbeddingSpace(identity="wheel-redis-v1", dimensions=2)
    async with await RedisStore.connect(
        url=os.environ["REDIS_TEST_URL"],
        embedding_space=space,
        key_prefix=prefix,
    ) as store:
        await store.initialize_schema(initialization_client=store._client)
        try:
            value = CacheEntry(
                cache_key=prompt_cache_key("wheel prompt"),
                namespace="default",
                prompt="wheel prompt",
                response="wheel response",
                embedding=(1.0, 0.0),
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
            await store.put(value)
            async with await RedisStore.connect(
                url=os.environ["REDIS_TEST_URL"],
                embedding_space=space,
                key_prefix=prefix,
            ) as runtime:
                await runtime.validate_schema()
                match = await runtime.find_nearest((1, 0), namespace="default")
                assert match and match.entry.response == "wheel response"
                assert await runtime.record_hit(
                    value.cache_key,
                    namespace="default",
                    expected_created_at=match.entry.created_at,
                )
        finally:
            await store._client.delete(*store._config.keys)
    assert semantix_cache.__file__ is not None
    assert "site-packages" in Path(semantix_cache.__file__).parts
    assert "app" not in sys.modules and "fastapi" not in sys.modules
    print(
        "Installed Redis wheel, explicit schema, persistence and confirmation verified"
    )


if __name__ == "__main__":
    asyncio.run(main())
