import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from asyncpg.pool import Pool

from app.benchmark.domain.validation import (
    ValidatedImportedDataset,
    validate_imported_dataset,
)
from app.benchmark.infrastructure.database import (
    apply_migrations,
    grant_run_history_runtime_privileges,
    grant_runtime_privileges,
    load_migrations,
)
from app.benchmark.infrastructure.postgres_repository import (
    PostgresEvaluationDatasetRepository,
)
from app.cache.infrastructure.database import (
    apply_migrations as apply_cache_migrations,
)
from app.cache.infrastructure.database import (
    load_migrations as load_cache_migrations,
)
from app.core.exceptions import (
    CacheStorageError,
    EvaluationDatasetCapacityError,
    EvaluationDatasetStorageError,
)

pytestmark = pytest.mark.pgvector


@pytest.fixture
async def evaluation_pool() -> AsyncIterator[Pool]:
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


def definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "PostgreSQL synthetic set",
        "description": "Synthetic migration and repository evidence.",
        "cases": [
            {
                "case_id": "seed",
                "prompt": "Synthetic PostgreSQL seed",
                "expected_cache_hit": False,
                "category": "storage",
            },
            {
                "case_id": "repeat",
                "prompt": "Synthetic PostgreSQL seed",
                "expected_cache_hit": True,
                "expected_match_case_id": "seed",
                "category": "storage",
                "note": "References an earlier case.",
            },
        ],
    }


def validated() -> ValidatedImportedDataset:
    return validate_imported_dataset(
        definition(),
        repetitions=1,
        threshold_count=2,
        max_cases=50,
        max_decoded_bytes=49_152,
        max_workload_queries=250,
    )


@pytest.mark.asyncio
async def test_evaluation_migration_is_fresh_idempotent_and_concurrent(
    evaluation_pool: Pool,
) -> None:
    await asyncio.gather(
        apply_migrations(evaluation_pool),
        apply_migrations(evaluation_pool),
    )
    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT version, checksum
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )
        tables = await connection.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'semantix'
            ORDER BY tablename
            """
        )

    migrations = load_migrations()

    assert [migration.version for migration in migrations] == [
        "0002",
        "0003",
    ]

    assert [(row["version"], row["checksum"]) for row in rows] == [
        (migration.version, migration.checksum) for migration in migrations
    ]

    assert [row["tablename"] for row in tables] == [
        "evaluation_dataset_cases",
        "evaluation_datasets",
        "evaluation_run_thresholds",
        "evaluation_runs",
        "schema_migrations",
    ]


@pytest.mark.asyncio
async def test_evaluation_migration_upgrades_cache_schema_additively(
    evaluation_pool: Pool,
) -> None:
    await apply_cache_migrations(evaluation_pool)
    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        versions = await connection.fetch(
            """
            SELECT version
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )
        cache_table = await connection.fetchval(
            "SELECT to_regclass('semantix.cache_entries') IS NOT NULL"
        )
        dataset_table = await connection.fetchval(
            "SELECT to_regclass('semantix.evaluation_datasets') IS NOT NULL"
        )
        history_table = await connection.fetchval(
            "SELECT to_regclass('semantix.evaluation_runs') IS NOT NULL"
        )
        history_threshold_table = await connection.fetchval(
            "SELECT to_regclass('semantix.evaluation_run_thresholds') IS NOT NULL"
        )

    assert [row["version"] for row in versions] == [
        "0001",
        "0002",
        "0003",
    ]
    assert cache_table is True
    assert dataset_table is True
    assert history_table is True
    assert history_threshold_table is True


@pytest.mark.asyncio
async def test_cache_migration_can_follow_evaluation_only_install(
    evaluation_pool: Pool,
) -> None:
    evaluation_migrations = load_migrations()
    cache_migration = load_cache_migrations()[0]

    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        evaluation_only_versions = await connection.fetch(
            """
            SELECT version, checksum
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )
        evaluation_table = await connection.fetchval(
            "SELECT to_regclass('semantix.evaluation_datasets') IS NOT NULL"
        )
        history_table = await connection.fetchval(
            "SELECT to_regclass('semantix.evaluation_runs') IS NOT NULL"
        )
        cache_table = await connection.fetchval(
            "SELECT to_regclass('semantix.cache_entries') IS NOT NULL"
        )

    assert [(row["version"], row["checksum"]) for row in evaluation_only_versions] == [
        (migration.version, migration.checksum) for migration in evaluation_migrations
    ]

    assert evaluation_table is True
    assert history_table is True
    assert cache_table is False

    await apply_cache_migrations(evaluation_pool)
    await apply_cache_migrations(evaluation_pool)
    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        combined_versions = await connection.fetch(
            """
            SELECT version, checksum
            FROM semantix.schema_migrations
            ORDER BY version
            """
        )
        relations = await connection.fetch(
            """
            SELECT relation, to_regclass(relation) IS NOT NULL AS exists
            FROM unnest($1::text[]) AS expected(relation)
            ORDER BY relation
            """,
            [
                "semantix.cache_entries",
                "semantix.cache_namespace_counters",
                "semantix.evaluation_dataset_cases",
                "semantix.evaluation_datasets",
                "semantix.evaluation_run_thresholds",
                "semantix.evaluation_runs",
                "semantix.schema_migrations",
            ],
        )

    assert [(row["version"], row["checksum"]) for row in combined_versions] == [
        ("0001", cache_migration.checksum),
        *[
            (migration.version, migration.checksum)
            for migration in evaluation_migrations
        ],
    ]

    assert all(row["exists"] for row in relations)

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = $1
            WHERE version = '0001'
            """,
            "0" * 64,
        )

    with pytest.raises(
        CacheStorageError,
        match="0001 checksum mismatch",
    ):
        await apply_cache_migrations(evaluation_pool)


@pytest.mark.asyncio
async def test_evaluation_migration_checksum_mismatch_is_rejected(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = $1
            WHERE version = '0002'
            """,
            "0" * 64,
        )

    with pytest.raises(
        EvaluationDatasetStorageError,
        match="0002 checksum mismatch",
    ):
        await apply_migrations(evaluation_pool)


@pytest.mark.asyncio
async def test_evaluation_history_migration_checksum_mismatch_is_rejected(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.schema_migrations
            SET checksum = $1
            WHERE version = '0003'
            """,
            "0" * 64,
        )

    with pytest.raises(
        EvaluationDatasetStorageError,
        match="0003 checksum mismatch",
    ):
        await apply_migrations(evaluation_pool)


@pytest.mark.asyncio
async def test_runtime_role_receives_only_required_evaluation_privileges(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    role_name = f"semantix_eval_{uuid4().hex[:12]}"
    password = uuid4().hex
    database_url = os.environ["PGVECTOR_TEST_DATABASE_URL"]
    dataset_id = uuid4()

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{password}'"
        )

    try:
        await grant_runtime_privileges(
            evaluation_pool,
            role_name,
        )

        runtime = await asyncpg.connect(
            database_url,
            user=role_name,
            password=password,
        )

        try:
            await runtime.execute(
                """
                INSERT INTO semantix.evaluation_datasets (
                    dataset_id,
                    namespace,
                    name,
                    source_type,
                    schema_version,
                    digest,
                    case_count,
                    decoded_bytes,
                    created_at,
                    expires_at
                )
                VALUES (
                    $1,
                    'runtime-role',
                    'Runtime role evidence',
                    'imported',
                    1,
                    $2,
                    1,
                    64,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP + INTERVAL '1 day'
                )
                """,
                dataset_id,
                "f" * 64,
            )

            await runtime.execute(
                """
                INSERT INTO semantix.evaluation_dataset_cases (
                    dataset_id,
                    sequence,
                    case_id,
                    prompt,
                    expected_cache_hit,
                    category
                )
                VALUES (
                    $1,
                    1,
                    'case',
                    'Synthetic role prompt',
                    FALSE,
                    'role'
                )
                """,
                dataset_id,
            )

            assert (
                await runtime.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM semantix.evaluation_dataset_cases
                    WHERE dataset_id = $1
                    """,
                    dataset_id,
                )
                == 1
            )

            assert (
                await runtime.fetchval(
                    """
                    SELECT has_table_privilege(
                        current_user,
                        'semantix.evaluation_runs',
                        'SELECT'
                    )
                    """
                )
                is False
            )

            assert (
                await runtime.fetchval(
                    """
                    SELECT has_table_privilege(
                        current_user,
                        'semantix.evaluation_run_thresholds',
                        'SELECT'
                    )
                    """
                )
                is False
            )

            await runtime.execute(
                """
                DELETE FROM semantix.evaluation_datasets
                WHERE dataset_id = $1
                """,
                dataset_id,
            )
        finally:
            await runtime.close()

    finally:
        async with evaluation_pool.acquire() as connection:
            await connection.execute(f'DROP OWNED BY "{role_name}"')
            await connection.execute(f'DROP ROLE IF EXISTS "{role_name}"')


@pytest.mark.asyncio
async def test_runtime_role_receives_only_history_privileges(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    role_name = f"semantix_history_{uuid4().hex[:12]}"
    password = uuid4().hex
    database_url = os.environ["PGVECTOR_TEST_DATABASE_URL"]

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{password}'"
        )

    try:
        await grant_run_history_runtime_privileges(
            evaluation_pool,
            role_name,
        )

        runtime = await asyncpg.connect(
            database_url,
            user=role_name,
            password=password,
        )

        try:
            for table in (
                "semantix.evaluation_runs",
                "semantix.evaluation_run_thresholds",
            ):
                for privilege in (
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                ):
                    assert (
                        await runtime.fetchval(
                            """
                            SELECT has_table_privilege(
                                current_user,
                                $1,
                                $2
                            )
                            """,
                            table,
                            privilege,
                        )
                        is True
                    )

            for table in (
                "semantix.evaluation_datasets",
                "semantix.evaluation_dataset_cases",
            ):
                for privilege in (
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                ):
                    assert (
                        await runtime.fetchval(
                            """
                            SELECT has_table_privilege(
                                current_user,
                                $1,
                                $2
                            )
                            """,
                            table,
                            privilege,
                        )
                        is False
                    )
        finally:
            await runtime.close()

    finally:
        async with evaluation_pool.acquire() as connection:
            await connection.execute(f'DROP OWNED BY "{role_name}"')
            await connection.execute(f'DROP ROLE IF EXISTS "{role_name}"')


@pytest.mark.asyncio
async def test_repository_preserves_order_scope_duplicates_and_cascade(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    repository = PostgresEvaluationDatasetRepository(
        evaluation_pool,
        max_per_namespace=10,
        cleanup_batch_size=10,
    )

    first = await repository.create_dataset(
        namespace="tenant-a",
        validated=validated(),
        retention_days=30,
    )

    second = await repository.create_dataset(
        namespace="tenant-a",
        validated=validated(),
        retention_days=30,
    )

    assert first.metadata.dataset_id != second.metadata.dataset_id
    assert first.metadata.digest == second.metadata.digest

    page = await repository.list_datasets(
        namespace="tenant-a",
        offset=0,
        limit=10,
    )

    detail = await repository.get_dataset(
        first.metadata.dataset_id,
        authorized_namespaces=frozenset({"tenant-a"}),
    )

    foreign = await repository.get_dataset(
        first.metadata.dataset_id,
        authorized_namespaces=frozenset({"tenant-b"}),
    )

    assert page.total == 2
    assert detail is not None
    assert [item.case_id for item in detail.dataset.cases] == [
        "seed",
        "repeat",
    ]
    assert foreign is None

    assert (
        await repository.delete_dataset(
            first.metadata.dataset_id,
            namespace="tenant-b",
        )
        is False
    )

    assert (
        await repository.delete_dataset(
            first.metadata.dataset_id,
            namespace="tenant-a",
        )
        is True
    )

    async with evaluation_pool.acquire() as connection:
        remaining_cases = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM semantix.evaluation_dataset_cases
            WHERE dataset_id = $1
            """,
            first.metadata.dataset_id,
        )

    assert remaining_cases == 0


@pytest.mark.asyncio
async def test_repository_enforces_capacity_and_bounded_expiry_cleanup(
    evaluation_pool: Pool,
) -> None:
    await apply_migrations(evaluation_pool)

    repository = PostgresEvaluationDatasetRepository(
        evaluation_pool,
        max_per_namespace=1,
        cleanup_batch_size=1,
    )

    expired = await repository.create_dataset(
        namespace="tenant-a",
        validated=validated(),
        retention_days=1,
    )

    async with evaluation_pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE semantix.evaluation_datasets
            SET created_at = $1,
                expires_at = $2
            WHERE dataset_id = $3
            """,
            datetime.now(UTC) - timedelta(days=2),
            datetime.now(UTC) - timedelta(days=1),
            expired.metadata.dataset_id,
        )

    replacement = await repository.create_dataset(
        namespace="tenant-a",
        validated=validated(),
        retention_days=30,
    )

    with pytest.raises(EvaluationDatasetCapacityError):
        await repository.create_dataset(
            namespace="tenant-a",
            validated=validated(),
            retention_days=30,
        )

    assert replacement.metadata.dataset_id != expired.metadata.dataset_id

    assert (
        await repository.get_dataset(
            expired.metadata.dataset_id,
            authorized_namespaces=frozenset({"tenant-a"}),
        )
        is None
    )
