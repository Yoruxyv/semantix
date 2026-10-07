"""Run only with an explicitly labelled disposable Redis Docker container."""

import asyncio
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from shutil import which
from uuid import uuid4

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as DriverConnectionError

from semantix_cache import CacheStoreError, EmbeddingSpace
from semantix_cache._semantics import prompt_cache_key
from semantix_cache.models import CacheEntry
from semantix_cache.stores.redis import RedisStore

IMAGE = "redis:8.10.2@sha256:c94085d298b738be22c9ccdc0ac3761fa6649df7dd82ad1d42367f3cb9714935"
SPACE = EmbeddingSpace(identity="restart-v1", dimensions=2)


def docker(*args: str) -> str:
    executable = which("docker")
    if executable is None:
        raise RuntimeError("Docker is required for this disposable harness")
    return subprocess.run(  # noqa: S603 -- fixed Docker argv; owned containers verified
        [executable, *args], check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def owned(container: str) -> None:
    assert re.fullmatch(r"semantix-redis-[a-z0-9-]+", container)
    labels = json.loads(
        docker("inspect", "--format", "{{json .Config.Labels}}", container)
    )
    assert str(labels.get("semantix.disposable", "")).startswith("redis-store")


def client(url: str) -> Redis:
    return Redis.from_url(
        url,
        retry=Retry(NoBackoff(), 0),
        protocol=2,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def value(
    prompt: str, namespace: str = "a", response: str = "synthetic response"
) -> CacheEntry:
    return CacheEntry(
        cache_key=prompt_cache_key(prompt, namespace=namespace),
        namespace=namespace,
        prompt=prompt,
        response=response,
        embedding=(1.0, 0.0),
        created_at=datetime(2400, 1, 1, tzinfo=UTC),
    )


async def ready(active: Redis) -> None:
    for _ in range(50):
        try:
            if await active.ping():
                return
        except (OSError, DriverConnectionError):
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError("Disposable Redis did not become ready")


async def restart(container: str, url: str) -> None:
    owned(container)
    prefix = "redis_restart_" + uuid4().hex
    active = client(url)
    store = RedisStore(
        client=active,
        embedding_space=SPACE,
        key_prefix=prefix,
        max_size=3,
        default_ttl_seconds=None,
    )
    try:
        await ready(active)
        await store.initialize_schema(initialization_client=active)
        a, b, c = value("keep a"), value("keep b", "b"), value("expire c", "c")
        await store.put(a, ttl_seconds=30)
        await store.put(b)
        await store.record_hit(
            a.cache_key, namespace="a", expected_created_at=a.created_at
        )
        await store.put(c, ttl_seconds=1)
        keys = store._config.keys
        before = await active.hgetall(keys[0])
        order = await active.zrange(keys[2], 0, -1)
        expiry = await active.hget(keys[1], "a|" + a.cache_key + ":e")
        await store.aclose()
        assert await active.exists(keys[0])
    finally:
        await active.aclose(close_connection_pool=True)
    docker("stop", "--time", "10", container)
    await asyncio.sleep(1.2)
    docker("start", container)
    active = client(url)
    await ready(active)
    store = RedisStore(
        client=active,
        embedding_space=SPACE,
        key_prefix=prefix,
        max_size=3,
        default_ttl_seconds=None,
    )
    try:
        await store.validate_schema()
        assert await active.hgetall(keys[0]) == before
        assert await active.zrange(keys[2], 0, -1) == order
        assert await active.hget(keys[1], "a|" + a.cache_key + ":e") == expiry
        kept = await store.find_nearest((1, 0), namespace="a")
        assert kept and kept.entry.created_at == a.created_at
        assert await active.hget(keys[1], "a|" + a.cache_key + ":h") == b"1"
        assert await store.find_nearest((1, 0), namespace="c") is None
        await store.clear(namespace="a")
        await store.put(a)
        newer = await store.find_nearest((1, 0), namespace="a")
        assert newer and newer.entry.created_at > a.created_at
        assert not await store.record_hit(
            a.cache_key, namespace="a", expected_created_at=a.created_at
        )
        assert await store.find_nearest((1, 0), namespace="b") is not None
        print(
            "AOF restart: payload, revisions, hit metadata, LRU and absolute downtime TTL passed"
        )
    finally:
        await store.aclose()
        await active.delete(*keys)
        await active.aclose(close_connection_pool=True)


async def fault_container(mode: str) -> None:
    name = "semantix-redis-fault-" + uuid4().hex
    args = [
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        "semantix.disposable=redis-store",
        "--publish",
        "127.0.0.1::6379",
        IMAGE,
        "redis-server",
        "--maxmemory-policy",
        "noeviction",
    ]
    if mode == "oom":
        args += ["--maxmemory", "3mb"]
    docker(*args)
    active: Redis | None = None
    try:
        owned(name)
        binding = docker("port", name, "6379/tcp")
        port = binding.rsplit(":", 1)[1]
        active = client("redis://127.0.0.1:" + port)
        await ready(active)
        store = RedisStore(
            client=active,
            embedding_space=SPACE,
            key_prefix="redis_fault_" + uuid4().hex,
            max_size=5,
            default_ttl_seconds=None,
        )
        await store.initialize_schema(initialization_client=active)
        if mode == "readonly":
            await active.replicaof("127.0.0.1", 1)
            try:
                await store.put(value("readonly"))
            except CacheStoreError:
                pass
            else:
                raise AssertionError(
                    "Writable mutation was accepted on a read-only replica"
                )
        else:
            refused = False
            for n in range(5):
                try:
                    await store.put(
                        value("oom " + str(n), response="\U0001f600" * 100000)
                    )
                except CacheStoreError:
                    refused = True
                    break
            assert refused
            status = await active.hget(store._config.keys[0], "status")
            assert status in (b"ready", b"mutating")
            if status == b"mutating":
                try:
                    await store.validate_schema()
                except CacheStoreError:
                    pass
                else:
                    raise AssertionError("Dirty OOM state was accepted")
        await store.aclose()
        print("Disposable real " + mode + " refusal passed")
    finally:
        try:
            if active is not None:
                await active.aclose(close_connection_pool=True)
        finally:
            owned(name)
            docker("rm", "--force", "--volumes", name)


async def main() -> None:
    await restart(os.environ["REDIS_TEST_CONTAINER"], os.environ["REDIS_TEST_URL"])
    await fault_container("oom")
    await fault_container("readonly")


if __name__ == "__main__":
    asyncio.run(main())
