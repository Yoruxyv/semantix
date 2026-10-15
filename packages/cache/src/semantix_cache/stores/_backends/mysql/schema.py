"""Explicit MySQL DDL readiness and canonical structural catalog validation."""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from hashlib import sha256
from importlib.resources import files
from typing import Any

from ....errors import CacheStoreError
from .worker import Job

OWNER = b"semantix-cache:mysql:v1"
MIGRATION = (
    files("semantix_cache.stores._backends.mysql.migrations")
    .joinpath("0001_cache.sql")
    .read_bytes()
)
CHECKSUM = sha256(MIGRATION).digest()
STATEMENTS = tuple(
    part.strip() for part in MIGRATION.decode("utf8").split(";") if part.strip()
)
VERIFIER = (
    files("semantix_cache.stores._backends.mysql.migrations")
    .joinpath("0002_verifier.sql")
    .read_bytes()
)
VERIFIER_SQL = VERIFIER.decode("utf8").strip().removesuffix(";")
VERIFIER_CHECKSUM = sha256(VERIFIER).digest()
VERIFIER_BODY = VERIFIER_SQL[VERIFIER_SQL.index("\nSELECT 2,") + 1 :]
VERIFIER_BODY_CHECKSUM = sha256(VERIFIER_BODY.encode("utf8")).hexdigest()
EXPECTED = json.loads(
    files("semantix_cache.stores._backends.mysql.migrations")
    .joinpath("0001_shape.json")
    .read_text(encoding="utf8")
)
NOW = "TIMESTAMPDIFF(MICROSECOND, CAST('1970-01-01 00:00:00.000000' AS DATETIME(6)), UTC_TIMESTAMP(6))"

CATALOG = (
    "SELECT TABLE_NAME,TABLE_TYPE,ENGINE,ROW_FORMAT,TABLE_COLLATION,CREATE_OPTIONS FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
    "SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,CHARACTER_SET_NAME,COLLATION_NAME,GENERATION_EXPRESSION FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION",
    "SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,COLLATION,SUB_PART,INDEX_TYPE,NULLABLE,EXPRESSION,IS_VISIBLE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX",
    "SELECT tc.TABLE_NAME,tc.CONSTRAINT_NAME,tc.CONSTRAINT_TYPE,tc.ENFORCED,cc.CHECK_CLAUSE FROM information_schema.TABLE_CONSTRAINTS tc LEFT JOIN information_schema.CHECK_CONSTRAINTS cc ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME WHERE tc.CONSTRAINT_SCHEMA=%s ORDER BY tc.TABLE_NAME,tc.CONSTRAINT_NAME",
    "SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,ORDINAL_POSITION,REFERENCED_TABLE_SCHEMA,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION",
    "SELECT TABLE_NAME,CONSTRAINT_NAME,UNIQUE_CONSTRAINT_NAME,MATCH_OPTION,UPDATE_RULE,DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=%s ORDER BY TABLE_NAME,CONSTRAINT_NAME",
    "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s ORDER BY TRIGGER_NAME",
)


def shape(job: Job) -> list[list[list[Any]]]:
    database = job.owner.config.database
    result: list[list[list[Any]]] = []
    for sql in CATALOG:
        rows = job.rows(sql, (database,))
        result.append(
            [
                ["$DATABASE" if item == database else item for item in row]
                for row in rows
            ]
        )
    return result


def validate(job: Job) -> None:
    if job.rows(
        "SELECT version,owner,checksum,state,codec FROM semantix_schema_migrations ORDER BY version LIMIT 3"
    ) != [
        (1, OWNER, CHECKSUM, b"READY", 1),
        (2, OWNER, VERIFIER_CHECKSUM, b"READY", 1),
    ]:
        raise CacheStoreError(
            "MySQL schema ownership, readiness or migration checksum is invalid"
        )
    # Invoker catalogs hide foreign objects; the fixed routine checks as its definer.
    if job.rows("CALL semantix_verify()") != [(2, 1, VERIFIER_BODY_CHECKSUM)]:
        raise CacheStoreError("MySQL schema shape or verifier is invalid")


def session(job: Job) -> None:
    server = job.rows(
        "SELECT @@version,@@version_comment,@@global.require_secure_transport,@@global.read_only,@@global.super_read_only,@@global.innodb_flush_log_at_trx_commit,@@global.log_bin,@@global.sync_binlog,@@global.binlog_format,@@global.max_allowed_packet"
    )[0]
    (
        version,
        comment,
        secure,
        readonly,
        super_readonly,
        flush,
        log_bin,
        sync_binlog,
        binlog_format,
        packet,
    ) = server
    if (
        not version.startswith("8.4.")
        or "Community" not in comment
        or secure != 1
        or readonly != 0
        or super_readonly != 0
        or flush != 1
        or (log_bin and (sync_binlog != 1 or binlog_format != "ROW"))
        or packet < 4 * 1024 * 1024
    ):
        raise CacheStoreError(
            "MySQL server is outside the verified single-primary InnoDB support boundary"
        )
    if not job.rows("SHOW SESSION STATUS LIKE 'Ssl_cipher'")[0][1]:
        raise CacheStoreError("MySQL verified TLS is required")
    job.rows(
        "SET SESSION time_zone='+00:00',collation_connection='utf8mb4_bin',sql_mode='STRICT_ALL_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION',transaction_isolation='READ-COMMITTED',innodb_lock_wait_timeout=1,lock_wait_timeout=1,max_execution_time=1000,net_read_timeout=1,net_write_timeout=1"
    )
    settings = job.rows(
        "SELECT @@session.time_zone,@@session.sql_mode,@@session.transaction_isolation,@@session.transaction_read_only,@@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout,@@session.max_execution_time,@@session.net_read_timeout,@@session.net_write_timeout,@@session.character_set_connection,@@session.collation_connection"
    )[0]
    if (
        settings[0] != "+00:00"
        or set(settings[1].split(","))
        != {
            "STRICT_ALL_TABLES",
            "ERROR_FOR_DIVISION_BY_ZERO",
            "NO_ZERO_DATE",
            "NO_ZERO_IN_DATE",
            "NO_ENGINE_SUBSTITUTION",
        }
        or settings[2:]
        != ("READ-COMMITTED", 0, 1, 1, 1000, 1, 1, "utf8mb4", "utf8mb4_bin")
    ):
        raise CacheStoreError("MySQL session safety settings are unavailable")


@contextmanager
def initialize(job: Job) -> Generator[None, None, None]:
    session(job)
    database = job.owner.config.database
    # Setup must itself see all objects before it can claim an empty database.
    if job.rows(
        "SELECT COUNT(DISTINCT PRIVILEGE_TYPE) FROM (SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES WHERE TABLE_SCHEMA=DATABASE() AND GRANTEE=CONCAT(QUOTE(LEFT(CURRENT_USER(),CHAR_LENGTH(CURRENT_USER())-CHAR_LENGTH(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))-1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))) UNION ALL SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES WHERE GRANTEE=CONCAT(QUOTE(LEFT(CURRENT_USER(),CHAR_LENGTH(CURRENT_USER())-CHAR_LENGTH(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))-1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))) p WHERE PRIVILEGE_TYPE IN ('SELECT','TRIGGER','EXECUTE','EVENT')"
    ) != [(4,)]:
        raise CacheStoreError("MySQL setup requires authoritative metadata privileges")
    lock = "semantix:" + sha256(database.encode("ascii")).hexdigest()[:48]
    if job.rows("SELECT GET_LOCK(%s,0)", (lock,)) != [(1,)]:
        raise CacheStoreError("MySQL schema setup is already in progress")
    try:
        objects = job.rows(CATALOG[0], (database,))
        if not objects:
            if job.rows(
                "SELECT (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE())+(SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE())"
            ) != [(0,)]:
                raise CacheStoreError(
                    "MySQL schema shape contains foreign stored objects"
                )
            job.rows(STATEMENTS[0])
            job.rows(
                "INSERT INTO semantix_schema_migrations VALUES(1,%s,%s,%s,1)",
                (OWNER, CHECKSUM, b"INITIALIZING"),
            )
            for statement in STATEMENTS[1:]:
                job.rows(statement)
            job.rows(
                "INSERT INTO semantix_schema_migrations VALUES(2,%s,%s,%s,1)",
                (OWNER, VERIFIER_CHECKSUM, b"INITIALIZING"),
            )
            job.rows(VERIFIER_SQL)
            if shape(job) != EXPECTED:
                raise CacheStoreError("MySQL initialized schema shape is invalid")
            with job.transaction(write=True):
                job.rows(
                    "UPDATE semantix_schema_migrations SET state=%s WHERE version IN (1,2) AND state=%s",
                    (b"READY", b"INITIALIZING"),
                )
                validate(job)
        validate(job)
        yield
    finally:
        # A disconnected session releases its locks; preserve its primary error.
        connection = job.connection
        if connection.open:
            with connection.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock,))
                if cursor.fetchone() != (1,):
                    raise CacheStoreError("MySQL schema setup lock release failed")
        elif sys.exception() is None:
            raise CacheStoreError("MySQL schema setup connection ended unexpectedly")
