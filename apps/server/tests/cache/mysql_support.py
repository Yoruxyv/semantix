"""Small server-test provisioning against the repository-owned TLS fixture."""

# SQL identifiers are generated UUIDs; credentials and data remain bound parameters.

import asyncio
import json
import os
import socket
import ssl
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import uuid4

import pymysql
import pytest
from pydantic import SecretStr

from app.cache.infrastructure.mysql_setup import initialize_mysql
from app.core.config import Settings
from app.providers.factory import create_default_provider_registry


def receipt() -> dict[str, object]:
    path = os.environ.get("MYSQL_TEST_CONFIG")
    assert path, "Required server MySQL tests need the repository-owned TLS fixture"
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    assert result["fixture_owner"] == "semantix-mysql-phase5"
    assert result["server_version"] == "8.4.12"
    assert os.environ.get("MYSQL_TEST_PASSWORD")
    return cast(dict[str, object], result)


@contextmanager
def connection(
    *, database: str | None = None, user: str | None = None, password: str | None = None
) -> Generator[pymysql.Connection, None, None]:
    config = receipt()
    active = pymysql.Connection(
        host=str(config["tls_hostname"]),
        port=int(str(config["port"])),
        user=str(config["user"]) if user is None else user,
        password=(
            os.environ["MYSQL_TEST_PASSWORD"] if password is None else password
        ).encode("utf-8"),
        database=database,
        ssl=ssl.create_default_context(cafile=str(config["ca_file"])),
        charset="utf8mb4",
        binary_prefix=True,
        autocommit=True,
        connect_timeout=2,
        read_timeout=10,
        write_timeout=10,
        defer_connect=True,
    )
    raw = socket.create_connection(
        (str(config["address"]), int(str(config["port"]))), timeout=2
    )
    try:
        active.connect(sock=raw)
        with active.cursor() as cursor:
            cursor.execute("SELECT @@server_uuid", ())
            assert cursor.fetchone() == (config["server_uuid"],)
        yield active
    finally:
        raw.close()
        if active.open:
            active.close()


def admin(
    sql: str, parameters: Sequence[object] = (), *, database: str | None = None
) -> list[tuple[object, ...]]:
    with connection(database=database) as active, active.cursor() as cursor:
        cursor.execute(sql, tuple(parameters))
        return cast(list[tuple[object, ...]], list(cursor.fetchall()))


async def provision() -> Settings:
    config = receipt()
    database, user, password = (
        "gc_" + uuid4().hex,
        "gc_" + uuid4().hex[:20],
        uuid4().hex,
    )
    await asyncio.to_thread(
        admin, f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
    )
    await asyncio.to_thread(
        admin,
        "CREATE USER IF NOT EXISTS 'semantix_schema_verifier'@'localhost' ACCOUNT LOCK",
    )
    await asyncio.to_thread(
        admin,
        f"GRANT SELECT,TRIGGER,EXECUTE,EVENT ON `{database}`.* TO 'semantix_schema_verifier'@'localhost'",
    )
    await asyncio.to_thread(
        admin, "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (user, password)
    )
    settings = Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "mock_embedding_dimensions": 4,
            "cache_backend": "mysql",
            "cache_mysql_address": config["address"],
            "cache_mysql_port": config["port"],
            "cache_mysql_tls_hostname": config["tls_hostname"],
            "cache_mysql_ca_file": config["ca_file"],
            "cache_mysql_database": database,
            "cache_mysql_user": user,
            "cache_mysql_password": password,
            "max_cache_size": 4,
            "cache_ttl_seconds": 60,
            "allowed_origins": ["http://localhost"],
            "rate_limit": "10000/minute",
            "auth_mode": "token",
            "auth_principals": [
                {
                    "name": name,
                    "role": role,
                    "namespaces": scopes,
                    "token_sha256": sha256(name.encode()).hexdigest(),
                }
                for name, role, scopes in [
                    ("reader", "viewer", ["alpha"]),
                    ("writer", "operator", ["alpha"]),
                    ("alpha-admin", "admin", ["alpha"]),
                    ("global-admin", "admin", ["*"]),
                ]
            ],
        }
    )
    metadata = (
        create_default_provider_registry(settings)
        .resolve("mock", "mock")
        .embedding_metadata
    )
    await initialize_mysql(
        settings,
        metadata=metadata,
        setup_user=SecretStr(str(config["user"])),
        setup_password=SecretStr(os.environ["MYSQL_TEST_PASSWORD"]),
    )
    for table, grants in (
        ("semantix_schema_migrations", "SELECT"),
        ("semantix_bindings", "SELECT,UPDATE"),
        ("semantix_entries", "SELECT,INSERT,UPDATE,DELETE"),
        ("semantix_payloads", "SELECT,INSERT,UPDATE,DELETE"),
    ):
        await asyncio.to_thread(
            admin, f"GRANT {grants} ON `{database}`.`{table}` TO %s@'%%'", (user,)
        )
    await asyncio.to_thread(
        admin,
        f"GRANT EXECUTE ON PROCEDURE `{database}`.semantix_verify TO %s@'%%'",
        (user,),
    )
    return settings


@pytest.fixture
async def mysql_settings() -> Settings:
    return await provision()
