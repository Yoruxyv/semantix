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
    coordination_backend: CoordinationBackendName = "memory"
    evaluation_dataset_storage: EvaluationDatasetStorageMode = "session"
    evaluation_run_history_storage: EvaluationRunHistoryStorageMode = "disabled"
    database_migration_mode: Literal["external"] = "external"

    @model_validator(mode="after")
    def require_database_feature(self) -> "MigrationSettings":
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
    settings = MigrationSettings()
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
            await cache_database.apply_migrations(pool)
            await cache_database.grant_runtime_privileges(
                pool,
                settings.database_runtime_role,
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
