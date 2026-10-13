"""Real disposable MySQL controls; credentials come only from a private receipt."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
import threading
from collections.abc import AsyncIterator, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymysql
import pytest

from examples.store_conformance import SPACE, HitMetadata, StoreCase, StoreFactory
from semantix_cache import EmbeddingSpace
from semantix_cache.stores import _mysql_database as database
from semantix_cache.stores._mysql_format import timestamp
from semantix_cache.stores.mysql import MySQLStore


def settings() -> dict[str, Any]:
    receipt = os.environ.get("MYSQL_TEST_CONFIG")
    if receipt is None:
        pytest.skip(
            "MYSQL_TEST_CONFIG must name an explicitly owned disposable fixture receipt"
        )
    result: dict[str, Any] = json.loads(Path(receipt).read_text(encoding="utf8"))
    assert result["fixture_owner"] == "semantix-mysql-phase5"
    assert result["server_uuid"]
    return result


@contextmanager
def admin_connection(name: str | None = None) -> Generator[Any, None, None]:
    config = settings()
    connection = pymysql.Connection(
        host=config["tls_hostname"],
        port=config["port"],
        user=config["user"],
        password=config["password"].encode("utf8"),
        database=name,
        ssl=ssl.create_default_context(cafile=config["ca_file"]),
        charset="utf8mb4",
        binary_prefix=True,
        autocommit=True,
        connect_timeout=2,
        read_timeout=10,
        write_timeout=10,
        defer_connect=True,
    )
    raw = socket.create_connection((config["address"], config["port"]), timeout=2)
    try:
        connection.connect(sock=raw)
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@server_uuid", ())
            assert cursor.fetchone() == (config["server_uuid"],), (
                "Fixture target changed"
            )
        yield connection
    finally:
        if connection.open:
            connection.close()


def admin(
    sql: str, parameters: Sequence[object] = (), *, name: str | None = None
) -> list[tuple[Any, ...]]:
    with admin_connection(name) as connection, connection.cursor() as cursor:
        cursor.execute(sql, tuple(parameters))
        return list(cursor.fetchall())


def options(name: str) -> dict[str, Any]:
    config = settings()
    return {
        key: config[key]
        for key in ("address", "port", "tls_hostname", "ca_file", "user", "password")
    } | {"database": name}


async def new_database() -> str:
    name = "smx_p5_" + uuid4().hex
    await asyncio.to_thread(
        admin,
        "CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin",
    )
    # Account provisioning is external to the adapter, inside this owned fixture.
    await asyncio.to_thread(
        admin,
        "CREATE USER IF NOT EXISTS 'semantix_schema_verifier'@'localhost' ACCOUNT LOCK",
    )
    assert await asyncio.to_thread(
        admin,
        "SELECT account_locked FROM mysql.user WHERE User='semantix_schema_verifier' AND Host='localhost'",
    ) == [("Y",)]
    await asyncio.to_thread(
        admin,
        f"GRANT SELECT,TRIGGER,EXECUTE,EVENT ON `{name}`.* TO 'semantix_schema_verifier'@'localhost'",
    )
    # Keep named databases for diagnosis; fixture lifetime owns their eventual removal.
    receipt = Path(os.environ["MYSQL_TEST_CONFIG"]).with_name(
        "owned-implementation-databases.jsonl"
    )
    with receipt.open("a", encoding="utf8") as stream:
        stream.write(json.dumps({"database": name}) + "\n")
    return name


@asynccontextmanager
async def block_lookup(
    store: MySQLStore, monkeypatch: pytest.MonkeyPatch, *, before_sql: bool = False
) -> AsyncIterator[asyncio.Event]:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    # Exercise the short conformance deadline before SQL; CPU tests keep the late barrier.
    target = store._database if before_sql else database
    boundary = "find" if before_sql else "nearest_index"
    original = getattr(target, boundary)

    def nearest(*args: Any, **kwargs: Any) -> Any:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Test worker was not released")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(target, boundary, nearest)
        try:
            yield entered
        finally:
            release.set()
            await store.find_nearest((1, 0), namespace="default")


@pytest.fixture
async def store_factory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[StoreFactory]:
    name = await new_database()
    stores: list[MySQLStore] = []
    username = "p5_" + uuid4().hex[:20]
    password = uuid4().hex + "\u691c\u8a3c\U0001f600"
    await asyncio.to_thread(
        admin, "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (username, password)
    )

    async def factory(
        capacity: int = 32, ttl: float | None = None, *, space: EmbeddingSpace = SPACE
    ) -> StoreCase:
        config = options(name) | {
            "embedding_space": space,
            "max_size": capacity,
            "default_ttl_seconds": ttl,
        }
        await MySQLStore.initialize_schema(**config)
        for table, grants in (
            ("semantix_schema_migrations", "SELECT"),
            ("semantix_bindings", "SELECT,UPDATE"),
            ("semantix_entries", "SELECT,INSERT,UPDATE,DELETE"),
            ("semantix_payloads", "SELECT,INSERT,UPDATE,DELETE"),
        ):
            await asyncio.to_thread(
                admin, f"GRANT {grants} ON `{name}`.`{table}` TO %s@'%%'", (username,)
            )
        await asyncio.to_thread(
            admin,
            f"GRANT EXECUTE ON PROCEDURE `{name}`.semantix_verify TO %s@'%%'",
            (username,),
        )
        store = await MySQLStore.connect(
            **(config | {"user": username, "password": password})
        )
        stores.append(store)
        identity = space.identity.encode("utf8")

        async def expire() -> None:
            await asyncio.to_thread(
                admin,
                "UPDATE semantix_entries e JOIN semantix_bindings b USING(binding_id) SET e.expires_at_us=-1 WHERE b.identity_utf8=%s AND b.dimensions=%s AND e.expires_at_us IS NOT NULL",
                (identity, space.dimensions),
                name=name,
            )

        async def metadata(key: str, namespace: str) -> HitMetadata | None:
            rows = await asyncio.to_thread(
                admin,
                "SELECT e.hit_count,e.last_accessed_at_us FROM semantix_entries e JOIN semantix_bindings b USING(binding_id) WHERE b.identity_utf8=%s AND b.dimensions=%s AND e.cache_key=%s AND e.namespace=%s",
                (
                    identity,
                    space.dimensions,
                    key.encode("ascii"),
                    namespace.encode("ascii"),
                ),
                name=name,
            )
            return (
                None
                if not rows
                else HitMetadata(
                    rows[0][0], None if rows[0][1] is None else timestamp(rows[0][1])
                )
            )

        return StoreCase(
            store,
            expire,
            metadata,
            lambda: block_lookup(store, monkeypatch, before_sql=True),
        )

    try:
        yield factory
    finally:
        for store in stores:
            await store.aclose()
