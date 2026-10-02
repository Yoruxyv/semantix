from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from typing import Protocol

import asyncpg
from asyncpg import Connection
from asyncpg.pool import Pool, PoolConnectionProxy

from app.core.exceptions import AppError, DatabaseStorageError

logger = logging.getLogger(__name__)

MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
MIGRATION_LOCK_ID = 7_374_772_830_148_015_240
ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
TABLE_NAME = re.compile(r"^semantix\.[a-z][a-z0-9_]*$")
MIGRATION_BOOTSTRAP_SQL = """
CREATE SCHEMA IF NOT EXISTS semantix;
CREATE TABLE IF NOT EXISTS semantix.schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE semantix.schema_migrations
    ADD COLUMN IF NOT EXISTS checksum TEXT;
"""

StorageErrorType = type[AppError]


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str

    @property
    def checksum(self) -> str:
        return sha256(self.sql.encode("utf-8")).hexdigest()


class LegacyMigrationValidator(Protocol):
    async def __call__(
        self,
        connection: (Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record]),
        migration: Migration,
    ) -> bool: ...


def load_packaged_migrations(
    packages: Iterable[str],
    *,
    label: str,
    error_type: StorageErrorType = DatabaseStorageError,
) -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    for package in packages:
        for resource in files(package).iterdir():
            match = MIGRATION_NAME.fullmatch(resource.name)
            if match is None:
                continue
            migrations.append(
                Migration(
                    version=match.group("version"),
                    sql=resource.read_text(encoding="utf-8"),
                )
            )
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    versions = [migration.version for migration in ordered]
    if not ordered:
        raise error_type(f"No {label.lower()} migrations were packaged")
    if len(versions) != len(set(versions)):
        raise error_type(f"{label} migration versions must be unique")
    return ordered


async def create_pool(
    dsn: str,
    *,
    min_size: int,
    max_size: int,
    connect_timeout: float,
    command_timeout: float,
    error_type: StorageErrorType = DatabaseStorageError,
    error_detail: str = "Could not connect to the configured PostgreSQL database",
) -> Pool:
    try:
        return await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=connect_timeout,
            command_timeout=command_timeout,
        )
    except (OSError, asyncpg.PostgresError) as error:
        raise error_type(error_detail) from error


async def _verify_applied_migration(
    connection: Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record],
    migration: Migration,
    recorded_checksum: str | None,
    *,
    label: str,
    error_type: StorageErrorType,
    legacy_validator: LegacyMigrationValidator | None,
) -> None:
    if recorded_checksum == migration.checksum:
        return
    if recorded_checksum is not None:
        raise error_type(f"{label} migration {migration.version} checksum mismatch")
    if legacy_validator is None or not await legacy_validator(connection, migration):
        raise error_type(
            f"{label} migration {migration.version} has no checksum "
            "and its released schema could not be verified"
        )
    await connection.execute(
        """
        UPDATE semantix.schema_migrations
        SET checksum = $2
        WHERE version = $1 AND checksum IS NULL
        """,
        migration.version,
        migration.checksum,
    )
    logger.info(
        "Backfilled database migration checksum label=%s version=%s",
        label,
        migration.version,
    )


async def apply_migrations(
    pool: Pool,
    migrations: Sequence[Migration],
    *,
    label: str,
    error_type: StorageErrorType = DatabaseStorageError,
    bootstrap_statements: Sequence[str] = (),
    legacy_validators: Mapping[str, LegacyMigrationValidator] | None = None,
) -> None:
    validators = legacy_validators or {}
    try:
        async with pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_ID)
            try:
                await connection.execute(MIGRATION_BOOTSTRAP_SQL)
                for statement in bootstrap_statements:
                    await connection.execute(statement)
                applied_rows = await connection.fetch(
                    "SELECT version, checksum FROM semantix.schema_migrations"
                )
                applied = {
                    str(row["version"]): (
                        None if row["checksum"] is None else str(row["checksum"])
                    )
                    for row in applied_rows
                }
                for migration in migrations:
                    if migration.version in applied:
                        await _verify_applied_migration(
                            connection,
                            migration,
                            applied[migration.version],
                            label=label,
                            error_type=error_type,
                            legacy_validator=validators.get(migration.version),
                        )
                        continue
                    async with connection.transaction():
                        await connection.execute(migration.sql)
                        await connection.execute(
                            """
                            INSERT INTO semantix.schema_migrations (
                                version,
                                checksum
                            )
                            VALUES ($1, $2)
                            """,
                            migration.version,
                            migration.checksum,
                        )
                    logger.info(
                        "Applied database migration label=%s version=%s",
                        label,
                        migration.version,
                    )
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock($1)",
                    MIGRATION_LOCK_ID,
                )
    except AppError:
        raise
    except (OSError, asyncpg.PostgresError) as error:
        raise error_type(f"Could not initialize the {label.lower()} schema") from error


async def grant_runtime_privileges(
    pool: Pool,
    runtime_role: str,
    tables: Sequence[str],
    *,
    error_type: StorageErrorType = DatabaseStorageError,
) -> None:
    if ROLE_NAME.fullmatch(runtime_role) is None:
        raise error_type("DATABASE_RUNTIME_ROLE is not a valid PostgreSQL role")
    if not tables or any(TABLE_NAME.fullmatch(table) is None for table in tables):
        raise error_type("Runtime privilege table allowlist is invalid")
    quoted_role = '"' + runtime_role.replace('"', '""') + '"'
    statements = (
        f"GRANT USAGE ON SCHEMA semantix TO {quoted_role}",
        (
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            f"{', '.join(tables)} TO {quoted_role}"
        ),
    )
    try:
        async with pool.acquire() as connection, connection.transaction():
            for statement in statements:
                await connection.execute(statement)
    except AppError:
        raise
    except (OSError, asyncpg.PostgresError) as error:
        raise error_type("Could not grant runtime database privileges") from error
