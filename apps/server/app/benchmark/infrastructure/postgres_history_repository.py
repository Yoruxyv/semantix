"""Retain terminal aggregates with bounded expiry cleanup and active-history pruning.

``app.benchmark.infrastructure.postgres_history_queries`` owns SQL/column layouts;
``app.benchmark.infrastructure.postgres_history_records`` maps values and rows.
The existing migration cascades source-dataset deletion to runs, then thresholds.
Expiry hides records from active reads; physical deletion occurs on later cleanup
or explicit deletion, not by a background timer in this repository.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

import asyncpg
from asyncpg import Connection, Record
from asyncpg.pool import Pool

from app.benchmark.domain.models import (
    EvaluationRunHistoryRecord,
    RetainedEvaluationRun,
    RetainedEvaluationRunPage,
)
from app.benchmark.infrastructure.postgres_history_queries import (
    ACQUIRE_NAMESPACE_LOCK,
    COUNT_ACTIVE_NAMESPACE_RUNS,
    COUNT_ACTIVE_RUNS,
    DELETE_ACTIVE_RUN,
    GET_ACTIVE_RUN,
    GET_RUN_THRESHOLDS,
    INSERT_RUN,
    INSERT_THRESHOLD,
    LIST_ACTIVE_RUNS,
    PRUNE_OLDEST_ACTIVE_HISTORY,
    PURGE_EXPIRED_HISTORY,
    READINESS_QUERY,
)
from app.benchmark.infrastructure.postgres_history_records import (
    build_run_values,
    build_threshold_values,
    retained_run_from_records,
    summary_from_record,
)
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.core.exceptions import AppError, EvaluationRunHistoryStorageError


class PostgresEvaluationRunHistoryRepository:
    """Persist and query aggregate evaluation history in PostgreSQL.

    Borrow the application pool; do not migrate, grant roles, create or close it.
    Retain aggregate/configuration evidence and descriptive dataset metadata, not
    per-query prompts/responses. Callers supply authenticated/authorized scopes
    and resolved source identity/expiry. Pool/driver timeouts apply; this adapter
    supplies no separate deadline or exactly-once retry protocol.
    """

    def __init__(
        self,
        pool: Pool,
        *,
        retention_days: int,
        max_per_namespace: int,
        cleanup_batch_size: int,
    ) -> None:
        """Validate limits and borrow the pool without acquiring a connection.

        Args:
            pool: Application-owned shared PostgreSQL pool.
            retention_days: Requested history lifetime from run completion.
            max_per_namespace: Active history capacity enforced by oldest-record pruning.
            cleanup_batch_size: Maximum expired parent rows selected per purge.

        Raises:
            ValueError: Any repository limit is not positive.
        """
        if retention_days < 1 or max_per_namespace < 1 or cleanup_batch_size < 1:
            raise ValueError(
                "Evaluation run history repository limits must be positive"
            )

        self._pool = pool
        self._retention_days = retention_days
        self._max_per_namespace = max_per_namespace
        self._cleanup_batch_size = cleanup_batch_size

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[Connection[Record], None]:
        """Borrow a connection, preserving AppError and cancellation.

        Only OSError/asyncpg.PostgresError are translated to a generic history storage
        error with a chained cause. Other exceptions and row-mapping failures are not
        universally intercepted or sanitized by this context manager.
        """
        try:
            async with self._pool.acquire() as connection:
                yield cast(Connection, connection)
        except AppError:
            raise
        except (OSError, asyncpg.PostgresError) as error:
            raise EvaluationRunHistoryStorageError(
                "Persistent evaluation run history operation failed"
            ) from error

    async def _purge_expired(
        self,
        connection: Connection[Record],
        namespace: str | None,
    ) -> None:
        """Purge one bounded expired-parent batch, optionally across all namespaces.

        The parent-row limit does not bound cascaded threshold-row deletions.
        """
        await connection.execute(
            PURGE_EXPIRED_HISTORY,
            namespace,
            self._cleanup_batch_size,
        )

    async def _prune_oldest_active(
        self,
        connection: Connection[Record],
        namespace: str,
        count: int,
    ) -> None:
        if count <= 0:
            return
        await connection.execute(
            PRUNE_OLDEST_ACTIVE_HISTORY,
            namespace,
            count,
        )

    def _source_dataset_id(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> UUID | None:
        """Require built-in/no expiry or persisted/UUID plus supplied source expiry.

        Inline sources cannot be retained. Source resolution/namespace authorization
        belongs to the caller; the existing foreign key enforces source existence.
        """
        dataset = record.context.dataset

        if dataset.dataset_source == "builtin":
            if record.context.source_dataset_expires_at is not None:
                raise EvaluationRunHistoryStorageError(
                    "Built-in evaluation history cannot carry source dataset expiry"
                )
            return None

        if dataset.dataset_source != "persisted":
            raise EvaluationRunHistoryStorageError(
                "Only built-in or persisted datasets can be retained in run history"
            )

        if record.context.source_dataset_expires_at is None:
            raise EvaluationRunHistoryStorageError(
                "Persisted evaluation history requires source dataset expiry"
            )

        try:
            return UUID(dataset.dataset_id)
        except ValueError as error:
            raise EvaluationRunHistoryStorageError(
                "Persisted evaluation history requires a valid source dataset ID"
            ) from error

    def _expires_at(self, record: EvaluationRunHistoryRecord) -> datetime:
        """Cap completion-plus-retention by source expiry and require expiry > completion.

        This compares with completion time, not a fresh database/current-time probe.
        """
        expires_at = record.completed_at + timedelta(days=self._retention_days)
        source_expires_at = record.context.source_dataset_expires_at

        if source_expires_at is not None:
            expires_at = min(expires_at, source_expires_at)

        if expires_at <= record.completed_at:
            raise EvaluationRunHistoryStorageError(
                "Evaluation run history retention window has already expired"
            )

        return expires_at

    async def persist_terminal_run(
        self,
        record: EvaluationRunHistoryRecord,
    ) -> None:
        """Insert one terminal aggregate and its supplied ordered threshold evidence.

        Require a history namespace, valid run UUID and supported resolved source.
        In one transaction acquire the history-prefixed namespace advisory lock,
        purge a bounded expired batch, count active runs and prune
        max(0, active_count - capacity + 1) oldest active rows before insertion.
        Oldest means completed_at then run_id ascending. Pruning and both inserts
        commit together; completed records include threshold rows, failures omit them.
        Expiry is completion plus retention capped by source expiry, strictly after
        completion. Source deletion cascades this history and its thresholds.
        The lock coordinates cooperating writes under that key, not all database
        operations. Duplicate IDs are insert errors, not idempotent replacements.

        Args:
            record: Validated terminal aggregate with caller-resolved ownership/source.

        Raises:
            EvaluationRunHistoryStorageError: Identity/source/expiry is invalid,
                value-layout validation fails, or a handled OS/PostgreSQL write fails.
        """
        namespace = record.context.history_namespace
        if namespace is None:
            raise EvaluationRunHistoryStorageError(
                "Retained evaluation history requires a namespace"
            )

        try:
            run_id = UUID(record.context.run_id)
        except ValueError as error:
            raise EvaluationRunHistoryStorageError(
                "Evaluation run history requires a valid run ID"
            ) from error

        source_dataset_id = self._source_dataset_id(record)
        expires_at = self._expires_at(record)

        async with self._connection() as connection, connection.transaction():
            await connection.execute(
                ACQUIRE_NAMESPACE_LOCK,
                f"evaluation-run-history:{namespace}",
            )
            await self._purge_expired(connection, namespace)

            active_count = int(
                await connection.fetchval(
                    COUNT_ACTIVE_NAMESPACE_RUNS,
                    namespace,
                )
            )
            prune_count = max(
                0,
                active_count - self._max_per_namespace + 1,
            )
            await self._prune_oldest_active(
                connection,
                namespace,
                prune_count,
            )

            await connection.execute(
                INSERT_RUN,
                *build_run_values(
                    record,
                    run_id=run_id,
                    source_dataset_id=source_dataset_id,
                    expires_at=expires_at,
                ),
            )

            if record.threshold_evaluations:
                await connection.executemany(
                    INSERT_THRESHOLD,
                    build_threshold_values(run_id, record.threshold_evaluations),
                )

    async def list_runs(
        self,
        *,
        namespace: str | None,
        offset: int,
        limit: int,
    ) -> RetainedEvaluationRunPage:
        """Purge one expired batch, then count/page active aggregate summaries.

        Statements share a default-isolation transaction, not a guaranteed stable
        concurrent snapshot. Threshold rows are not loaded for summaries.

        Args:
            namespace: Authorized namespace filter, or None for authorized global listing.
            offset: Caller-validated pagination offset.
            limit: Caller-validated maximum page size.

        Returns:
            Active summaries ordered by completed_at descending, then run_id ascending.

        Raises:
            EvaluationRunHistoryStorageError: A mapped row or handled OS/PostgreSQL
                operation is inconsistent/failed.
        """
        async with self._connection() as connection, connection.transaction():
            await self._purge_expired(connection, namespace)
            total = int(
                await connection.fetchval(
                    COUNT_ACTIVE_RUNS,
                    namespace,
                )
            )
            rows = await connection.fetch(
                LIST_ACTIVE_RUNS,
                namespace,
                limit,
                offset,
            )

        return RetainedEvaluationRunPage(
            items=tuple(summary_from_record(row) for row in rows),
            total=total,
        )

    async def get_run(
        self,
        run_id: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> RetainedEvaluationRun | None:
        """Read an active scoped parent, then its sequence-ordered threshold rows.

        Both reads share a connection but no explicit enclosing transaction. Concurrent
        deletion/pruning can leave incomplete detail for mapper validation; this is not
        a guaranteed atomic snapshot. No expired-row cleanup is performed here.

        Args:
            run_id: UUID string; invalid strings return None without SQL.
            authorized_namespaces: Caller-authorized scope; None is unrestricted and
                an empty set permits no namespace.

        Returns:
            Reconstructed retained detail, or None for invalid, expired, absent or
            invisible parent identity without distinguishing those cases.

        Raises:
            EvaluationRunHistoryStorageError: A mapped row/detail is inconsistent
                or a handled OS/PostgreSQL operation fails.
        """
        try:
            resolved_id = UUID(run_id)
        except ValueError:
            return None

        namespace_scope = (
            None if authorized_namespaces is None else sorted(authorized_namespaces)
        )
        async with self._connection() as connection:
            row = await connection.fetchrow(
                GET_ACTIVE_RUN,
                resolved_id,
                namespace_scope,
            )
            if row is None:
                return None

            threshold_rows = await connection.fetch(
                GET_RUN_THRESHOLDS,
                resolved_id,
            )

        return retained_run_from_records(row, list(threshold_rows))

    async def delete_run(
        self,
        run_id: str,
        *,
        namespace: str,
    ) -> bool:
        """Delete an active run in the concrete authorized namespace after bounded purge.

        Threshold rows cascade through the existing foreign key. Purge and deletion
        share a transaction, including when the requested deletion returns false.

        Args:
            run_id: UUID string; invalid strings return False without SQL.
            namespace: Concrete namespace already authorized by the caller.

        Returns:
            Whether the requested active scoped parent was deleted.
        """
        try:
            resolved_id = UUID(run_id)
        except ValueError:
            return False

        async with self._connection() as connection, connection.transaction():
            await self._purge_expired(connection, namespace)
            deleted = await connection.fetchval(
                DELETE_ACTIVE_RUN,
                resolved_id,
                namespace,
            )

        return deleted is not None

    async def readiness(self) -> None:
        """Check run-parent table read access without loading historical evidence.

        This does not prove threshold-table/write availability or probe providers,
        datasets or the top-level readiness endpoint's configured checks.
        """
        async with self._connection() as connection:
            await connection.fetchval(READINESS_QUERY)
