"""Explicit privileged PostgreSQL setup command, separate from server runtime.

MigrationSettings reads required MIGRATION_DATABASE_URL and DATABASE_RUNTIME_ROLE
plus feature selections through BaseSettings environment sources. Its external
mode and feature-presence validator do not select ordinary server startup mode.
Fields/constraints remain in the model; runtime uses its separately supplied DSN.
"""

import asyncio
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.benchmark.infrastructure import database as evaluation_database
from app.cache.infrastructure import database as cache_database
from app.core.config import (
    CacheBackendName,
    CoordinationBackendName,
    EvaluationDatasetStorageMode,
    EvaluationRunHistoryStorageMode,
)
from app.core.exceptions import DatabaseStorageError
from app.infrastructure import coordination_database
from app.infrastructure.database import create_pool


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    migration_database_url: SecretStr
    database_runtime_role: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$",
    )
    database_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_command_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    cache_backend: CacheBackendName = "pgvector"
    cache_pgvector_schema: str = Field(
        default="semantix_cache", pattern=r"^[a-z_][a-z0-9_]{0,62}$"
    )
    cache_pgvector_table_prefix: str = Field(
        default="workbench_", pattern=r"^[a-z_][a-z0-9_]{0,44}$"
    )
    coordination_backend: CoordinationBackendName = "memory"
    evaluation_dataset_storage: EvaluationDatasetStorageMode = "session"
    evaluation_run_history_storage: EvaluationRunHistoryStorageMode = "disabled"
    database_migration_mode: Literal["external"] = "external"

    @model_validator(mode="after")
    def require_database_feature(self) -> "MigrationSettings":
        """Require at least one selected PostgreSQL feature before setup can run.

        This validates feature selection only, without connecting, checking authority or
        proving the required schema exists. Field defaults/constraints own other checks.

        Returns:
            The same settings object when a database feature is selected.

        Raises:
            ValueError: Cache, coordination, dataset and history selections need no PostgreSQL.
        """
        if (
            self.cache_backend != "pgvector"
            and self.coordination_backend != "postgres"
            and self.evaluation_dataset_storage != "postgres"
            and self.evaluation_run_history_storage != "postgres"
        ):
            raise ValueError(
                "The migration job requires pgvector cache, PostgreSQL "
                "coordination, or persistent evaluation storage"
            )
        return self


async def run() -> None:
    # Required fields are supplied by BaseSettings environment sources.
    """Own one migration pool and initialize only the selected PostgreSQL features.

    Resolve MigrationSettings before I/O, then open a one-connection pool using
    migration credentials. Initialize official cache schema when pgvector is chosen;
    apply/grant coordination when enabled; apply evaluation resources if either
    dataset/history storage is PostgreSQL and grant those table groups independently.
    This command does not initialize Redis or construct providers.

    Once pool creation succeeds, finally awaits pool.close without this command
    adding a close deadline/termination fallback. Cleanup failure or cancellation
    may replace setup failure. Earlier completed feature setup is not rolled back
    as a single cross-feature transaction. Script execution uses asyncio.run.
    """
    settings = MigrationSettings()  # pyright: ignore[reportCallIssue]
    pool = await create_pool(
        settings.migration_database_url.get_secret_value(),
        min_size=1,
        max_size=1,
        connect_timeout=settings.database_connect_timeout_seconds,
        command_timeout=settings.database_command_timeout_seconds,
        error_type=DatabaseStorageError,
    )
    try:
        if settings.cache_backend == "pgvector":
            await cache_database.initialize_official_schema(
                pool,
                schema=settings.cache_pgvector_schema,
                table_prefix=settings.cache_pgvector_table_prefix,
                runtime_role=settings.database_runtime_role,
            )
        if settings.coordination_backend == "postgres":
            await coordination_database.apply_migrations(pool)
            await coordination_database.grant_runtime_privileges(
                pool, settings.database_runtime_role
            )
        if (
            settings.evaluation_dataset_storage == "postgres"
            or settings.evaluation_run_history_storage == "postgres"
        ):
            await evaluation_database.apply_migrations(pool)
        if settings.evaluation_dataset_storage == "postgres":
            await evaluation_database.grant_runtime_privileges(
                pool,
                settings.database_runtime_role,
            )

        if settings.evaluation_run_history_storage == "postgres":
            await evaluation_database.grant_run_history_runtime_privileges(
                pool,
                settings.database_runtime_role,
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
