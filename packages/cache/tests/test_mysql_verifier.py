"""Authoritative metadata, fixed definer capability, and explicit setup refusal."""

import asyncio
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pymysql
import pytest

from examples.store_conformance import SPACE, StoreFactory
from semantix_cache import CacheStoreError
from semantix_cache.stores._backends.mysql import schema
from semantix_cache.stores._backends.mysql.worker import Job
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, admin_connection, new_database, options, store_factory

__all__ = ["store_factory"]
pytestmark = pytest.mark.mysql


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE PROCEDURE foreign_routine() SELECT 1",
        "CREATE EVENT foreign_event ON SCHEDULE AT CURRENT_TIMESTAMP + INTERVAL 1 DAY DISABLE DO SELECT 1",
        "ALTER TABLE semantix_payloads ADD COLUMN extra INT",
        "ALTER TABLE semantix_payloads DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci",
        "ALTER TABLE semantix_entries ALTER INDEX scope_idx INVISIBLE",
        "ALTER TABLE semantix_entries ALTER CHECK se_hits NOT ENFORCED",
        "ALTER TABLE semantix_payloads DROP FOREIGN KEY sp_entry",
        "ALTER PROCEDURE semantix_verify SQL SECURITY INVOKER",
        "ALTER PROCEDURE semantix_verify COMMENT 'foreign verifier'",
        "UPDATE semantix_schema_migrations SET checksum=REPEAT('x',32) WHERE version=2",
        "UPDATE semantix_schema_migrations SET owner='foreign' WHERE version=2",
        "UPDATE semantix_schema_migrations SET state='INITIALIZING' WHERE version=2",
        "UPDATE semantix_schema_migrations SET version=3 WHERE version=2",
        "REVOKE TRIGGER ON `{database}`.* FROM 'semantix_schema_verifier'@'localhost'",
        "REVOKE EVENT ON `{database}`.* FROM 'semantix_schema_verifier'@'localhost'",
        "REVOKE EXECUTE ON `{database}`.* FROM 'semantix_schema_verifier'@'localhost'",
        "REVOKE SELECT ON `{database}`.* FROM 'semantix_schema_verifier'@'localhost'",
        "REVOKE EXECUTE ON PROCEDURE `{database}`.semantix_verify FROM '{runtime}'@'%%'",
        "DROP PROCEDURE semantix_verify",
    ],
)
async def test_existing_and_fresh_stores_refuse_schema_or_verifier_drift(
    store_factory: StoreFactory, sql: str
) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    name = store._config.database
    # Only test-generated ASCII identifiers are substituted; no production SQL template.
    await asyncio.to_thread(
        admin, sql.format(database=name, runtime=store._config.user), name=name
    )
    with pytest.raises(CacheStoreError):
        await store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheStoreError):
        await MySQLStore.connect(
            **(
                options(name)
                | {"user": store._config.user, "password": store._config.password}
            ),
            embedding_space=SPACE,
            default_ttl_seconds=None,
            max_size=32,
        )


async def test_exact_routine_body_is_verified(store_factory: StoreFactory) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    name = store._config.database
    result = await store._worker.run(
        lambda job: job.rows("CALL semantix_verify()"), readonly=True
    )
    assert result == [(2, 1, schema.VERIFIER_BODY_CHECKSUM)]
    await asyncio.to_thread(admin, "DROP PROCEDURE semantix_verify", name=name)

    # Semantically equivalent body change must still fail the immutable digest check.
    def replace() -> None:
        with admin_connection(name) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION',collation_connection='utf8mb4_bin'"
            )
            cursor.execute(
                schema.VERIFIER_SQL.replace(
                    "SELECT 2,COALESCE", "SELECT 02,COALESCE", 1
                )
            )

    await asyncio.to_thread(replace)
    await asyncio.to_thread(
        admin,
        f"GRANT EXECUTE ON PROCEDURE `{name}`.semantix_verify TO %s@'%%'",
        (store._config.user,),
    )
    result = await store._worker.run(
        lambda job: job.rows("CALL semantix_verify()"), readonly=True
    )
    assert result[0][:2] == (2, 1)
    assert result[0][2] != schema.VERIFIER_BODY_CHECKSUM
    with pytest.raises(CacheStoreError, match="schema shape or verifier"):
        await store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheStoreError, match="schema shape or verifier"):
        await MySQLStore.connect(
            **options(name),
            embedding_space=SPACE,
            max_size=32,
            default_ttl_seconds=None,
        )


@pytest.mark.parametrize("object_type", ["routine", "event"])
async def test_setup_refuses_otherwise_empty_database_with_stored_objects(
    object_type: str,
) -> None:
    name = await new_database()
    sql = (
        "CREATE PROCEDURE foreign_routine() SELECT 1"
        if object_type == "routine"
        else "CREATE EVENT foreign_event ON SCHEDULE AT CURRENT_TIMESTAMP + INTERVAL 1 DAY DISABLE DO SELECT 1"
    )
    await asyncio.to_thread(admin, sql, name=name)
    with pytest.raises(CacheStoreError, match="foreign stored objects"):
        await MySQLStore.initialize_schema(**options(name), embedding_space=SPACE)
    assert await asyncio.to_thread(admin, "SHOW TABLES", name=name) == []


async def test_original_version_is_preserved_without_implicit_verifier_upgrade() -> (
    None
):
    name = await new_database()
    assert (
        schema.CHECKSUM.hex()
        == "2a2b9d29118053d8091871c30369ac0c629fa03d7291722ca1a0ba840f13cd13"
    )
    for statement in schema.STATEMENTS:
        await asyncio.to_thread(admin, statement, name=name)
    await asyncio.to_thread(
        admin,
        "INSERT INTO semantix_schema_migrations VALUES(1,%s,%s,%s,1)",
        (schema.OWNER, schema.CHECKSUM, b"READY"),
        name=name,
    )
    before = await asyncio.to_thread(
        admin, "SELECT * FROM semantix_schema_migrations", name=name
    )
    for operation in (MySQLStore.initialize_schema, MySQLStore.connect):
        with pytest.raises(CacheStoreError, match="migration checksum"):
            await operation(**options(name), embedding_space=SPACE)
    assert (
        await asyncio.to_thread(
            admin, "SELECT * FROM semantix_schema_migrations", name=name
        )
        == before
    )
    assert await asyncio.to_thread(
        admin,
        "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s",
        (name,),
        name=name,
    ) == [(0,)]


async def test_failure_after_verifier_ddl_never_marks_schema_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = await new_database()
    original = Job.rows
    workers = []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original(job, sql, parameters)
        if sql == schema.VERIFIER_SQL:
            workers.append(job.owner)
            raise pymysql.OperationalError(2013, "private-verifier-ddl-failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        with pytest.raises(CacheStoreError):
            await MySQLStore.initialize_schema(**options(name), embedding_space=SPACE)
    assert len(workers) == 1
    assert workers[0].thread is not None
    assert not workers[0].thread.is_alive()
    assert await asyncio.to_thread(
        admin,
        "SELECT version,state FROM semantix_schema_migrations ORDER BY version",
        name=name,
    ) == [(1, b"INITIALIZING"), (2, b"INITIALIZING")]
    with pytest.raises(CacheStoreError):
        await MySQLStore.initialize_schema(**options(name), embedding_space=SPACE)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TRIGGER attacker AFTER INSERT ON semantix_entries FOR EACH ROW SET @effect=1",
        "CREATE PROCEDURE attacker() SELECT 1",
        "ALTER PROCEDURE semantix_verify SQL SECURITY INVOKER",
        "DROP PROCEDURE semantix_verify",
        "CALL semantix_verify('anything')",
    ],
)
async def test_runtime_has_only_fixed_verifier_capability(
    store_factory: StoreFactory,
    sql: str,
) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    with pytest.raises(CacheStoreError) as failure:
        await store._worker.run(lambda job: job.rows(sql))
    assert "attacker" not in str(failure.value)
    assert store._config.password.decode("utf8") not in str(failure.value)


async def test_minimal_setup_grants_and_definer_creation_privilege() -> None:
    name = await new_database()
    user = "p5_setup_" + uuid4().hex[:10] + "@検"
    password = uuid4().hex + "検証"
    await asyncio.to_thread(
        admin, "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (user, password)
    )
    await asyncio.to_thread(
        admin,
        f"GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,INDEX,REFERENCES,CREATE ROUTINE,EXECUTE,TRIGGER,EVENT ON `{name}`.* TO %s@'%%'",
        (user,),
    )
    await asyncio.to_thread(admin, "GRANT SET_ANY_DEFINER ON *.* TO %s@'%%'", (user,))
    config = options(name) | {
        "user": user,
        "password": password,
        "embedding_space": SPACE,
    }
    await MySQLStore.initialize_schema(**config)
    await asyncio.to_thread(
        admin, "REVOKE SET_ANY_DEFINER ON *.* FROM %s@'%%'", (user,)
    )
    # Registering/validating an existing schema performs no definer DDL.
    await MySQLStore.initialize_schema(**config)
    async with await MySQLStore.connect(**config) as store:
        assert await store.find_nearest((1, 0), namespace="default") is None
    assert sha256(schema.VERIFIER).digest() == schema.VERIFIER_CHECKSUM


@pytest.mark.parametrize("missing", ["SELECT", "TRIGGER", "EXECUTE", "EVENT"])
async def test_setup_without_complete_metadata_authority_refuses_before_ddl(
    missing: str,
) -> None:
    name = await new_database()
    user = "p5_setup_" + uuid4().hex[:20]
    password = uuid4().hex
    await asyncio.to_thread(
        admin, "CREATE USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL", (user, password)
    )
    grants = ",".join(
        privilege
        for privilege in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "INDEX",
            "REFERENCES",
            "CREATE ROUTINE",
            "EXECUTE",
            "TRIGGER",
            "EVENT",
        )
        if privilege != missing
    )
    await asyncio.to_thread(admin, f"GRANT {grants} ON `{name}`.* TO %s@'%%'", (user,))
    await asyncio.to_thread(admin, "GRANT SET_ANY_DEFINER ON *.* TO %s@'%%'", (user,))
    with pytest.raises(CacheStoreError, match="authoritative metadata privileges"):
        await MySQLStore.initialize_schema(
            **(options(name) | {"user": user, "password": password}),
            embedding_space=SPACE,
        )
    assert await asyncio.to_thread(admin, "SHOW TABLES", name=name) == []
    assert await asyncio.to_thread(
        admin,
        "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s",
        (name,),
        name=name,
    ) == [(0,)]
