from asyncpg.pool import Pool

from app.core.exceptions import CoordinationStorageError
from app.infrastructure import database
from app.infrastructure.database import Migration

MIGRATION_PACKAGE = "app.infrastructure.migrations"
COORDINATION_TABLES = (
    "semantix.rate_limit_buckets",
    "semantix.authentication_attempts",
    "semantix.cache_threshold",
)


def load_migrations() -> tuple[Migration, ...]:
    return database.load_packaged_migrations(
        (MIGRATION_PACKAGE,),
        label="Coordination database",
        error_type=CoordinationStorageError,
    )


async def apply_migrations(pool: Pool) -> None:
    await database.apply_migrations(
        pool,
        load_migrations(),
        label="Coordination database",
        error_type=CoordinationStorageError,
    )


async def grant_runtime_privileges(pool: Pool, runtime_role: str) -> None:
    await database.grant_runtime_privileges(
        pool,
        runtime_role,
        COORDINATION_TABLES,
        error_type=CoordinationStorageError,
    )
