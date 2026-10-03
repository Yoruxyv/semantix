from typing import cast

import pytest
from asyncpg.pool import Pool

from app.benchmark.infrastructure import database as evaluation_database
from app.cache.infrastructure import database as cache_database
from app.core.config import Settings
from app.infrastructure import lifecycle
from app.infrastructure.lifecycle import database_pool_lifespan


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def settings(
    *,
    cache_backend: str,
    evaluation_dataset_storage: str,
    evaluation_run_history_storage: str = "disabled",
) -> Settings:
    database_required = (
        cache_backend == "pgvector"
        or evaluation_dataset_storage == "postgres"
        or evaluation_run_history_storage == "postgres"
    )
    return Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "cache_backend": cache_backend,
            "evaluation_dataset_storage": evaluation_dataset_storage,
            "evaluation_run_history_storage": evaluation_run_history_storage,
            "evaluation_run_history_retention_days": 30,
            "evaluation_run_history_max_per_namespace": 100,
            "evaluation_run_history_cleanup_batch_size": 10,
            "database_url": (
                "postgresql://user:secret@database:5432/semantix"
                if database_required
                else None
            ),
            "allowed_origins": ["http://localhost:5173"],
        }
    )


@pytest.mark.asyncio
async def test_memory_and_session_mode_open_no_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_pool(*args: object, **kwargs: object) -> Pool:
        raise AssertionError("A session-only memory deployment must not open a pool")

    monkeypatch.setattr(lifecycle, "create_pool", unexpected_pool)

    async with database_pool_lifespan(
        settings(
            cache_backend="memory",
            evaluation_dataset_storage="session",
        )
    ) as pool:
        assert pool is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cache_backend", "evaluation_storage", "history_storage", "expected_migrations"),
    [
        ("memory", "postgres", "disabled", ["evaluation"]),
        ("memory", "session", "postgres", ["evaluation"]),
        ("pgvector", "session", "disabled", ["cache"]),
        ("pgvector", "postgres", "disabled", ["cache", "evaluation"]),
        ("pgvector", "session", "postgres", ["cache", "evaluation"]),
    ],
)
async def test_database_features_reuse_one_pool_and_apply_owned_migrations(
    monkeypatch: pytest.MonkeyPatch,
    cache_backend: str,
    evaluation_storage: str,
    history_storage: str,
    expected_migrations: list[str],
) -> None:
    fake_pool = FakePool()
    created = 0
    migrations: list[str] = []

    async def create_pool(*args: object, **kwargs: object) -> Pool:
        nonlocal created
        created += 1
        return cast(Pool, fake_pool)

    async def cache_migrations(pool: Pool) -> None:
        assert pool is cast(Pool, fake_pool)
        migrations.append("cache")

    async def evaluation_migrations(pool: Pool) -> None:
        assert pool is cast(Pool, fake_pool)
        migrations.append("evaluation")

    monkeypatch.setattr(lifecycle, "create_pool", create_pool)
    monkeypatch.setattr(
        cache_database,
        "apply_migrations",
        cache_migrations,
    )
    monkeypatch.setattr(
        evaluation_database,
        "apply_migrations",
        evaluation_migrations,
    )

    async with database_pool_lifespan(
        settings(
            cache_backend=cache_backend,
            evaluation_dataset_storage=evaluation_storage,
            evaluation_run_history_storage=history_storage,
        )
    ) as pool:
        assert pool is cast(Pool, fake_pool)

    assert created == 1
    assert migrations == expected_migrations
    assert fake_pool.closed is True
