"""Bind evaluation migrations and runtime table grants to shared database machinery.

Packaged migrations 0002/0003 create dataset/case and run/threshold table groups in
the server's semantix schema, distinct from the official embedded cache store.
Dataset persistence and run-history enablement/grants remain separate even though
the evaluation migration package contains both. Callers supply the shared pool
and migration/grant authority; these wrappers neither create nor close that pool.
Explicit setup and explicitly selected development auto-migration mode can invoke
migrations. Normal runtime repository construction does not perform privileged DDL.
"""

from asyncpg.pool import Pool

from app.core.exceptions import (
    EvaluationDatasetStorageError,
    EvaluationRunHistoryStorageError,
)
from app.infrastructure import database as shared_database
from app.infrastructure.database import Migration

MIGRATION_PACKAGE = "app.benchmark.infrastructure.migrations"

EVALUATION_DATASET_TABLES = (
    "semantix.evaluation_datasets",
    "semantix.evaluation_dataset_cases",
)

EVALUATION_RUN_HISTORY_TABLES = (
    "semantix.evaluation_runs",
    "semantix.evaluation_run_thresholds",
)


def load_migrations() -> tuple[Migration, ...]:
    """Load ordered packaged evaluation SQL without executing it or opening a database.

    Returns:
        Shared Migration objects for the dataset and run-history resources. The
        shared loader orders versions; the runner verifies their SQL checksums.

    Raises:
        EvaluationDatasetStorageError: Shared loading finds no migrations or
            duplicate versions. Resource-loading errors are not universally mapped.
    """
    return shared_database.load_packaged_migrations(
        (MIGRATION_PACKAGE,),
        label="Evaluation dataset database",
        error_type=EvaluationDatasetStorageError,
    )


async def apply_migrations(pool: Pool) -> None:
    """Apply evaluation resources through the shared locked, checksum-aware runner.

    The shared runner serializes migration work and applies each pending migration
    with its ledger entry in a transaction, not one transaction for the whole set.
    Existing checksum mismatches fail rather than silently adopting changed SQL.

    Args:
        pool: Borrowed application-supplied pool with migration authority.

    Raises:
        EvaluationDatasetStorageError: Declared migration/handled database failure,
            including run-history migrations under this package's existing label.
    """
    await shared_database.apply_migrations(
        pool,
        load_migrations(),
        label="Evaluation dataset database",
        error_type=EvaluationDatasetStorageError,
    )


async def grant_runtime_privileges(
    pool: Pool,
    runtime_role: str,
) -> None:
    """Grant schema usage and DML on dataset/case tables through the shared allowlist.

    Args:
        pool: Borrowed pool whose connection can grant the requested privileges.
        runtime_role: Existing PostgreSQL role validated/quoted by the shared helper.

    Raises:
        EvaluationDatasetStorageError: Role/table validation or a handled grant fails.
    """
    await shared_database.grant_runtime_privileges(
        pool,
        runtime_role,
        EVALUATION_DATASET_TABLES,
        error_type=EvaluationDatasetStorageError,
    )


async def grant_run_history_runtime_privileges(
    pool: Pool,
    runtime_role: str,
) -> None:
    """Grant schema usage and DML on run/threshold tables separately from datasets.

    These grants add privileges, not revoke other pre-existing permissions or
    grant migration authority. Table availability does not prove operations succeed.

    Args:
        pool: Borrowed pool whose connection can grant the requested privileges.
        runtime_role: Existing PostgreSQL role validated/quoted by the shared helper.

    Raises:
        EvaluationRunHistoryStorageError: Role/table validation or a handled grant fails.
    """
    await shared_database.grant_runtime_privileges(
        pool,
        runtime_role,
        EVALUATION_RUN_HISTORY_TABLES,
        error_type=EvaluationRunHistoryStorageError,
    )
