import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
from asyncpg.pool import Pool

from app.benchmark.infrastructure.database import apply_migrations
from app.benchmark.infrastructure.postgres_history_repository import (
    PostgresEvaluationRunHistoryRepository,
)
from tests.benchmark.history_support import make_history_record

pytestmark = pytest.mark.pgvector


@pytest.fixture
async def history_pool() -> AsyncIterator[Pool]:
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=4,
    )

    async with pool.acquire() as connection:
        await connection.execute("DROP SCHEMA IF EXISTS semantix CASCADE")

    try:
        yield pool
    finally:
        await pool.close()


def repository(pool: Pool) -> PostgresEvaluationRunHistoryRepository:
    return PostgresEvaluationRunHistoryRepository(
        pool,
        retention_days=30,
        max_per_namespace=100,
        cleanup_batch_size=10,
    )


@pytest.mark.asyncio
async def test_history_list_is_paginated_namespace_scoped_and_newest_first(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    history = repository(history_pool)
    base = datetime.now(UTC) - timedelta(seconds=10)

    oldest = make_history_record(
        run_id=f"{1:032x}",
        namespace="tenant-a",
        completed_at=base,
    )
    newest = make_history_record(
        run_id=f"{2:032x}",
        namespace="tenant-a",
        completed_at=base + timedelta(seconds=1),
    )
    foreign = make_history_record(
        run_id=f"{3:032x}",
        namespace="tenant-b",
        completed_at=base + timedelta(seconds=2),
    )

    for record in (oldest, newest, foreign):
        await history.persist_terminal_run(record)

    first_page = await history.list_runs(
        namespace="tenant-a",
        offset=0,
        limit=1,
    )
    second_page = await history.list_runs(
        namespace="tenant-a",
        offset=1,
        limit=1,
    )
    global_page = await history.list_runs(
        namespace=None,
        offset=0,
        limit=10,
    )

    assert first_page.total == 2
    assert [item.context.run_id for item in first_page.items] == [newest.context.run_id]
    assert [item.context.run_id for item in second_page.items] == [
        oldest.context.run_id
    ]
    assert global_page.total == 3


@pytest.mark.asyncio
async def test_history_detail_enforces_namespace_scope_and_loads_thresholds(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    history = repository(history_pool)
    record = make_history_record(namespace="tenant-a")

    await history.persist_terminal_run(record)

    denied = await history.get_run(
        record.context.run_id,
        authorized_namespaces=frozenset({"tenant-b"}),
    )
    allowed = await history.get_run(
        record.context.run_id,
        authorized_namespaces=frozenset({"tenant-a"}),
    )
    global_read = await history.get_run(
        record.context.run_id,
        authorized_namespaces=None,
    )

    assert denied is None
    assert allowed is not None
    assert allowed.record.context.run_id == record.context.run_id
    assert allowed.record.context.history_namespace == "tenant-a"
    assert allowed.record.terminal_state == "completed"
    assert allowed.record.threshold_evaluations == record.threshold_evaluations
    assert global_read is not None


@pytest.mark.asyncio
async def test_history_delete_is_namespace_scoped_and_cascades_thresholds(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    history = repository(history_pool)
    record = make_history_record(namespace="tenant-a")

    await history.persist_terminal_run(record)

    assert not await history.delete_run(
        record.context.run_id,
        namespace="tenant-b",
    )

    assert await history.delete_run(
        record.context.run_id,
        namespace="tenant-a",
    )

    async with history_pool.acquire() as connection:
        run_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_runs
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )
        threshold_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_run_thresholds
            WHERE run_id = $1
            """,
            UUID(record.context.run_id),
        )

    assert run_count == 0
    assert threshold_count == 0


@pytest.mark.asyncio
async def test_history_detail_reconstructs_failed_terminal_evidence(
    history_pool: Pool,
) -> None:
    await apply_migrations(history_pool)
    history = repository(history_pool)
    record = make_history_record(
        namespace="tenant-failed",
        terminal_state="failed",
    )

    await history.persist_terminal_run(record)
    retained = await history.get_run(
        record.context.run_id,
        authorized_namespaces=frozenset({"tenant-failed"}),
    )

    assert retained is not None
    assert retained.record.terminal_state == "failed"
    assert retained.record.metrics is None
    assert retained.record.threshold_evaluations == ()
    assert retained.record.failure_code == "internal_error"
    assert retained.record.safe_failure_detail is None
