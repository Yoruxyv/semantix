"""Exact cosine storage in an application database; migrations are always explicit.

Install semantix-cache[pgvector]. Operators install the vector extension first.
PgVectorStore(pool=...) borrows its pool; await PgVectorStore.connect(...) owns one.
Neither construction nor ordinary cache operations create or adopt database objects.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from importlib.resources import files
from types import TracebackType
from typing import Self, cast

try:
    import asyncpg
    from asyncpg.pool import Pool, PoolConnectionProxy
except ModuleNotFoundError as exc:
    if exc.name != "asyncpg":
        raise
    raise ImportError(
        "PostgreSQL storage requires 'semantix-cache[pgvector]'. "
        "Custom CacheStore implementations need no database extra: "
        "https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-storage.md"
    ) from None

from .._lifecycle import Lifecycle
from .._semantics import (
    cache_key_value,
    finite_number,
    namespace_value,
    normalized_vector,
    resolve_ttl,
)
from ..errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    SemantixCacheError,
)
from ..inspection import (
    InspectionEntry,
    InspectionPage,
    InspectionSort,
    inspection_arguments,
    inspection_namespaces,
    remaining,
)
from ..models import CacheEntry, CacheMatch, EmbeddingSpace

_MARKER = "semantix-cache:pgvector:v1"
_MIGRATION = (
    files("semantix_cache.stores.migrations")
    .joinpath("0001_cache.sql")
    .read_text(encoding="utf-8")
)
_CHECKSUM = sha256(_MIGRATION.encode("utf-8")).hexdigest()
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}", re.ASCII)


def _quote(name: str) -> str:
    # Catalog-owned extension identifiers may use mixed case; escape every quote.
    return '"' + name.replace('"', '""') + '"'


def _positive_timeout(value: float) -> float:
    result = finite_number(value, minimum=0.0, maximum=86400.0)
    if result == 0:
        raise ValueError("Timeout must be positive")
    return result


@dataclass(frozen=True)
class _Configuration:
    space: EmbeddingSpace
    schema: str
    prefix: str
    capacity: int
    ttl: float | None
    timeout: float
    close_timeout: float

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.space, EmbeddingSpace):
                raise CacheConfigurationError("Invalid PostgreSQL embedding space")
            space = EmbeddingSpace.model_validate(self.space.model_dump())
            if (
                space.dimensions > 16000
                or len(space.identity) > 1024
                or "\0" in space.identity
            ):
                raise ValueError("Space exceeds database limits")
            if (
                not isinstance(self.schema, str)
                or _IDENTIFIER.fullmatch(self.schema) is None
            ):
                raise ValueError("Invalid schema")
            if self.schema.startswith("pg_") or self.schema == "information_schema":
                raise ValueError("Reserved schema")
            if not isinstance(self.prefix, str) or (
                self.prefix and _IDENTIFIER.fullmatch(self.prefix) is None
            ):
                raise ValueError("Invalid prefix")
            for suffix in (
                "cache_entries",
                "binding_state",
                "schema_migrations",
                "scope_idx",
            ):
                if _IDENTIFIER.fullmatch(self.prefix + suffix) is None:
                    raise ValueError("Identifier exceeds database limits")
            if (
                isinstance(self.capacity, bool)
                or not isinstance(self.capacity, int)
                or not 1 <= self.capacity <= 100000
            ):
                raise ValueError("Invalid capacity")
            object.__setattr__(self, "space", space)
            object.__setattr__(self, "ttl", resolve_ttl(None, self.ttl))
            object.__setattr__(self, "timeout", _positive_timeout(self.timeout))
            object.__setattr__(
                self, "close_timeout", _positive_timeout(self.close_timeout)
            )
        except ValueError:
            raise CacheConfigurationError(
                "Invalid PostgreSQL store configuration"
            ) from None

    def relation(self, suffix: str) -> str:
        return _quote(self.schema) + "." + _quote(self.prefix + suffix)

    @property
    def lock_key(self) -> str:
        return "semantix-cache:" + self.schema + ":" + self.prefix


class PgVectorStore:
    """Bounded exact search, space/namespace isolation, non-sliding TTL and LRU.

    The caller authorizes namespaces and owns supplied pools. Runtime operations
    only touch marked tables in the configured schema/prefix. Use a separate
    migration pool with initialize_schema(), or apply the packaged migration
    through controlled deployment tooling. connect() does not initialize schema.
    """

    def __init__(
        self,
        *,
        pool: Pool,
        embedding_space: EmbeddingSpace,
        schema: str = "semantix_cache",
        table_prefix: str = "",
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> None:
        """Bind a borrowed asyncpg pool without connecting or initializing tables.

        The pool stays caller-owned, including after context exit or aclose.
        Storage operations validate markers and migration version/checksum before
        using the selected tables. They have one deadline covering acquisition,
        I/O, transaction completion and release. Cancellation propagates; expected
        driver failures become safe CacheStoreError/CacheTimeoutError without raw
        DSNs or server payloads. No automatic replay is provided; a lost commit
        acknowledgement can leave a mutation's outcome uncertain.

        Args:
            pool: Existing asyncpg Pool, not an individual connection.
            embedding_space: Identity (at most 1,024 characters, no NUL) and
                dimensions (1-16,000) that scope entries in the shared tables.
            schema: Cache schema; defaults to semantix_cache. Use a non-reserved
                lowercase ASCII SQL identifier of at most 63 characters.
            table_prefix: Optional prefix for owned entries, binding state,
                migration ledger and index. Complete names must fit 63 characters.
            max_size: Capacity across this space's namespaces, 1-100,000;
                defaults to 500.
            default_ttl_seconds: Positive finite retention up to 31,536,000 seconds,
                defaulting to 3,600. None permits writes without expiry.
            operation_timeout_seconds: Positive finite operation deadline, at most
                86,400 seconds; defaults to 30.
            close_timeout_seconds: Positive finite owned-pool close deadline with
                the same bounds/default. Borrowed pools are never closed here.

        Raises:
            CacheConfigurationError: If the pool or binding configuration is invalid.
        """

        self._config = _Configuration(
            embedding_space,
            schema,
            table_prefix,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        if not isinstance(cast(object, pool), Pool):
            raise CacheConfigurationError("Expected an asyncpg pool, not a connection")
        self._pool = pool
        self._owned = False
        self._state = Lifecycle()

    @classmethod
    async def connect(
        cls,
        *,
        dsn: str,
        embedding_space: EmbeddingSpace,
        schema: str = "semantix_cache",
        table_prefix: str = "",
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        pool_min_size: int = 1,
        pool_max_size: int = 5,
        connect_timeout_seconds: float = 10.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> PgVectorStore:
        """Create and prewarm an owned pool without initializing or validating schema.

        Other binding/deadline arguments follow the constructor. Failed or
        cancelled startup terminates the partially opened pool; cancellation and
        unexpected programming errors propagate. Call validate_schema before use.

        Args:
            dsn: Private postgres:// or postgresql:// connection URL. Keep it out
                of logs and source control.
            pool_min_size: Initial connection count, default 1.
            pool_max_size: Pool ceiling, default 5; 1 <= min <= max <= 100.
            connect_timeout_seconds: Positive finite total startup deadline, at
                most 86,400 seconds; defaults to 10.

        Returns:
            Store owning its pool; close it with aclose or async context exit.

        Raises:
            CacheConfigurationError: If connection or binding settings are invalid.
            CacheTimeoutError: If the startup deadline expires.
            CacheStoreError: For expected connection/driver failures.
        """

        config = _Configuration(
            embedding_space,
            schema,
            table_prefix,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        try:
            timeout = _positive_timeout(connect_timeout_seconds)
            if (
                not isinstance(dsn, str)
                or not dsn.startswith(("postgres://", "postgresql://"))
                or not dsn.strip()
                or "\0" in dsn
                or len(dsn) > 8192
            ):
                raise ValueError("Invalid DSN")
            if (
                any(
                    isinstance(v, bool) or not isinstance(v, int)
                    for v in (pool_min_size, pool_max_size)
                )
                or not 1 <= pool_min_size <= pool_max_size <= 100
            ):
                raise ValueError("Invalid pool bounds")
        except ValueError:
            raise CacheConfigurationError(
                "Invalid PostgreSQL connection configuration"
            ) from None
        pool: Pool | None = None
        failure: SemantixCacheError
        try:
            pool = asyncpg.create_pool(
                dsn=dsn,
                min_size=0,
                max_size=pool_max_size,
                timeout=timeout,
                command_timeout=config.timeout,
            )
            try:
                async with asyncio.timeout(timeout):
                    await pool
                    # Serial prewarming avoids driver-internal concurrent startup
                    # tasks surviving partial failure. Hold each connection until
                    # the requested minimum is established, then reuse this pool.
                    async with AsyncExitStack() as stack:
                        for _ in range(pool_min_size):
                            await stack.enter_async_context(
                                pool.acquire(timeout=timeout)
                            )
                store = cls(
                    pool=pool,
                    embedding_space=embedding_space,
                    schema=schema,
                    table_prefix=table_prefix,
                    max_size=max_size,
                    default_ttl_seconds=default_ttl_seconds,
                    operation_timeout_seconds=operation_timeout_seconds,
                    close_timeout_seconds=close_timeout_seconds,
                )
            except BaseException:
                # Cleanup only; cancellation and unexpected bugs propagate.
                pool.terminate()
                raise
        except TimeoutError:
            failure = CacheTimeoutError("PostgreSQL connection deadline expired")
        except ValueError:
            failure = CacheConfigurationError(
                "Invalid PostgreSQL connection configuration"
            )
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
            failure = CacheStoreError(
                "Could not connect to the configured PostgreSQL database"
            )
        else:
            store._owned = True
            return store
        # Raw driver errors can contain DSNs or server-provided payloads.
        # Construct the cause after the except block so neither context leaks.
        raise failure from RuntimeError(str(failure))

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._config.space

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._config.ttl

    @asynccontextmanager
    async def _connection(
        self, pool: Pool | None = None
    ) -> AsyncGenerator[PoolConnectionProxy[asyncpg.Record], None]:
        with self._state.operation():
            failure: SemantixCacheError | None = None
            try:
                async with asyncio.timeout(self._config.timeout):
                    async with (self._pool if pool is None else pool).acquire(
                        timeout=self._config.timeout
                    ) as connection:
                        yield connection
            except TimeoutError:
                failure = CacheTimeoutError("PostgreSQL operation deadline expired")
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
                failure = CacheStoreError(
                    "PostgreSQL operation failed; check connectivity, permissions and schema"
                )
            if failure is not None:
                raise failure from RuntimeError(str(failure))

    async def _layout(
        self, connection: PoolConnectionProxy[asyncpg.Record], *, require_schema: bool
    ) -> dict[str, str]:
        extension = await connection.fetchval(
            "SELECT n.nspname FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
        )
        if not isinstance(extension, str):
            raise CacheStoreError(
                "Install the vector extension before initializing the cache schema"
            )
        vector_schema = _quote(extension)
        layout = {
            "ledger": self._config.relation("schema_migrations"),
            "bindings": self._config.relation("binding_state"),
            "entries": self._config.relation("cache_entries"),
            "scope_index": _quote(self._config.prefix + "scope_idx"),
            "vector": vector_schema + '."vector"',
            "vector_dims": vector_schema + '."vector_dims"',
            "cosine": "OPERATOR(" + vector_schema + ".<=>)",
        }
        rows = await connection.fetch(
            "SELECT c.relname, c.relkind, pg_catalog.obj_description(c.oid, 'pg_class') AS marker FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname=$1 AND c.relname=ANY($2::text[])",
            self._config.schema,
            [
                self._config.prefix + suffix
                for suffix in ("schema_migrations", "binding_state", "cache_entries")
            ],
        )
        if not rows and not require_schema:
            return layout
        if len(rows) != 3 or any(
            row["marker"] != _MARKER or row["relkind"] != b"r" for row in rows
        ):
            raise CacheStoreError(
                "Cache schema is absent or unowned; initialize explicitly or choose another schema/prefix"
            )
        # Identifiers come only from the validated configuration and quoted catalog.
        versions = await connection.fetch(
            f"SELECT version, checksum FROM {layout['ledger']}"
        )
        if (
            len(versions) != 1
            or versions[0]["version"] != "0001"
            or versions[0]["checksum"] != _CHECKSUM
        ):
            raise CacheStoreError("Cache schema migration version/checksum mismatch")
        return layout

    async def initialize_schema(self, *, migration_pool: Pool) -> None:
        """Explicitly initialize marked tables using separate migration authority.

        Operators must install the vector extension first. In one transaction,
        lock schema creation before the configured prefix, reject foreign/partial
        layouts and apply the packaged migration with its checksum ledger. An
        already valid layout is left intact; this does not convert legacy tables
        or automatically migrate unknown versions.

        Args:
            migration_pool: Separately supplied, authorized asyncpg pool for DDL.
                It is borrowed and never closed; runtime credentials need no DDL.

        Raises:
            CacheConfigurationError: If migration_pool is not an asyncpg Pool.
            CacheStoreError: For absent extension, ownership/checksum mismatch or
                expected database failures. Failed transactions roll back.
            CacheTimeoutError: If the operation deadline expires.
        """

        self._state.check_open()
        if not isinstance(cast(object, migration_pool), Pool):
            raise CacheConfigurationError(
                "Expected a separately authorized migration pool"
            )
        async with (
            self._connection(migration_pool) as connection,
            connection.transaction(),
        ):
            # Different prefixes share schema creation. Serialize that boundary
            # before taking the prefix lock; IF NOT EXISTS alone races in catalogs.
            await connection.execute(
                "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
                "semantix-cache:schema:" + self._config.schema,
            )
            await connection.execute(
                "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
                self._config.lock_key,
            )
            layout = await self._layout(connection, require_schema=False)
            exists = await connection.fetchval(
                "SELECT pg_catalog.to_regclass($1)", layout["ledger"]
            )
            if exists is not None:
                return
            await connection.execute(
                f"CREATE SCHEMA IF NOT EXISTS {_quote(self._config.schema)}"
            )
            await connection.execute(_MIGRATION.format_map(layout))
            await connection.execute(
                f"INSERT INTO {layout['ledger']} (version, checksum) VALUES ($1, $2)",
                "0001",
                _CHECKSUM,
            )

    async def validate_schema(self) -> None:
        """Check the extension, three table markers and known ledger version/checksum.

        This performs no DDL or adoption and is not a complete schema-tampering
        audit. Administrators must prevent out-of-band changes.

        Raises:
            CacheStoreError: If required objects are absent, unowned, incompatible
                or inaccessible, or an expected driver failure occurs.
            CacheTimeoutError: If acquisition or validation exceeds the deadline.
        """

        async with self._connection() as connection:
            await self._layout(connection, require_schema=True)

    async def _lock(self, connection: PoolConnectionProxy[asyncpg.Record]) -> None:
        await connection.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
            self._config.lock_key
            + ":"
            + self.embedding_space.identity
            + ":"
            + str(self.embedding_space.dimensions),
        )

    def _scope(self, namespace: str) -> tuple[str, int, str]:
        self._state.check_open()
        try:
            return (
                self.embedding_space.identity,
                self.embedding_space.dimensions,
                namespace_value(namespace),
            )
        except ValueError:
            raise CacheValidationError("Invalid cache namespace") from None

    def _key(self, cache_key: str, namespace: str) -> tuple[str, int, str, str]:
        self._state.check_open()
        try:
            key = cache_key_value(cache_key)
        except ValueError:
            raise CacheValidationError("Invalid cache key") from None
        return (*self._scope(namespace), key)

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        """Select the exact cosine winner in SQL without confirming a hit.

        Eligibility filters space identity, dimensions, namespace and PostgreSQL
        clock expiry before comparison. Stored pgvector components are float32;
        near-threshold scores can differ from MemoryStore's float64 results.
        Search does not change hit metadata or LRU and applies no facade threshold.

        Args:
            embedding: Finite, nonzero vector with the bound dimensions.
            namespace: Exact namespace; authorization belongs to the caller.

        Returns:
            Detached validated candidate with a score clamped to [-1, 1], or None
            if no eligible row exists. Ties use ascending created_at, then key.
            Expiry/replacement can intervene afterward; record_hit must confirm it.

        Raises:
            CacheValidationError: If the vector or namespace is invalid.
            CacheStoreError: For invalid persisted evidence, layout or driver failures.
            CacheTimeoutError: If the database operation deadline expires.
        """

        scope = self._scope(namespace)
        try:
            vector = normalized_vector(
                embedding, dimensions=self.embedding_space.dimensions
            )
        except ValueError:
            raise CacheValidationError("Invalid query vector") from None
        literal = "[" + ",".join(str(float(v)) for v in vector) + "]"
        async with self._connection() as connection:
            layout = await self._layout(connection, require_schema=True)
            # Keep eligibility materialized before variable-dimension distance,
            # then fence the native-vector winner before text/payload projection.
            # Only its embedding is serialized; validation below remains complete.
            row = await connection.fetchrow(
                f"""
                WITH eligible AS MATERIALIZED (
                    SELECT * FROM {layout["entries"]}
                    WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3
                      AND (expires_at IS NULL OR expires_at>clock_timestamp())
                ), winner AS MATERIALIZED (
                    SELECT cache_key, namespace, prompt, response, embedding,
                           created_at, expires_at,
                           embedding {layout["cosine"]} $4::{layout["vector"]} AS distance
                    FROM eligible ORDER BY distance, created_at, cache_key LIMIT 1
                )
                SELECT cache_key, namespace, prompt, response, embedding::text AS embedding,
                       created_at, expires_at, 1-distance AS score
                FROM winner
            """,
                *scope,
                literal,
            )
        if row is None:
            return None
        try:
            raw = row["embedding"]
            if (
                not isinstance(raw, str)
                or len(raw) > 1048576
                or not raw.startswith("[")
                or not raw.endswith("]")
            ):
                raise ValueError("Malformed persisted vector")
            components = raw[1:-1].split(",", self.embedding_space.dimensions)
            values = tuple(float(v) for v in components)
            normalized_vector(values, dimensions=self.embedding_space.dimensions)
            score = finite_number(row["score"], minimum=-1.000001, maximum=1.000001)
            return CacheMatch(
                entry=CacheEntry(
                    cache_key=row["cache_key"],
                    namespace=row["namespace"],
                    prompt=row["prompt"],
                    response=row["response"],
                    embedding=values,
                    created_at=row["created_at"],
                ),
                similarity_score=max(-1.0, min(1.0, score)),
                expires_at=row["expires_at"],
            )
        except ValueError:
            raise CacheStoreError("Invalid persisted cache entry") from None

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        """Confirm a live revision atomically under the binding advisory lock.

        Args:
            cache_key: Candidate key in the bound space.
            namespace: Exact candidate namespace.
            expected_created_at: Timezone-aware revision from the candidate entry.

        Returns:
            True after committing a hit increment, server last-access timestamp
            and LRU promotion. Revision/expiry do not change. False for an absent,
            expired, foreign or replaced candidate, without successful-hit effects.

        Raises:
            CacheValidationError: If the key, namespace or revision is invalid.
        """

        scope = self._key(cache_key, namespace)
        if (
            not isinstance(expected_created_at, datetime)
            or expected_created_at.tzinfo is None
            or expected_created_at.utcoffset() is None
        ):
            raise CacheValidationError("Expected revision must be timezone-aware")
        async with self._connection() as connection, connection.transaction():
            layout = await self._layout(connection, require_schema=True)
            await self._lock(connection)
            result = await connection.fetchval(
                f"""
                WITH bumped AS (
                    UPDATE {layout["bindings"]} SET access_order=access_order+1
                    WHERE embedding_space=$1 AND embedding_dimensions=$2
                      AND EXISTS (SELECT 1 FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                          AND namespace=$3 AND cache_key=$4 AND created_at=$5
                          AND (expires_at IS NULL OR expires_at>clock_timestamp()))
                    RETURNING access_order
                )
                UPDATE {layout["entries"]} SET hit_count=hit_count+1, last_accessed_at=clock_timestamp(),
                    access_order=(SELECT access_order FROM bumped)
                WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3 AND cache_key=$4 AND created_at=$5
                  AND (expires_at IS NULL OR expires_at>clock_timestamp()) AND EXISTS (SELECT 1 FROM bumped)
                RETURNING TRUE
            """,
                *scope,
                expected_created_at,
            )
        return result is True

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        """Upsert and enforce binding-wide capacity in one locked SQL transaction.

        Allocate an increasing revision, reset hit metadata and TTL, promote LRU,
        clean at most 500 expired rows explicitly and remove capacity overflow
        before commit. Revision history survives delete/clear. Expected failures
        roll back the transaction; a lost commit acknowledgement is not replayed.

        Args:
            entry: Valid CacheEntry from this space, with matching dimensions.
                Identity provenance is caller-owned; PostgreSQL rejects response NUL.
            ttl_seconds: None inherits the default. A positive finite TTL up to
                31,536,000 seconds is capped by a finite default; both values None
                mean no expiry. Retention starts at the database write clock,
                resets on replacement and never slides on hits.

        Raises:
            CacheStoreError: If entry/TTL validation fails, or for expected layout
                or database failures.
            CacheTimeoutError: If the operation deadline expires.
        """

        self._state.check_open()
        try:
            if not isinstance(cast(object, entry), CacheEntry):
                raise CacheStoreError("Invalid stored entry")
            entry = CacheEntry.model_validate(entry.model_dump())
            if "\0" in entry.response:
                raise ValueError("PostgreSQL text cannot contain NUL")
            vector = normalized_vector(
                entry.embedding, dimensions=self.embedding_space.dimensions
            )
            ttl = resolve_ttl(ttl_seconds, self.default_ttl_seconds)
        except ValueError:
            raise CacheStoreError("Invalid stored entry or TTL") from None
        space, dimensions = (
            self.embedding_space.identity,
            self.embedding_space.dimensions,
        )
        literal = "[" + ",".join(str(float(v)) for v in vector) + "]"
        async with self._connection() as connection, connection.transaction():
            layout = await self._layout(connection, require_schema=True)
            await self._lock(connection)
            await connection.execute(
                f"INSERT INTO {layout['bindings']} (embedding_space, embedding_dimensions) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                space,
                dimensions,
            )
            revision = await connection.fetchrow(
                f"""
                UPDATE {layout["bindings"]} SET revision=GREATEST($3, COALESCE(revision+INTERVAL '1 microsecond',$3)), access_order=access_order+1
                WHERE embedding_space=$1 AND embedding_dimensions=$2 RETURNING revision, access_order
            """,
                space,
                dimensions,
                entry.created_at,
            )
            if revision is None:
                raise CacheStoreError("Cache binding state could not be updated")
            await connection.execute(
                f"""
                DELETE FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                    AND cache_key IN (SELECT cache_key FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                    AND expires_at<=clock_timestamp() ORDER BY expires_at, cache_key LIMIT 500)
            """,
                space,
                dimensions,
            )
            await connection.execute(
                f"""
                INSERT INTO {layout["entries"]} (embedding_space, embedding_dimensions, cache_key, namespace, prompt, response,
                    embedding, created_at, expires_at, access_order)
                VALUES ($1,$2,$3,$4,$5,$6,$7::{layout["vector"]},$8,
                    CASE WHEN $9::double precision IS NULL THEN NULL ELSE clock_timestamp()+$9*INTERVAL '1 second' END,$10)
                ON CONFLICT (embedding_space, embedding_dimensions, cache_key) DO UPDATE SET
                    namespace=EXCLUDED.namespace, prompt=EXCLUDED.prompt, response=EXCLUDED.response, embedding=EXCLUDED.embedding,
                    created_at=EXCLUDED.created_at, expires_at=EXCLUDED.expires_at, access_order=EXCLUDED.access_order,
                    hit_count=0, last_accessed_at=NULL
            """,
                space,
                dimensions,
                entry.cache_key,
                entry.namespace,
                entry.prompt,
                entry.response,
                literal,
                revision["revision"],
                ttl,
                revision["access_order"],
            )
            await connection.execute(
                f"""
                DELETE FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2 AND cache_key IN (
                    SELECT cache_key FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                    ORDER BY (expires_at IS NULL OR expires_at>clock_timestamp()) DESC, access_order DESC, created_at DESC, cache_key
                    OFFSET $3)
            """,
                space,
                dimensions,
                self._config.capacity,
            )

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        """Delete a live key in the exact space/namespace under the binding lock.

        Returns:
            True if a live row was removed, otherwise False. Revision history
            and other namespaces/spaces are preserved.

        Raises:
            CacheValidationError: If the key or namespace is invalid.
        """

        scope = self._key(cache_key, namespace)
        async with self._connection() as connection, connection.transaction():
            layout = await self._layout(connection, require_schema=True)
            await self._lock(connection)
            result = await connection.fetchval(
                f"""
                DELETE FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3 AND cache_key=$4
                    AND (expires_at IS NULL OR expires_at>clock_timestamp()) RETURNING TRUE
            """,
                *scope,
            )
        return result is True

    async def clear(self, *, namespace: str) -> int:
        """Delete namespace rows transactionally, retaining binding revision history.

        Returns:
            Number of live rows removed; expired rows are also deleted but not
            counted. Other namespaces and embedding spaces are preserved.

        Raises:
            CacheValidationError: If the namespace is invalid.
        """

        scope = self._scope(namespace)
        async with self._connection() as connection, connection.transaction():
            layout = await self._layout(connection, require_schema=True)
            await self._lock(connection)
            count = await connection.fetchval(
                f"""
                WITH removed AS (DELETE FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2 AND namespace=$3
                    RETURNING expires_at)
                SELECT count(*) FROM removed WHERE expires_at IS NULL OR expires_at>clock_timestamp()
            """,
                *scope,
            )
        return int(count)

    async def _inspect(
        self,
        *,
        namespace: str | None,
        namespaces: tuple[str, ...] | None,
        cache_key: str | None,
        offset: int,
        limit: int,
        search: str | None,
        sort: InspectionSort,
    ) -> InspectionPage:
        inspection_arguments(namespace, offset, limit, search, sort)
        inspection_namespaces(namespaces)
        if cache_key is not None:
            try:
                cache_key = cache_key_value(cache_key)
            except ValueError:
                raise CacheValidationError("Invalid inspection key") from None
        order = {
            "newest": "created_at DESC, cache_key, namespace",
            "oldest": "created_at, cache_key, namespace",
            "most_hit": "hit_count DESC, created_at DESC, cache_key, namespace",
            "nearest_expiry": "expires_at ASC NULLS LAST, created_at DESC, cache_key, namespace",
        }[sort]
        async with (
            self._connection() as connection,
            connection.transaction(isolation="repeatable_read", readonly=True),
        ):
            layout = await self._layout(connection, require_schema=True)
            scope = (
                self.embedding_space.identity,
                self.embedding_space.dimensions,
                namespace,
                list(namespaces) if namespaces is not None else None,
                cache_key,
                None if search is None else search.strip(),
            )
            eligible = f"""SELECT cache_key, namespace, prompt, created_at, expires_at, hit_count, last_accessed_at, access_order FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                AND (expires_at IS NULL OR expires_at>transaction_timestamp())
                AND ($3::text IS NULL OR namespace=$3)
                AND ($4::text[] IS NULL OR namespace=ANY($4))"""
            filtered = "($5::text IS NULL OR cache_key=$5) AND ($6::text IS NULL OR POSITION(LOWER($6) IN LOWER(prompt))>0)"
            total = await connection.fetchval(
                f"SELECT count(*) FROM ({eligible}) eligible WHERE {filtered}", *scope
            )
            rows = await connection.fetch(
                f"""WITH eligible AS MATERIALIZED ({eligible}), ranked AS (
                SELECT *, row_number() OVER (ORDER BY access_order DESC, created_at DESC, cache_key, namespace) AS recency_rank
                FROM eligible), page AS MATERIALIZED (
                SELECT * FROM ranked WHERE {filtered} ORDER BY {order} OFFSET $7 LIMIT $8)
                SELECT page.*, left(e.response,240) AS response_preview,
                    length(e.response)>240 AS response_preview_truncated,
                    CASE WHEN $5::text IS NULL THEN NULL ELSE e.response END AS response,
                    transaction_timestamp() AS observed_at
                FROM page JOIN {layout["entries"]} e
                ON e.embedding_space=$1 AND e.embedding_dimensions=$2
                    AND e.namespace=page.namespace AND e.cache_key=page.cache_key
                ORDER BY {", ".join("page." + field.strip() for field in order.split(","))}""",
                *scope,
                offset,
                limit,
            )
            try:
                metadata = tuple(
                    InspectionEntry(
                        cache_key=row["cache_key"],
                        namespace=row["namespace"],
                        prompt=row["prompt"],
                        response_preview=row["response_preview"],
                        response_preview_truncated=row["response_preview_truncated"],
                        response=row["response"],
                        created_at=row["created_at"],
                        expires_at=row["expires_at"],
                        remaining_ttl_seconds=remaining(
                            row["expires_at"], row["observed_at"]
                        ),
                        hit_count=row["hit_count"],
                        last_accessed_at=row["last_accessed_at"],
                        recency_rank=row["recency_rank"],
                    )
                    for row in rows
                )
            except ValueError:
                raise CacheStoreError(
                    "Invalid PostgreSQL inspection metadata"
                ) from None
            return InspectionPage(
                items=metadata,
                total=int(total),
                offset=offset,
                limit=limit,
                has_more=offset + len(metadata) < int(total),
            )

    async def inspect_entries(
        self,
        *,
        namespace: str | None = None,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort: InspectionSort = "newest",
    ) -> InspectionPage:
        """Observe live metadata in a read-only repeatable-read transaction.

        Count and rank metadata, then limit the page before projecting sensitive
        240-character response previews. Vectors are absent and response is None;
        hits, LRU and expiry are unchanged. Authorize the requested scope first.

        Args:
            namespace: Exact namespace, or None for all in this space binding.
            offset: Nonnegative live offset; later calls can see shifted results.
            limit: Page size from 1 through 100.
            search: Optional trimmed prompt substring, at most 2,000 characters;
                case-insensitive matching uses PostgreSQL LOWER.
            sort: newest, oldest, most_hit or nearest_expiry.

        Returns:
            Detached page whose total and TTL use this transaction's observation.
            Persisted hit/access metadata is not a lease or durability guarantee.

        Raises:
            CacheValidationError: If inspection arguments are invalid.
        """

        return await self._inspect(
            namespace=namespace,
            namespaces=None,
            cache_key=None,
            offset=offset,
            limit=limit,
            search=search,
            sort=sort,
        )

    async def inspect_entry(
        self, cache_key: str, *, namespaces: tuple[str, ...] | None
    ) -> InspectionEntry | None:
        """Observe a live entry and its sensitive full response without hit effects.

        Args:
            cache_key: Canonical key within the bound embedding space.
            namespaces: Caller-authorized tuple; () allows none, None allows all
                namespaces. This filter does not authenticate the caller.

        Returns:
            Detached detail or None if absent, expired or outside the allowed scope,
            using a read-only repeatable-read transaction. No expiry cleanup occurs.

        Raises:
            CacheValidationError: If the key or namespace scope is invalid.
        """

        page = await self._inspect(
            namespace=None,
            namespaces=namespaces,
            cache_key=cache_key,
            offset=0,
            limit=1,
            search=None,
            sort="newest",
        )
        return page.items[0] if page.items else None

    async def clear_all(self) -> int:
        """Administratively delete this space binding's rows across namespaces.

        Returns:
            Live removal count; expired rows are deleted without being counted.
            The transaction retains revision history and other embedding spaces.
            This optional mutation requires caller-owned authorization.
        """
        async with self._connection() as connection, connection.transaction():
            layout = await self._layout(connection, require_schema=True)
            await self._lock(connection)
            count = await connection.fetchval(
                f"""WITH removed AS (DELETE FROM {layout["entries"]}
                WHERE embedding_space=$1 AND embedding_dimensions=$2 RETURNING expires_at)
                SELECT count(*) FROM removed WHERE expires_at IS NULL OR expires_at>clock_timestamp()""",
                self.embedding_space.identity,
                self.embedding_space.dimensions,
            )
        return int(count)

    async def aclose(self) -> None:
        """Seal an idle store and close only an owned pool within its close deadline.

        Borrowed pools remain caller-owned. Owned close directly awaits asyncpg;
        failure/timeout/cancellation terminates remaining owned connections and
        leaves the store sealed. Cancellation propagates. Later close calls return
        without retrying cleanup; async context exit uses this path and propagates
        body exceptions when close succeeds. Persisted entries are retained.

        Raises:
            CacheBusyError: If an admitted operation remains; the store stays open.
            CacheTimeoutError: If owned-pool close exceeds its deadline.
            CacheStoreError: For expected owned-pool close failures.
        """

        if self._state.closed:
            return
        self._state.close()
        if not self._owned:
            return
        failure: SemantixCacheError | None = None
        try:
            async with asyncio.timeout(self._config.close_timeout):
                await self._pool.close()
        except TimeoutError:
            failure = CacheTimeoutError("PostgreSQL pool close deadline expired")
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
            failure = CacheStoreError("PostgreSQL pool could not close")
        finally:
            if not self._pool.is_closing():
                self._pool.terminate()
        if failure is not None:
            raise failure from RuntimeError(str(failure))

    async def __aenter__(self) -> Self:
        self._state.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
