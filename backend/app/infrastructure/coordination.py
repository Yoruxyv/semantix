import logging
from datetime import datetime, timedelta
from hashlib import sha256
from math import ceil
from time import monotonic

import asyncpg
from asyncpg.pool import Pool

from app.core.exceptions import CoordinationStorageError
from app.security.auth_attempts import (
    FAILURES_PER_STAGE,
    LOCKOUT_DURATIONS_SECONDS,
    STALE_STATE_SECONDS,
)

logger = logging.getLogger(__name__)

RATE_BUCKET_SQL = """
INSERT INTO semantix.rate_limit_buckets (bucket_key, hits, expires_at)
VALUES ($1, 1, clock_timestamp() + make_interval(secs => $2::double precision))
ON CONFLICT (bucket_key) DO UPDATE SET
    hits = CASE
        WHEN semantix.rate_limit_buckets.expires_at <= clock_timestamp() THEN 1
        ELSE LEAST(semantix.rate_limit_buckets.hits + 1, $3::bigint + 1)
    END,
    expires_at = CASE
        WHEN semantix.rate_limit_buckets.expires_at <= clock_timestamp()
            THEN clock_timestamp() + make_interval(secs => $2::double precision)
        ELSE semantix.rate_limit_buckets.expires_at
    END
RETURNING hits
"""


def _key(*parts: str) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()


class PostgresCoordination:
    """One PostgreSQL authority for security counters and the global threshold."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        self._last_cleanup = monotonic()

    async def _cleanup_if_due(self) -> None:
        now = monotonic()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        try:
            async with self._pool.acquire() as connection:
                await connection.execute(
                    """
                DELETE FROM semantix.rate_limit_buckets
                WHERE expires_at <= clock_timestamp()
                  AND bucket_key IN (
                    SELECT bucket_key FROM semantix.rate_limit_buckets
                    WHERE expires_at <= clock_timestamp()
                    LIMIT 1000
                )
                """
                )
                await connection.execute(
                    """
                DELETE FROM semantix.authentication_attempts
                WHERE last_activity <= clock_timestamp() - interval '1 day'
                  AND client_key IN (
                    SELECT client_key FROM semantix.authentication_attempts
                    WHERE last_activity <= clock_timestamp() - interval '1 day'
                    LIMIT 1000
                )
                """
                )
        except (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError):
            logger.warning("Optional coordination expiry cleanup failed")

    async def allow_request(
        self, address: str, route: str, quota: str, amount: int, seconds: int
    ) -> bool:
        try:
            async with self._pool.acquire() as connection:
                hits = await connection.fetchval(
                    RATE_BUCKET_SQL,
                    _key(address, route, quota),
                    seconds,
                    amount,
                )
            await self._cleanup_if_due()
            return isinstance(hits, int) and hits <= amount
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ) as error:
            raise CoordinationStorageError from error

    async def record_session_attempt(
        self, address: str, *, succeeded: bool
    ) -> int | None:
        client_key = _key(address)
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                if not succeeded:
                    await connection.execute(
                        """
                        INSERT INTO semantix.authentication_attempts
                            (client_key, failures, escalation_stage, last_activity)
                        VALUES ($1, 0, 0, clock_timestamp())
                        ON CONFLICT (client_key) DO NOTHING
                        """,
                        client_key,
                    )
                row = await connection.fetchrow(
                    """
                    SELECT failures, escalation_stage, locked_until, last_activity
                    FROM semantix.authentication_attempts
                    WHERE client_key = $1
                    FOR UPDATE
                    """,
                    client_key,
                )
                if row is None:
                    return None

                now: datetime = await connection.fetchval("SELECT clock_timestamp()")
                failures = int(row["failures"])
                stage = int(row["escalation_stage"])
                locked_until: datetime | None = row["locked_until"]
                if (now - row["last_activity"]).total_seconds() >= STALE_STATE_SECONDS:
                    failures, stage, locked_until = 0, 0, None

                if locked_until is not None and locked_until > now:
                    return max(1, ceil((locked_until - now).total_seconds()))
                if succeeded:
                    await connection.execute(
                        "DELETE FROM semantix.authentication_attempts WHERE client_key = $1",
                        client_key,
                    )
                    return None

                failures += 1
                retry_after: int | None = None
                if failures >= FAILURES_PER_STAGE:
                    retry_after = LOCKOUT_DURATIONS_SECONDS[stage]
                    failures = 0
                    stage = min(stage + 1, len(LOCKOUT_DURATIONS_SECONDS) - 1)
                    locked_until = now + timedelta(seconds=retry_after)
                else:
                    locked_until = None
                await connection.execute(
                    """
                    UPDATE semantix.authentication_attempts
                    SET failures = $2, escalation_stage = $3,
                        locked_until = $4, last_activity = $5
                    WHERE client_key = $1
                    """,
                    client_key,
                    failures,
                    stage,
                    locked_until,
                    now,
                )
            await self._cleanup_if_due()
            return retry_after
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ) as error:
            raise CoordinationStorageError from error

    async def initialize_threshold(self, default: float) -> None:
        try:
            async with self._pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO semantix.cache_threshold (singleton, threshold)
                    VALUES (TRUE, $1)
                    ON CONFLICT (singleton) DO NOTHING
                    """,
                    default,
                )
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ) as error:
            raise CoordinationStorageError from error

    async def read_threshold(self) -> float:
        try:
            async with self._pool.acquire() as connection:
                value = await connection.fetchval(
                    "SELECT threshold FROM semantix.cache_threshold WHERE singleton"
                )
            if value is None:
                raise CoordinationStorageError
            return float(value)
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ) as error:
            raise CoordinationStorageError from error

    async def write_threshold(self, threshold: float) -> float:
        try:
            async with self._pool.acquire() as connection:
                value = await connection.fetchval(
                    """
                    INSERT INTO semantix.cache_threshold (singleton, threshold)
                    VALUES (TRUE, $1)
                    ON CONFLICT (singleton) DO UPDATE SET threshold = EXCLUDED.threshold
                    RETURNING threshold
                    """,
                    threshold,
                )
            return float(value)
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ) as error:
            raise CoordinationStorageError from error
