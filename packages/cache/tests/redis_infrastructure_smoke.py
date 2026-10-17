"""Run only with an explicitly labelled, pinned disposable Redis or Valkey container."""

import argparse
import asyncio
import json
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import version
from shutil import which
from typing import cast
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
VALKEY_IMAGE = "valkey/valkey:9.1.2@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd"
SPACE = EmbeddingSpace(identity="restart-v1", dimensions=2)


def docker(*args: str) -> str:
    executable = which("docker")
    if executable is None:
        raise RuntimeError("Docker is required for this disposable harness")
    return subprocess.run(  # noqa: S603 -- fixed Docker argv; owned containers verified
        [executable, *args], check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def server_command(image: str) -> str:
    if image == VALKEY_IMAGE:
        return "valkey-server"
    if re.fullmatch(r"redis:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}", image):
        return "redis-server"
    raise RuntimeError("Disposable fault tests require an approved pinned server image")


def owned(container: str) -> str:
    assert re.fullmatch(r"semantix-redis-[a-z0-9-]+", container)
    config = json.loads(docker("inspect", "--format", "{{json .Config}}", container))
    assert str(config["Labels"].get("semantix.disposable", "")).startswith(
        "redis-store"
    )
    image = str(config["Image"])
    server_command(image)
    return image


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


async def verify_version() -> None:
    expected = os.environ["REDIS_TEST_VERSION"]
    active = client(os.environ["REDIS_TEST_URL"])
    try:
        await ready(active)
        server = await active.info("server")
        product = os.environ.get("REDIS_TEST_PRODUCT", "redis")
        if product == "valkey":
            assert expected == "9.1.2", "Unexpected Valkey target"
            assert all(
                server.get(field) == value
                for field, value in {
                    "server_name": "valkey",
                    "valkey_version": expected,
                    "valkey_release_stage": "ga",
                    "redis_version": "7.2.4",
                    "server_mode": "standalone",
                }.items()
            ), "Unexpected Valkey identity/version/mode"
            assert "redis_mode" not in server, "Unexpected Valkey mode field"
            assert (await active.info("replication"))["role"] == "master"
            assert (await active.info("cluster"))["cluster_enabled"] == 0
            assert (await active.config_get("maxmemory-policy")) == {
                "maxmemory-policy": "noeviction"
            }
            execute = cast(Callable[..., Awaitable[object]], active.execute_command)
            commands = await execute(
                "COMMAND", "INFO", "eval", "eval_ro", "hpexpireat", "hpexpiretime"
            )
            assert isinstance(commands, dict)
            assert set(commands) == {"eval", "eval_ro", "hpexpireat", "hpexpiretime"}
            assert all(commands.values())
        else:
            assert product == "redis", "Unknown server product"
            assert server.get("redis_version") == expected, "Unexpected Redis version"
            assert (
                server.get("server_name", "redis") == "redis"
                and "valkey_version" not in server
            ), "Unexpected Redis server identity"
        print(f"Verified {product} {expected}; redis-py {version('redis')}")
    finally:
        await asyncio.wait_for(active.aclose(close_connection_pool=True), timeout=5)


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
        assert (await active.config_get("appendonly"))["appendonly"] == "yes"
        assert (await active.config_get("appendfsync"))["appendfsync"] == "always"
        assert (await active.info("persistence"))["aof_enabled"] == 1
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
    active = client(url)
    store = RedisStore(
        client=active,
        embedding_space=SPACE,
        key_prefix=prefix,
        max_size=3,
        default_ttl_seconds=None,
    )
    try:
        try:
            try:
                await store.validate_schema()
            except CacheStoreError:
                pass
            else:
                raise AssertionError("Stopped server unexpectedly accepted a read")
        finally:
            docker("start", container)
        await ready(active)
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


async def fault_container(mode: str, *, image: str = IMAGE) -> None:
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
        image,
        server_command(image),
        "--maxmemory-policy",
        "noeviction",
    ]
    if mode == "oom":
        args += ["--maxmemory", "3mb"]
    docker(*args)
    active: Redis | None = None
    store: RedisStore | None = None
    try:
        assert owned(name) == image
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
                await store.initialize_schema(initialization_client=active)
            except CacheStoreError:
                pass
            else:
                raise AssertionError("Read-only replica passed initialization")
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
                before = (
                    await active.hgetall(store._config.keys[0]),
                    await active.hgetall(store._config.keys[1]),
                    await active.zrange(store._config.keys[2], 0, -1, withscores=True),
                )
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
            if status == b"ready":
                assert before == (
                    await active.hgetall(store._config.keys[0]),
                    await active.hgetall(store._config.keys[1]),
                    await active.zrange(store._config.keys[2], 0, -1, withscores=True),
                ), "Refused write changed a ready binding"
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
            try:
                if store is not None:
                    await store.aclose()
            finally:
                if active is not None:
                    await active.aclose(close_connection_pool=True)
        finally:
            assert owned(name) == image
            docker("rm", "--force", "--volumes", name)


async def main() -> None:
    await verify_version()
    container = os.environ["REDIS_TEST_CONTAINER"]
    image = owned(container)
    product = os.environ.get("REDIS_TEST_PRODUCT", "redis")
    assert (server_command(image) == "valkey-server") == (product == "valkey")
    await restart(container, os.environ["REDIS_TEST_URL"])
    await fault_container("oom", image=image)
    await fault_container("readonly", image=image)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-version", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify_version() if args.verify_version else main())
