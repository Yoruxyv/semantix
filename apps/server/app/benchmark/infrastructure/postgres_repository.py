"""Persist explicit imported datasets, including private case text, in PostgreSQL.

Metadata and ordered cases use the existing evaluation schema, separate from the
embedded cache store. Repository queries enforce supplied namespace filters;
HTTP authentication/authorization and import validation belong to callers.
Dataset capacity rejects creation rather than pruning active datasets. Existing
foreign keys cascade source deletion to cases and linked retained run history.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import asyncpg
from asyncpg import Connection, Record
from asyncpg.pool import Pool

from app.benchmark.api.schemas import BenchmarkDatasetSummary
from app.benchmark.domain.models import (
    BenchmarkCase,
    BenchmarkDataset,
    PersistedEvaluationDataset,
    PersistedEvaluationDatasetMetadata,
    PersistedEvaluationDatasetPage,
)
from app.benchmark.domain.validation import ValidatedImportedDataset
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.exceptions import (
    AppError,
    EvaluationDatasetCapacityError,
    EvaluationDatasetStorageError,
)

PURGE_EXPIRED = """
DELETE FROM semantix.evaluation_datasets
WHERE dataset_id IN (
    SELECT dataset_id
    FROM semantix.evaluation_datasets
    WHERE expires_at <= CURRENT_TIMESTAMP
      AND ($1::text IS NULL OR namespace = $1)
    ORDER BY expires_at, dataset_id
    LIMIT $2
)
"""


def _metadata_from_record(row: Record) -> PersistedEvaluationDatasetMetadata:
    return PersistedEvaluationDatasetMetadata(
        dataset_id=str(cast(UUID, row["dataset_id"])),
        namespace=str(row["namespace"]),
        name=str(row["name"]),
        description=(None if row["description"] is None else str(row["description"])),
        schema_version=int(row["schema_version"]),
        digest=str(row["digest"]),
        case_count=int(row["case_count"]),
        decoded_bytes=int(row["decoded_bytes"]),
        created_at=cast(datetime, row["created_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )


def _case_from_record(row: Record) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=str(row["case_id"]),
        prompt=str(row["prompt"]),
        expected_cache_hit=bool(row["expected_cache_hit"]),
        expected_match_case_id=(
            None
            if row["expected_match_case_id"] is None
            else str(row["expected_match_case_id"])
        ),
        category=str(row["category"]),
        note=None if row["note"] is None else str(row["note"]),
    )


def _dataset(
    metadata: PersistedEvaluationDatasetMetadata,
    cases: Sequence[BenchmarkCase],
) -> BenchmarkDataset:
    """Rebuild persisted identity/counts from metadata and the supplied case order.

    Version comes from schema_version and the stored digest is carried unchanged,
    not recomputed. The detail reader separately checks metadata's case count.
    """
    expected_hits = sum(case.expected_cache_hit for case in cases)
    categories = list(dict.fromkeys(case.category for case in cases))
    return BenchmarkDataset(
        summary=BenchmarkDatasetSummary(
            dataset_id=metadata.dataset_id,
            dataset_source="persisted",
            schema_version=metadata.schema_version,
            version=str(metadata.schema_version),
            digest=metadata.digest,
            name=metadata.name,
            description=(
                metadata.description or "Persisted imported evaluation dataset."
            ),
            query_count=len(cases),
            expected_hits=expected_hits,
            expected_misses=len(cases) - expected_hits,
            categories=categories,
        ),
        cases=tuple(cases),
    )


class PostgresEvaluationDatasetRepository:
    """Borrow a shared pool for scoped imported-dataset persistence and reads.

    Opening/closing the pool, migrations, role grants and caller authorization
    remain outside this adapter. Connections are released through the pool's
    context manager. Methods use the configured pool/driver timeout behavior;
    this repository does not add its own deadline or background cleanup task.
    """

    def __init__(
        self,
        pool: Pool,
        *,
        max_per_namespace: int,
        cleanup_batch_size: int,
    ) -> None:
        """Validate repository limits without acquiring a connection.

        Args:
            pool: Application-owned shared PostgreSQL pool to borrow.
            max_per_namespace: Maximum active datasets before creation is rejected.
            cleanup_batch_size: Maximum expired parent rows selected per purge.

        Raises:
            ValueError: Either repository limit is not positive.
        """
        if max_per_namespace < 1 or cleanup_batch_size < 1:
            raise ValueError("Persistent dataset repository limits must be positive")
        self._pool = pool
        self._max_per_namespace = max_per_namespace
        self._cleanup_batch_size = cleanup_batch_size

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[Connection[Record], None]:
        """Borrow a connection and translate only handled OS/PostgreSQL failures.

        Existing AppError and cancellation propagate. OSError/asyncpg.PostgresError
        become EvaluationDatasetStorageError with a generic internal message and a
        chained cause; other conversion/driver exceptions are not all intercepted.
        """
        try:
            async with self._pool.acquire() as connection:
                yield cast(Connection, connection)
        except AppError:
            raise
        except (OSError, asyncpg.PostgresError) as error:
            raise EvaluationDatasetStorageError(
                "Persistent evaluation dataset operation failed"
            ) from error

    async def _purge_expired(
        self,
        connection: Connection[Record],
        namespace: str | None,
    ) -> None:
        """Delete at most one configured batch of expired parents in the supplied scope.

        None selects all namespaces. Foreign-key cascades may remove additional
        dependent rows; the batch bounds parents, not total cascaded row work.
        """
        await connection.execute(
            PURGE_EXPIRED,
            namespace,
            self._cleanup_batch_size,
        )

    async def list_datasets(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> PersistedEvaluationDatasetPage:
        """Purge a bounded expired batch, then count and page active metadata.

        These statements share a transaction without an explicitly stronger isolation
        level; count/page are not promised to be a concurrent stable snapshot.

        Args:
            namespace: Caller-authorized filter, or None for an authorized global list.
            offset: Validated pagination offset.
            limit: Validated maximum returned metadata rows.

        Returns:
            Active metadata ordered by created_at descending, then dataset_id.

        Raises:
            EvaluationDatasetStorageError: A handled OS/PostgreSQL operation fails.
        """
        async with self._connection() as connection, connection.transaction():
            await self._purge_expired(connection, namespace)
            total = int(
                await connection.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM semantix.evaluation_datasets
                    WHERE expires_at > CURRENT_TIMESTAMP
                      AND ($1::text IS NULL OR namespace = $1)
                    """,
                    namespace,
                )
            )
            rows = await connection.fetch(
                """
                SELECT
                    dataset_id,
                    namespace,
                    name,
                    description,
                    schema_version,
                    digest,
                    case_count,
                    decoded_bytes,
                    created_at,
                    expires_at
                FROM semantix.evaluation_datasets
                WHERE expires_at > CURRENT_TIMESTAMP
                  AND ($1::text IS NULL OR namespace = $1)
                ORDER BY created_at DESC, dataset_id
                LIMIT $2
                OFFSET $3
                """,
                namespace,
                limit,
                offset,
            )
        return PersistedEvaluationDatasetPage(
            items=tuple(_metadata_from_record(row) for row in rows),
            total=total,
        )

    async def get_dataset(
        self,
        dataset_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> PersistedEvaluationDataset | None:
        """Read visible active metadata and cases ordered by stored sequence.

        Parent and case reads share a transaction with its default isolation. Check
        reconstructed case count against metadata before returning, without re-running
        import validation or recomputing the digest. Imported prompts/notes are private
        contents; knowing the UUID does not bypass the supplied namespace scope.

        Args:
            dataset_id: Persisted UUID string; invalid strings return None.
            authorized_namespaces: Authorized scope, None for unrestricted reads or
                an empty set for no permitted namespace.

        Returns:
            Ordered dataset with metadata, or None for invalid, expired, absent or
            invisible identity, without disclosing which lookup condition failed.

        Raises:
            EvaluationDatasetStorageError: Case count is inconsistent or a handled
                OS/PostgreSQL operation fails. Other row-conversion errors can propagate.
        """
        try:
            resolved_id = UUID(dataset_id)
        except ValueError:
            return None
        namespace_scope = (
            None if authorized_namespaces is None else sorted(authorized_namespaces)
        )
        async with self._connection() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                SELECT
                    dataset_id,
                    namespace,
                    name,
                    description,
                    schema_version,
                    digest,
                    case_count,
                    decoded_bytes,
                    created_at,
                    expires_at
                FROM semantix.evaluation_datasets
                WHERE dataset_id = $1
                  AND expires_at > CURRENT_TIMESTAMP
                  AND (
                      $2::text[] IS NULL
                      OR namespace = ANY($2::text[])
                  )
                """,
                resolved_id,
                namespace_scope,
            )
            if row is None:
                return None
            case_rows = await connection.fetch(
                """
                SELECT
                    sequence,
                    case_id,
                    prompt,
                    expected_cache_hit,
                    expected_match_case_id,
                    category,
                    note
                FROM semantix.evaluation_dataset_cases
                WHERE dataset_id = $1
                ORDER BY sequence
                """,
                resolved_id,
            )
        metadata = _metadata_from_record(row)
        cases = tuple(_case_from_record(case) for case in case_rows)
        if len(cases) != metadata.case_count:
            raise EvaluationDatasetStorageError(
                "Persistent evaluation dataset case count is inconsistent"
            )
        return PersistedEvaluationDataset(
            metadata=metadata,
            dataset=_dataset(metadata, cases),
        )

    async def create_dataset(
        self,
        *,
        namespace: str,
        validated: ValidatedImportedDataset,
        retention_days: int,
    ) -> PersistedEvaluationDataset:
        """Explicitly save validated metadata and ordered case records in one transaction.

        Assign a fresh UUID and UTC created/expiry times using requested retention.
        The caller supplies validated data, retention bounds and authorized namespace.
        Acquire an advisory transaction lock keyed by namespace, purge one expired
        batch, count active datasets and reject a full namespace before inserting.
        Metadata and one-based case sequences commit together. Mapping the result is
        afterward. The lock coordinates this creation path, not every read/delete or
        the separately keyed history-persistence path.

        Args:
            namespace: Concrete caller-authorized ownership namespace.
            validated: Import validation result, including counts and semantic digest.
            retention_days: Caller-validated duration from creation to expiry.

        Returns:
            Newly assigned metadata and reconstructed persisted dataset identity.

        Raises:
            EvaluationDatasetCapacityError: Active namespace capacity is full.
            EvaluationDatasetStorageError: Insert evidence is missing or a handled
                OS/PostgreSQL operation fails.
        """
        dataset_id = uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(days=retention_days)
        preview = validated.preview
        dataset = validated.dataset

        async with self._connection() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                namespace,
            )
            await self._purge_expired(connection, namespace)
            active_count = int(
                await connection.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM semantix.evaluation_datasets
                    WHERE namespace = $1
                      AND expires_at > CURRENT_TIMESTAMP
                    """,
                    namespace,
                )
            )
            if active_count >= self._max_per_namespace:
                raise EvaluationDatasetCapacityError
            row = await connection.fetchrow(
                """
                INSERT INTO semantix.evaluation_datasets (
                    dataset_id,
                    namespace,
                    name,
                    description,
                    source_type,
                    schema_version,
                    digest,
                    case_count,
                    decoded_bytes,
                    created_at,
                    expires_at
                )
                VALUES ($1, $2, $3, $4, 'imported', $5, $6, $7, $8, $9, $10)
                RETURNING
                    dataset_id,
                    namespace,
                    name,
                    description,
                    schema_version,
                    digest,
                    case_count,
                    decoded_bytes,
                    created_at,
                    expires_at
                """,
                dataset_id,
                namespace,
                preview.name,
                preview.description,
                preview.schema_version,
                preview.digest,
                preview.case_count,
                preview.decoded_bytes,
                created_at,
                expires_at,
            )
            if row is None:
                raise EvaluationDatasetStorageError(
                    "Persistent evaluation dataset insert returned no evidence"
                )
            await connection.executemany(
                """
                INSERT INTO semantix.evaluation_dataset_cases (
                    dataset_id,
                    sequence,
                    case_id,
                    prompt,
                    expected_cache_hit,
                    expected_match_case_id,
                    category,
                    note
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    (
                        dataset_id,
                        sequence,
                        case.case_id,
                        case.prompt,
                        case.expected_cache_hit,
                        case.expected_match_case_id,
                        case.category,
                        case.note,
                    )
                    for sequence, case in enumerate(dataset.cases, start=1)
                ],
            )
        metadata = _metadata_from_record(row)
        return PersistedEvaluationDataset(
            metadata=metadata,
            dataset=_dataset(metadata, dataset.cases),
        )

    async def delete_dataset(
        self,
        dataset_id: str,
        *,
        namespace: str,
    ) -> bool:
        """Delete an active identity in one concrete namespace after bounded cleanup.

        Existing foreign keys cascade its cases and source-linked run/threshold rows.
        Cleanup and deletion share a transaction; false does not mean cleanup did no work.

        Args:
            dataset_id: UUID string; invalid strings return False without SQL.
            namespace: Concrete namespace already authorized by the caller.

        Returns:
            Whether the targeted active scoped parent was deleted.
        """
        try:
            resolved_id = UUID(dataset_id)
        except ValueError:
            return False
        async with self._connection() as connection, connection.transaction():
            await self._purge_expired(connection, namespace)
            deleted = await connection.fetchval(
                """
                DELETE FROM semantix.evaluation_datasets
                WHERE dataset_id = $1
                  AND namespace = $2
                  AND expires_at > CURRENT_TIMESTAMP
                RETURNING dataset_id
                """,
                resolved_id,
                namespace,
            )
        return deleted is not None

    async def readiness(self) -> None:
        """Check dataset-parent table read access without loading private records.

        This is not a write/child-table/provider/history probe. Handled OS/PostgreSQL
        failures use the same storage-error translation as other connection operations.
        """
        async with self._connection() as connection:
            await connection.fetchval(
                "SELECT COUNT(*) FROM semantix.evaluation_datasets WHERE FALSE"
            )
