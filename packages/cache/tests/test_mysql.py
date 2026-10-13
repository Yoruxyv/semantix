"""Real MySQL schema, policy, codecs, numerical and durable-authority checks."""

import asyncio
import sys
import traceback
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import CacheConfigurationError, CacheStoreError, EmbeddingSpace
from semantix_cache._semantics import nearest_index, normalized_vector
from semantix_cache.stores import _mysql_schema as schema
from semantix_cache.stores._mysql_format import HEADER, MAX_INT, MAX_US, decode_vector
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, new_database, options, store_factory

__all__ = ["store_factory"]
pytestmark = pytest.mark.mysql


@pytest.fixture
async def mysql_store() -> AsyncIterator[MySQLStore]:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    async with await MySQLStore.connect(**config) as store:
        yield store


@pytest.mark.parametrize(
    "change",
    [
        {"address": "localhost"},
        {"address": "::1"},
        {"address": "127.000.0.1"},
        {"port": True},
        {"port": 0},
        {"tls_hostname": ""},
        {"user": "bad\0name"},
        {"database": "mysql"},
        {"database": "BAD"},
        {"database": "bad`name"},
        {"max_size": 0},
        {"max_size": True},
        {"max_size": 5001},
        {"operation_timeout_seconds": 0},
        {"close_timeout_seconds": float("inf")},
        {"embedding_space": EmbeddingSpace(identity="wide", dimensions=16001)},
        {
            "embedding_space": EmbeddingSpace(identity="wide", dimensions=16000),
            "max_size": 5000,
        },
    ],
)
async def test_configuration_before_io(change: dict[str, Any]) -> None:
    with pytest.raises(CacheConfigurationError):
        await MySQLStore.connect(
            **cast(
                dict[str, Any],
                (
                    {
                        "address": "127.0.0.1",
                        "port": 1,
                        "tls_hostname": "localhost",
                        "ca_file": "missing.pem",
                        "user": "synthetic",
                        "password": b"",
                        "database": "absent",
                        "embedding_space": SPACE,
                    }
                    | change
                ),
            )
        )


async def test_no_driver_does_not_break_base_import() -> None:
    code = """
import sys
sys.modules['pymysql']=None
from semantix_cache import MemoryStore
assert 'semantix_cache.stores.mysql' not in sys.modules
try:
    from semantix_cache.stores.mysql import MySQLStore
except ImportError as error:
    assert '[mysql]' in str(error)
else:
    raise AssertionError('Missing driver accepted')
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, errors = await asyncio.wait_for(process.communicate(), 20)
        assert process.returncode == 0, errors.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


@pytest.mark.parametrize("kind", ["foreign", "initializing", "missing_binding"])
async def test_foreign_partial_and_unregistered_rejected(kind: str) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    if kind == "foreign":
        await asyncio.to_thread(
            admin, "CREATE TABLE app_data(secret VARBINARY(64))", name=name
        )
        await asyncio.to_thread(
            admin, "INSERT INTO app_data VALUES(%s)", (b"preserve",), name=name
        )
    elif kind == "initializing":
        await asyncio.to_thread(admin, schema.STATEMENTS[0], name=name)
        await asyncio.to_thread(
            admin,
            "INSERT INTO semantix_schema_migrations VALUES(1,%s,%s,%s,1)",
            (schema.OWNER, schema.CHECKSUM, b"INITIALIZING"),
            name=name,
        )
    else:
        await MySQLStore.initialize_schema(**config)
        config["embedding_space"] = EmbeddingSpace(
            identity="unregistered", dimensions=2
        )
    before = await asyncio.to_thread(admin, "SHOW TABLES", name=name)
    operation = (
        MySQLStore.connect
        if kind == "missing_binding"
        else MySQLStore.initialize_schema
    )
    with pytest.raises((CacheStoreError, CacheConfigurationError)):
        await operation(**config)
    assert await asyncio.to_thread(admin, "SHOW TABLES", name=name) == before
    if kind == "foreign":
        assert await asyncio.to_thread(
            admin, "SELECT secret FROM app_data", name=name
        ) == [(b"preserve",)]
    elif kind == "initializing":
        assert await asyncio.to_thread(
            admin, "SELECT state FROM semantix_schema_migrations", name=name
        ) == [(b"INITIALIZING",)]


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE semantix_schema_migrations SET checksum=REPEAT('x',32)",
        "UPDATE semantix_schema_migrations SET owner='foreign'",
        "UPDATE semantix_schema_migrations SET state='INITIALIZING'",
        "ALTER TABLE semantix_entries DROP INDEX lru_idx",
        "ALTER TABLE semantix_payloads DROP FOREIGN KEY sp_entry",
        "ALTER TABLE semantix_entries DROP CHECK se_hits",
        "ALTER TABLE semantix_entries ADD COLUMN extra INT",
        "ALTER TABLE semantix_payloads ENGINE=MyISAM",
        "CREATE VIEW foreign_view AS SELECT 1",
        "CREATE TRIGGER foreign_trigger AFTER DELETE ON semantix_entries FOR EACH ROW SET @changed=1",
    ],
)
async def test_schema_drift_rejected(mysql_store: MySQLStore, mutation: str) -> None:
    name = mysql_store._config.database
    if mutation.endswith("ENGINE=MyISAM"):
        await asyncio.to_thread(
            admin, "ALTER TABLE semantix_payloads DROP FOREIGN KEY sp_entry", name=name
        )
    await asyncio.to_thread(admin, mutation, name=name)
    with pytest.raises(CacheStoreError):
        await mysql_store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheStoreError):
        await MySQLStore.connect(
            **(options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None})
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE semantix_entries SET vector_blob=REPEAT(CHAR(0),28)",
        "DELETE FROM semantix_payloads",
        "UPDATE semantix_payloads SET payload_blob='{}'",
        "UPDATE semantix_bindings SET last_revision_us=NULL",
        "UPDATE semantix_bindings SET access_counter=0",
        "UPDATE semantix_entries SET namespace='*'",
        "UPDATE semantix_entries SET hit_count=1,last_accessed_at_us=NULL",
    ],
)
async def test_corruption_is_sanitized_error(
    mysql_store: MySQLStore, mutation: str
) -> None:
    await mysql_store.put(
        entry("private-prompt-marker", response="private-response-marker")
    )
    await asyncio.to_thread(admin, mutation, name=mysql_store._config.database)
    with pytest.raises(CacheStoreError) as caught:
        await mysql_store.find_nearest((1, 0), namespace="default")
    error = caught.value
    formatted = "".join(traceback.format_exception(error))
    assert error.__context__ is None
    assert error.__cause__ is None
    assert "private-response-marker" not in formatted
    assert "private-prompt-marker" not in formatted
    assert mysql_store._config.password.decode("utf8") not in formatted
    assert mysql_store._config.database not in formatted


@pytest.mark.parametrize("dimensions", [2, 384, 1536, 16000])
async def test_complete_float64_kernel(dimensions: int) -> None:
    name = await new_database()
    space = EmbeddingSpace(identity="numeric", dimensions=dimensions)
    config = options(name) | {
        "embedding_space": space,
        "max_size": 7,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    rng = np.random.default_rng(92)
    vectors = [tuple(rng.normal(size=dimensions)) for _ in range(7)]
    query = tuple(rng.normal(size=dimensions))
    async with await MySQLStore.connect(**config) as store:
        for index, vector in enumerate(vectors):
            await store.put(entry(str(index), vector=vector))
        rows = await asyncio.to_thread(
            admin,
            "SELECT cache_key,vector_blob FROM semantix_entries ORDER BY revision_us,cache_key",
            name=name,
        )
        matrix = np.asarray([decode_vector(blob, dimensions) for _, blob in rows])
        index, score = nearest_index(
            normalized_vector(query, dimensions=dimensions),
            cast(Sequence[Sequence[float]], matrix),
        )
        match = await store.find_nearest(query, namespace="default")
        assert match is not None
        assert match.entry.cache_key.encode("ascii") == rows[index][0]
        assert match.similarity_score == score
        for (_, blob), vector in zip(rows, vectors, strict=True):
            assert (
                blob[12:]
                == normalized_vector(vector, dimensions=dimensions)
                .astype("<f8")
                .tobytes()
            )


async def test_max_unicode_binary_payload_and_independent_connection(
    mysql_store: MySQLStore,
) -> None:
    value = entry("\U0001f600" * 2000, response="\U0001f600" * 100000)
    await mysql_store.put(value)
    name = mysql_store._config.database
    async with await MySQLStore.connect(
        **(options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None})
    ) as other:
        found = await other.find_nearest((1, 0), namespace="default")
        assert found is not None
        assert found.entry.response == value.response
        direct = await other._worker.run(
            lambda job: job.rows("SELECT %s", (bytes(range(256)) * 4096,)),
            readonly=True,
        )
        assert direct == [(bytes(range(256)) * 4096,)]


async def test_unicode_username_and_password(mysql_store: MySQLStore) -> None:
    user = "p5_" + uuid4().hex[:16] + "\u7528"
    password = uuid4().hex + "\u691c\u8a3c\U0001f600"
    await asyncio.to_thread(
        admin, "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (user, password)
    )
    name = mysql_store._config.database
    await asyncio.to_thread(
        admin, f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{name}`.* TO %s@'%%'", (user,)
    )
    await asyncio.to_thread(
        admin,
        f"GRANT EXECUTE ON PROCEDURE `{name}`.semantix_verify TO %s@'%%'",
        (user,),
    )
    async with await MySQLStore.connect(
        **(
            options(name)
            | {
                "user": user,
                "password": password,
                "embedding_space": SPACE,
                "default_ttl_seconds": None,
            }
        )
    ) as other:
        await other.put(entry("unicode credentials"))
        assert await other.find_nearest((1, 0), namespace="default") is not None


@pytest.mark.parametrize(
    ("column", "value"), [("last_revision_us", MAX_US), ("access_counter", MAX_INT)]
)
async def test_exhaustion_rolls_back(
    mysql_store: MySQLStore, column: str, value: int
) -> None:
    await mysql_store.put(entry("before"))
    name = mysql_store._config.database
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_bindings SET " + column + "=%s",  # noqa: S608 -- fixed parametrized ledger columns
        (value,),
        name=name,
    )
    before = await asyncio.to_thread(admin, "SELECT * FROM semantix_entries", name=name)
    with pytest.raises(CacheStoreError):
        await mysql_store.put(entry("after"))
    assert (
        await asyncio.to_thread(admin, "SELECT * FROM semantix_entries", name=name)
        == before
    )


async def test_revision_lru_and_binding_policy_survive_close() -> None:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "default_ttl_seconds": None,
        "max_size": 2,
    }
    await MySQLStore.initialize_schema(**config)
    value = entry("one", created_at=datetime(1900, 1, 1, tzinfo=UTC))
    async with await MySQLStore.connect(**config) as store:
        await store.put(value)
        await store.put(entry("two", namespace="other"))
        old = await store.find_nearest((1, 0), namespace="default")
        assert old is not None
        assert await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
    async with await MySQLStore.connect(**config) as store:
        await store.put(entry("three", namespace="other"))
        assert await store.find_nearest((1, 0), namespace="other") is not None
        assert await store.delete_entry(value.cache_key, namespace="default")
        await store.put(value)
        fresh = await store.find_nearest((1, 0), namespace="default")
        assert fresh is not None
        assert fresh.entry.created_at > old.entry.created_at
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
    with pytest.raises(CacheConfigurationError):
        await MySQLStore.connect(**(config | {"max_size": 3}))


async def test_negative_ties_and_nonwinning_corruption(mysql_store: MySQLStore) -> None:
    await mysql_store.put(entry("old", vector=(-1, 0)))
    await mysql_store.put(entry("new", vector=(-1, 0)))
    found = await mysql_store.find_nearest((1, 0), namespace="default")
    assert found is not None
    assert found.entry.prompt == "old"
    assert found.similarity_score == -1
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_entries SET vector_blob=%s WHERE cache_key=%s",
        (
            HEADER.pack(b"SMXV", 1, 1, 0, 2)
            + np.asarray([float("nan"), 0], dtype="<f8").tobytes(),
            entry("new", vector=(-1, 0)).cache_key.encode("ascii"),
        ),
        name=mysql_store._config.database,
    )
    with pytest.raises(CacheStoreError):
        await mysql_store.find_nearest((1, 0), namespace="default")
