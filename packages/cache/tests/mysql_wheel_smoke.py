"""Run outside the checkout with the installed MySQL extra and an owned fixture."""

import asyncio
import json
import os
import socket
import ssl
import sys
import threading
from hashlib import sha256
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import semantix_cache
from semantix_cache import AsyncSemanticCache, EmbeddingSpace

assert "pymysql" not in sys.modules
MySQLStore = import_module("semantix_cache.stores.mysql").MySQLStore
import pymysql  # noqa: E402


class Adapter:
    embedding_space = EmbeddingSpace(identity="mysql-wheel-v1", dimensions=2)

    async def embed(self, text: str) -> tuple[float, float]:
        return (1.0, 0.0)


async def main() -> None:
    config = json.loads(
        await asyncio.to_thread(Path(os.environ["MYSQL_TEST_CONFIG"]).read_text)
    )
    assert config["fixture_owner"] == "semantix-mysql-phase5"
    assert config["server_version"] == "8.4.12"
    assert "password" not in config
    credential = os.environ["MYSQL_TEST_PASSWORD"]
    name = "smx_wheel_" + uuid4().hex
    user, password = "wheel_" + uuid4().hex[:20], uuid4().hex
    admin = pymysql.Connection(
        host=config["tls_hostname"],
        port=config["port"],
        user=config["user"],
        password=credential.encode("utf8"),
        ssl=ssl.create_default_context(cafile=config["ca_file"]),
        autocommit=True,
        connect_timeout=2,
        read_timeout=5,
        write_timeout=5,
        defer_connect=True,
    )
    raw = socket.create_connection((config["address"], config["port"]), timeout=2)
    try:
        admin.connect(sock=raw)
        with admin.cursor() as cursor:
            cursor.execute("SELECT @@server_uuid,@@version")
            assert cursor.fetchone() == (config["server_uuid"], "8.4.12")
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
            cursor.execute(
                "CREATE USER IF NOT EXISTS 'semantix_schema_verifier'@'localhost' ACCOUNT LOCK"
            )
            cursor.execute(
                f"GRANT SELECT,TRIGGER,EXECUTE,EVENT ON `{name}`.* TO 'semantix_schema_verifier'@'localhost'"
            )
            cursor.execute(
                "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (user, password)
            )
        adapter = Adapter()
        options = {
            key: config[key]
            for key in (
                "address",
                "port",
                "tls_hostname",
                "ca_file",
                "user",
            )
        }
        options.update(
            database=name, embedding_space=adapter.embedding_space, password=credential
        )
        await MySQLStore.initialize_schema(**options)
        with admin.cursor() as cursor:
            for table, grants in (
                ("semantix_schema_migrations", "SELECT"),
                ("semantix_bindings", "SELECT,UPDATE"),
                ("semantix_entries", "SELECT,INSERT,UPDATE,DELETE"),
                ("semantix_payloads", "SELECT,INSERT,UPDATE,DELETE"),
            ):
                cursor.execute(
                    f"GRANT {grants} ON `{name}`.`{table}` TO %s@'%%'", (user,)
                )
            cursor.execute(
                f"GRANT EXECUTE ON PROCEDURE `{name}`.semantix_verify TO %s@'%%'",
                (user,),
            )
        options.update(user=user, password=password)

        async def generate(prompt: str) -> str:
            return "installed answer"

        async with (
            await MySQLStore.connect(**options) as store,
            AsyncSemanticCache(embedder=adapter, store=store) as cache,
        ):
            miss = await cache.resolve("first", generate=generate)
            hit = await cache.resolve("second", generate=generate)
            assert miss.cache_written and miss.provider_called
            assert hit.cache_hit and hit.generation_skipped
        async with await MySQLStore.connect(**options) as store:
            match = await store.find_nearest((1, 0), namespace="default")
            assert match is not None and match.entry.response == "installed answer"
    finally:
        if admin.open:
            admin.close()
        raw.close()
    assert semantix_cache.__file__ is not None
    assert "site-packages" in Path(semantix_cache.__file__).parts
    migration = import_module("semantix_cache.stores._mysql_schema")
    resources = files("semantix_cache.stores.mysql_migrations")
    assert (
        sha256(resources.joinpath("0001_cache.sql").read_bytes()).digest()
        == migration.CHECKSUM
    )
    assert (
        sha256(resources.joinpath("0002_verifier.sql").read_bytes()).digest()
        == migration.VERIFIER_CHECKSUM
    )
    assert (
        json.loads(resources.joinpath("0001_shape.json").read_text())
        == migration.EXPECTED
    )
    assert not MySQLStore.failed_cleanups()
    assert not any(t.name.startswith("semantix-mysql") for t in threading.enumerate())
    assert all(
        name not in sys.modules
        for name in ("app", "fastapi", "asyncpg", "redis", "httpx")
    )
    print(
        "Installed MySQL resources, optional isolation, least-privileged miss/hit and reopen verified"
    )


if __name__ == "__main__":
    asyncio.run(main())
