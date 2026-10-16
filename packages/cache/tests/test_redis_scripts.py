"""Pin Redis protocol bytes and the runner's existing script injection boundary."""

from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from semantix_cache import CacheStoreError, EmbeddingSpace
from semantix_cache.stores import redis as module
from semantix_cache.stores._backends.redis import scripts as _redis_scripts
from semantix_cache.stores.redis import RedisStore, _Configuration

# Captured from immutable main 412025807965d457fc320219e31660396c929150 before moving.
CHECKSUM = "d39472099de85395dea75f2bb00b85f63bf395cfd4df3b8dafef61c0bf85babf"
SPACE = EmbeddingSpace(identity="redis-script-refactor-v1", dimensions=2)


@pytest.mark.parametrize(
    ("name", "byte_count", "digest"),
    [
        (
            "_COMMON",
            809,
            "127988feaac767e407f6e1bb0c0839a6fa3cf8f7ec2296fbce4949dc574ff253",
        ),
        (
            "_DATA",
            3603,
            "0b04c973e827a4e1e8088d550b36b8c091a78da72f9cb4c1917ecef4c76140f1",
        ),
        (
            "_READ",
            5177,
            "bcaec2f5d866e5657dc0eb1f15b8e57500d9c06610f543253b465a698a3961b3",
        ),
        (
            "_WRITE",
            7782,
            "9c8c22b0b840384a5031f588d64c3c292ecba66453d7c30a4fdc0b6509f173c6",
        ),
        (
            "_INITIALIZE",
            4936,
            "a7d8a128ed009c73881b422e8d0e57d4605a5ab7b5226ec4c24209d5f2223837",
        ),
        (
            "_CLEAR_ALL",
            7772,
            "4be639f30134d729abae3a6303e3e1aec89c6fc45ab790aae7ecf0c50f115a53",
        ),
        (
            "_INSPECT",
            6406,
            "df2f5c46b2e7593cacb61cc08a59ac418c55f7a36d42aa8e7a5c92cbbf3d6c03",
        ),
    ],
)
def test_baseline_script_bytes(name: str, byte_count: int, digest: str) -> None:
    original_binding: str = getattr(module, name)
    extracted: str = getattr(_redis_scripts, name)
    assert original_binding == extracted
    data = extracted.encode("utf-8")
    assert len(data) == byte_count
    assert sha256(data).hexdigest() == digest


def test_checksum_and_clear_all_composition() -> None:
    assert module._CHECKSUM == _redis_scripts._CHECKSUM == CHECKSUM
    assert (
        sha256(
            (module._INITIALIZE + module._READ + module._WRITE).encode("utf-8")
        ).hexdigest()
        == CHECKSUM
    )
    assert (
        module._WRITE.replace("if member(key)==m then", "if true then")
        == module._CLEAR_ALL
    )


@pytest.mark.parametrize(
    ("ttl", "encoded"),
    [(None, ""), (60.0, "0x1.e000000000000p+5"), (0.125, "0x1.0000000000000p-3")],
)
def test_baseline_descriptor(ttl: float | None, encoded: str) -> None:
    config = _Configuration(SPACE, "refactor_probe", 128, ttl, 5.0, 2.0)
    assert config.descriptor == [
        "semantix-cache:redis:v1",
        CHECKSUM,
        SPACE.identity,
        "2",
        "128",
        encoded,
    ]
    prefix = "refactor_probe:{370adf52867c777a74509a965624d322ddc30e4a6c1bbabe114bc7c090039da6}:"
    assert config.keys == (prefix + "meta", prefix + "entries", prefix + "lru")


def test_descriptor_uses_redis_checksum_global(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _Configuration(SPACE, "refactor_probe", 128, None, 5.0, 2.0)
    monkeypatch.setattr(module, "_CHECKSUM", "patched-checksum")
    assert config.descriptor[1] == "patched-checksum"
    assert _redis_scripts._CHECKSUM == CHECKSUM


@pytest.mark.parametrize(
    "script_name", ["_INITIALIZE", "_READ", "_WRITE", "_CLEAR_ALL", "_INSPECT"]
)
async def test_operations_use_redis_script_globals(
    script_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = Redis(
        retry=Retry(NoBackoff(), 0),
        protocol=2,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    store = RedisStore(client=active, embedding_space=SPACE)
    original_clear_all = module._CLEAR_ALL
    script = f"patched-{script_name}"
    monkeypatch.setattr(module, script_name, script)
    execute = AsyncMock(
        side_effect=[
            {"redis_version": "8.10.2", "redis_mode": "standalone"},
            {"role": "master"},
            {"cluster_enabled": 0},
            {"maxmemory-policy": "noeviction"},
            {name: [1] for name in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")},
        ]
    )
    write = AsyncMock(return_value=0)
    read = AsyncMock(return_value=[0, []] if script_name == "_INSPECT" else 1)
    monkeypatch.setattr(active, "execute_command", execute)
    monkeypatch.setattr(active, "eval", write)
    monkeypatch.setattr(active, "eval_ro", read)
    suffix: tuple[object, ...]
    try:
        if script_name == "_INITIALIZE":
            await store.initialize_schema(initialization_client=active)
            suffix = ()
        elif script_name == "_READ":
            await store.validate_schema()
            suffix = ("validate",)
        elif script_name == "_WRITE":
            assert await store.clear(namespace="default") == 0
            suffix = ("clear", "default")
        elif script_name == "_CLEAR_ALL":
            assert await store.clear_all() == 0
            suffix = ("clear", "")
        else:
            page = await store.inspect_entries()
            assert page.total == 0
            suffix = ("", "", "null", 0, 20, "newest")
        selected = read if script_name in ("_READ", "_INSPECT") else write
        selected.assert_awaited_once_with(
            script, 3, *store._config.keys, *store._config.descriptor, *suffix
        )
        assert getattr(_redis_scripts, script_name) != script
        assert module._CHECKSUM == CHECKSUM
        if script_name in ("_READ", "_WRITE"):
            assert original_clear_all == module._CLEAR_ALL
    finally:
        await store.aclose()
        await active.aclose(close_connection_pool=True)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        *[
            (value, True)
            for value in (
                "7.4.11",
                "7.4.12",
                "8.2.10",
                "8.2.11",
                "8.4.7",
                "8.4.8",
                "8.6.7",
                "8.6.8",
                "8.8.3",
                "8.8.4",
                "8.10.2",
                "8.10.3",
            )
        ],
        *[
            (value, False)
            for value in (
                "6.2.24",
                "7.2.16",
                "7.4.10",
                "7.5.11",
                "8.0.99",
                "8.1.10",
                "8.2.9",
                "8.3.10",
                "8.4.6",
                "8.6.6",
                "8.8.2",
                "8.10.1",
                "8.12.0",
                "9.0.0",
                "",
                "8.10",
                "8.10.2.0",
                "v8.10.2",
                "8.10.2-rc1",
                "8.10.2+vendor",
                "8.10.2\n",
                " 8.10.2",
                "08.10.2",
                "8.010.2",
                "8.10.02",
                "8.10.+2",
                "8.10.-2",
                "8.10.٢",
                "8.10.2_0",
                "8.10." + "9" * 5000,
                None,
                8.10,
                b"8.10.2",
                ["8", "10", "2"],
            )
        ],
    ],
)
def test_server_version_policy(value: object, accepted: bool) -> None:
    assert module._supported_server_version(value) is accepted


@pytest.mark.parametrize(
    ("position", "response"),
    [
        (0, None),
        (0, {}),
        (0, {"redis_version": None, "redis_mode": "standalone"}),
        (0, {"redis_version": "7.2.16", "redis_mode": "standalone"}),
        (0, {"redis_version": "8.0.99", "redis_mode": "standalone"}),
        (0, {"redis_version": "8.10.2+vendor", "redis_mode": "standalone"}),
        (0, {"redis_version": "8.10.2", "redis_mode": "cluster"}),
        (
            0,
            {
                "redis_version": "8.10.2",
                "redis_mode": "standalone",
                "server_name": "valkey",
            },
        ),
        (
            0,
            {
                "redis_version": "8.10.2",
                "redis_mode": "standalone",
                "server_name": "other",
            },
        ),
        (
            0,
            {
                "redis_version": "8.10.2",
                "redis_mode": "standalone",
                "valkey_version": "9.1.2",
            },
        ),
        (1, {"role": "slave"}),
        (2, {"cluster_enabled": 1}),
        (3, {"maxmemory-policy": "allkeys-lru"}),
        (4, None),
        *[
            (
                4,
                {
                    name: [1]
                    for name in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")
                    if name != missing
                },
            )
            for missing in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")
        ],
        *[
            (
                4,
                {
                    name: None if name == missing else [1]
                    for name in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")
                },
            )
            for missing in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")
        ],
        (4, {name: [1] for name in ("eval", "eval_ro", "hpexpireat", "wrong_command")}),
    ],
)
async def test_initialization_rejects_unsupported_server_before_writes(
    monkeypatch: pytest.MonkeyPatch, position: int, response: object
) -> None:
    active = Redis(
        retry=Retry(NoBackoff(), 0),
        protocol=2,
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    store = RedisStore(client=active, embedding_space=SPACE)
    responses: list[object] = [
        {"redis_version": "8.10.2", "redis_mode": "standalone"},
        {"role": "master"},
        {"cluster_enabled": 0},
        {"maxmemory-policy": "noeviction"},
        {name: [1] for name in ("eval", "eval_ro", "hpexpireat", "hpexpiretime")},
    ]
    responses[position] = response
    execute = AsyncMock(side_effect=responses)
    write = AsyncMock()
    monkeypatch.setattr(active, "execute_command", execute)
    monkeypatch.setattr(active, "eval", write)
    try:
        with pytest.raises(CacheStoreError):
            await store.initialize_schema(initialization_client=active)
        write.assert_not_awaited()
    finally:
        await store.aclose()
        await active.aclose(close_connection_pool=True)
