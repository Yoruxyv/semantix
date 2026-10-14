"""Independent processes prove InnoDB revision, hit, LRU and crash authority."""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache.stores._backends.mysql.format import micros
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, new_database, options

pytestmark = pytest.mark.mysql


def send(process: asyncio.subprocess.Process, command: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write((json.dumps(command) + "\n").encode("utf8"))


async def receive(process: asyncio.subprocess.Process) -> Any:
    assert process.stdout is not None
    data = await asyncio.wait_for(process.stdout.readline(), 20)
    assert data, "Independent client exited without its expected response"
    return json.loads(data)


@asynccontextmanager
async def clients(
    name: str, count: int, capacity: int = 128
) -> AsyncIterator[list[asyncio.subprocess.Process]]:
    processes = []
    try:
        for _ in range(count):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-X",
                "utf8",
                "-B",
                "-m",
                "tests.mysql_process_client",
                name,
                str(capacity),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            processes.append(process)
            assert await receive(process) == "ready"
        yield processes
    finally:
        for process in processes:
            if process.returncode is None:
                send(process, {"action": "stop"})
            try:
                _, errors = await asyncio.wait_for(process.communicate(), 10)
            except TimeoutError:
                process.kill()
                await process.communicate()
                raise AssertionError("Owned client did not close its worker") from None
            assert process.returncode == 0, (
                "Independent client failed (private fixture retains diagnostics)"
            )
            assert not errors, "Independent client emitted diagnostics"


@pytest.mark.parametrize("writers", [1, 2, 4])
async def test_independent_revision_and_hit_serialization(writers: int) -> None:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "max_size": 128,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    async with clients(name, writers) as processes:
        for process in processes:
            send(process, {"action": "put", "prompt": "shared", "count": 10})
        assert (
            await asyncio.gather(*(receive(p) for p in processes)) == [True] * writers
        )
        ledger = await asyncio.to_thread(
            admin,
            "SELECT last_revision_us,access_counter FROM semantix_bindings",
            name=name,
        )
        assert ledger == [
            (micros(datetime(2020, 1, 1, tzinfo=UTC)) + writers * 10 - 1, writers * 10)
        ]
        async with await MySQLStore.connect(**config) as observer:
            match = await observer.find_nearest((1, 0), namespace="default")
            assert match
            command = {
                "action": "hit",
                "key": match.entry.cache_key,
                "revision": match.entry.created_at.isoformat(),
                "count": 10,
            }
            for process in processes:
                send(process, command)
            assert (
                await asyncio.gather(*(receive(p) for p in processes))
                == [[True] * 10] * writers
            )
        assert await asyncio.to_thread(
            admin, "SELECT hit_count,access_seq FROM semantix_entries", name=name
        ) == [(writers * 10, writers * 20)]


async def test_cross_process_binding_wide_lru() -> None:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "max_size": 2,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    async with clients(name, 2, capacity=2) as processes:
        for process, prompt, namespace in (
            (processes[0], "a", "first"),
            (processes[1], "b", "second"),
            (processes[0], "c", "first"),
        ):
            send(
                process,
                {"action": "put", "prompt": prompt, "namespace": namespace, "count": 1},
            )
            assert await receive(process) is True
    keys = await asyncio.to_thread(
        admin, "SELECT cache_key FROM semantix_entries ORDER BY cache_key", name=name
    )
    assert keys == sorted(
        [
            (entry("b", namespace="second").cache_key.encode("ascii"),),
            (entry("c", namespace="first").cache_key.encode("ascii"),),
        ]
    )


@pytest.mark.parametrize("side", ["before", "after"])
async def test_process_crash_around_commit(side: str) -> None:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "max_size": 128,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-m",
        "tests.mysql_process_client",
        name,
        "128",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await receive(process) == "ready"
        send(process, {"action": "crash", "side": side})
        assert await receive(process) == "commit boundary"
        process.kill()
        await asyncio.wait_for(process.communicate(), 10)
        async with await MySQLStore.connect(**config) as store:
            match = await store.find_nearest((1, 0), namespace="default")
            assert (match is not None) is (side == "after")
        assert await asyncio.to_thread(
            admin, "SELECT count(*) FROM semantix_entries", name=name
        ) == [(int(side == "after"),)]
        assert await asyncio.to_thread(
            admin, "SELECT access_counter FROM semantix_bindings", name=name
        ) == [(int(side == "after"),)]
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
