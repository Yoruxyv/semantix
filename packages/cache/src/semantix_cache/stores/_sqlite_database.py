"""SQLite persistence and transaction authority; called only on the owned worker."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from time import monotonic, time_ns
from typing import cast

import numpy as np

from .._semantics import (
    cache_key_value,
    namespace_value,
    nearest_index,
    normalized_vector,
    resolve_ttl,
)
from ..errors import CacheConfigurationError, CacheStoreError, CacheValidationError
from ..models import CacheEntry, CacheMatch
from ._sqlite_format import (
    APPLICATION_ID,
    CHECKSUM,
    MAX_INT,
    MAX_PAYLOAD,
    MAX_US,
    OWNER,
    STATEMENTS,
    Configuration,
    checked_path,
    decode_entry,
    decode_vector,
    encode_entry,
    micros,
    safe,
    schema_shape,
    sqlite3,
    timestamp,
)
from ._sqlite_worker import Job


def now_us() -> int:
    return time_ns() // 1000


class Database:
    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.schema_version: int | None = None

    def open(self, job: Job, *, initialize: bool = False) -> None:
        path = checked_path(self.config.path)
        created = False
        if initialize:
            try:
                with path.open("xb"):
                    created = True
            except FileExistsError:
                pass
        options = {"autocommit": True} if sys.version_info >= (3, 12) else {}
        connection = sqlite3.connect(
            path.as_uri() + "?mode=rw",
            uri=True,
            timeout=0,
            isolation_level=None,
            check_same_thread=True,
            **options,
        )
        job.owner.bind(connection)
        connection.set_progress_handler(
            lambda: int(job.stopped.is_set() or monotonic() >= job.deadline),
            1000,
        )
        connection.create_function("semantix_now_us", 0, now_us, deterministic=False)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_PAYLOAD + 4096)
        if hasattr(connection, "setconfig"):
            defensive = "SQLITE_DBCONFIG_DEFENSIVE"
            connection.setconfig(getattr(sqlite3, defensive), True)
        for setting in (
            "trusted_schema=OFF",
            "foreign_keys=ON",
            "read_uncommitted=OFF",
            "synchronous=FULL",
            "cache_size=-8192",
            "mmap_size=0",
            "wal_autocheckpoint=1000",
        ):
            job.rows("PRAGMA " + setting)
        if created:
            if job.rows("PRAGMA journal_mode=WAL") != [("wal",)]:
                raise CacheStoreError("SQLite WAL is unavailable")
        elif job.rows("PRAGMA journal_mode") != [("wal",)]:
            raise CacheStoreError("SQLite file is not an initialized WAL cache")
        if job.rows("PRAGMA foreign_keys") != [(1,)] or job.rows(
            "PRAGMA synchronous"
        ) != [(2,)]:
            raise CacheStoreError("SQLite connection safety policy is unavailable")
        with job.transaction(write=initialize):
            if created:
                for statement in STATEMENTS:
                    job.rows(statement)
                job.rows(
                    "INSERT INTO schema_migrations VALUES(1,?,?)", (OWNER, CHECKSUM)
                )
                job.rows(f"PRAGMA application_id={APPLICATION_ID}")
                job.rows("PRAGMA user_version=1")
            self.validate_schema(job)
            self.binding(job, create=initialize)

    def validate_schema(self, job: Job) -> None:
        if job.rows("PRAGMA application_id") != [(APPLICATION_ID,)] or job.rows(
            "PRAGMA user_version"
        ) != [(1,)]:
            raise CacheStoreError("SQLite file ownership or schema version is invalid")
        if job.rows("SELECT version,owner,checksum FROM schema_migrations LIMIT 2") != [
            (1, OWNER, CHECKSUM)
        ]:
            raise CacheStoreError("SQLite migration ledger is invalid")
        version = job.rows("PRAGMA schema_version")[0][0]
        if self.schema_version != version:
            shape = {
                name: " ".join(sql.split())
                for name, sql in job.rows(
                    "SELECT name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY name LIMIT 9"
                )
            }
            if shape != schema_shape():
                raise CacheStoreError("SQLite schema shape is invalid")
            self.schema_version = version

    def binding(self, job: Job, *, create: bool = False) -> tuple[int, int | None, int]:
        identity, dimensions, capacity, ttl = self.config.descriptor
        rows = job.rows(
            "SELECT binding_id,capacity,default_ttl_hex,last_revision_us,access_counter FROM binding_state WHERE identity=? AND dimensions=?",
            (identity, dimensions),
        )
        if not rows and create:
            job.rows(
                "INSERT INTO binding_state(identity,dimensions,capacity,default_ttl_hex,access_counter) VALUES(?,?,?,?,0)",
                self.config.descriptor,
            )
            rows = job.rows(
                "SELECT binding_id,capacity,default_ttl_hex,last_revision_us,access_counter FROM binding_state WHERE identity=? AND dimensions=?",
                (identity, dimensions),
            )
        if len(rows) != 1 or rows[0][1:3] != (capacity, ttl):
            raise CacheConfigurationError(
                "SQLite binding is missing or its capacity/TTL policy differs; initialize it explicitly"
            )
        binding_id, _, _, revision, access = rows[0]
        if (
            type(binding_id) is not int
            or binding_id <= 0
            or type(access) is not int
            or not 0 <= access <= MAX_INT
        ):
            raise ValueError("Invalid binding ledger")
        if revision is not None:
            timestamp(revision)
        # Inspect only bounded metadata, never foreign namespace payload contents.
        entries = job.rows(
            "SELECT e.cache_key,e.namespace,e.revision_us,e.expires_at_us,e.hit_count,e.last_accessed_at_us,e.access_seq,length(e.vector_blob),length(p.payload_blob) FROM cache_entries e LEFT JOIN cache_payloads p USING(binding_id,cache_key) WHERE e.binding_id=? LIMIT ?",
            (binding_id, capacity + 1),
        )
        if len(entries) > capacity:
            raise ValueError("Binding exceeds capacity")
        for (
            key,
            namespace,
            entry_revision,
            expiry,
            hits,
            accessed,
            sequence,
            vector_length,
            payload_length,
        ) in entries:
            cache_key_value(key)
            namespace_value(namespace)
            timestamp(entry_revision)
            if expiry is not None:
                timestamp(expiry)
            if accessed is not None:
                timestamp(accessed)
            if (
                revision is None
                or entry_revision > revision
                or type(sequence) is not int
                or not 0 < sequence <= access
                or type(hits) is not int
                or not 0 <= hits <= MAX_INT
                or (hits == 0) != (accessed is None)
                or vector_length != 12 + dimensions * 8
                or payload_length is None
                or not 0 < payload_length <= MAX_PAYLOAD
            ):
                raise ValueError("Invalid entry ledger or payload pairing")
        if job.rows(
            "SELECT 1 FROM cache_payloads p LEFT JOIN cache_entries e USING(binding_id,cache_key) WHERE p.binding_id=? AND e.cache_key IS NULL LIMIT 1",
            (binding_id,),
        ):
            raise ValueError("Orphan payload")
        return binding_id, revision, access

    def authority(self, job: Job) -> tuple[int, int | None, int]:
        self.validate_schema(job)
        return self.binding(job)

    def put(self, job: Job, entry: CacheEntry, ttl: float | None) -> None:
        entry, vector, payload = encode_entry(entry, self.config.space.dimensions)
        try:
            duration = resolve_ttl(ttl, self.config.ttl)
            requested = micros(entry.created_at)
        except (ValueError, TypeError, OverflowError):
            safe(CacheStoreError("Invalid SQLite entry TTL or revision"))
        with job.transaction(write=True):
            binding, last, access = self.authority(job)
            revision = requested if last is None else max(requested, last + 1)
            if revision > MAX_US or access == MAX_INT:
                raise ValueError("Revision or recency exhausted")
            observed = now_us()
            expiry = None
            if duration is not None:
                numerator, denominator = duration.as_integer_ratio()
                expiry = observed + numerator * 1000000 // denominator
                timestamp(expiry)
            job.rows(
                "DELETE FROM cache_entries WHERE binding_id=? AND expires_at_us<=?",
                (binding, observed),
            )
            job.rows(
                "INSERT INTO cache_entries VALUES(?,?,?,?,?,?,0,NULL,?) ON CONFLICT(binding_id,cache_key) DO UPDATE SET namespace=excluded.namespace,vector_blob=excluded.vector_blob,revision_us=excluded.revision_us,expires_at_us=excluded.expires_at_us,hit_count=0,last_accessed_at_us=NULL,access_seq=excluded.access_seq",
                (
                    binding,
                    entry.cache_key,
                    entry.namespace,
                    vector,
                    revision,
                    expiry,
                    access + 1,
                ),
            )
            job.rows(
                "INSERT INTO cache_payloads VALUES(?,?,?) ON CONFLICT(binding_id,cache_key) DO UPDATE SET payload_blob=excluded.payload_blob",
                (binding, entry.cache_key, payload),
            )
            job.rows(
                "UPDATE binding_state SET last_revision_us=?,access_counter=? WHERE binding_id=?",
                (revision, access + 1, binding),
            )
            job.rows(
                "DELETE FROM cache_entries WHERE binding_id=? AND expires_at_us<=?",
                (binding, now_us()),
            )
            overflow = (
                job.rows(
                    "SELECT count(*) FROM cache_entries WHERE binding_id=?", (binding,)
                )[0][0]
                - self.config.capacity
            )
            if overflow > 0:
                job.rows(
                    "DELETE FROM cache_entries WHERE binding_id=? AND cache_key IN (SELECT cache_key FROM cache_entries WHERE binding_id=? ORDER BY access_seq,revision_us,cache_key LIMIT ?)",
                    (binding, binding, overflow),
                )

    def record_hit(self, job: Job, key: str, namespace: str, expected: int) -> bool:
        changed = False
        with job.transaction(write=True):
            binding, _, access = self.authority(job)
            row = job.rows(
                "SELECT hit_count FROM cache_entries WHERE binding_id=? AND namespace=? AND cache_key=? AND revision_us=?",
                (binding, namespace, key, expected),
            )
            if row:
                if access == MAX_INT or row[0][0] == MAX_INT:
                    # Expired candidates still return false without allocating recency.
                    if job.rows(
                        "SELECT 1 FROM cache_entries WHERE binding_id=? AND namespace=? AND cache_key=? AND revision_us=? AND (expires_at_us IS NULL OR expires_at_us>semantix_now_us())",
                        (binding, namespace, key, expected),
                    ):
                        raise ValueError("Hit or recency counter exhausted")
                else:
                    result = job.rows(
                        "WITH observation AS MATERIALIZED (SELECT semantix_now_us() AS now_us) UPDATE cache_entries SET hit_count=hit_count+1,last_accessed_at_us=(SELECT now_us FROM observation),access_seq=? WHERE binding_id=? AND namespace=? AND cache_key=? AND revision_us=? AND (expires_at_us IS NULL OR expires_at_us>(SELECT now_us FROM observation)) RETURNING cache_key",
                        (access + 1, binding, namespace, key, expected),
                    )
                    changed = result == [(key,)]
                    if changed:
                        job.rows(
                            "UPDATE binding_state SET access_counter=? WHERE binding_id=?",
                            (access + 1, binding),
                        )
        return changed

    def delete(self, job: Job, key: str, namespace: str) -> bool:
        with job.transaction(write=True):
            binding, _, _ = self.authority(job)
            live = bool(
                job.rows(
                    "SELECT 1 FROM cache_entries WHERE binding_id=? AND namespace=? AND cache_key=? AND (expires_at_us IS NULL OR expires_at_us>semantix_now_us())",
                    (binding, namespace, key),
                )
            )
            job.rows(
                "DELETE FROM cache_entries WHERE binding_id=? AND namespace=? AND cache_key=?",
                (binding, namespace, key),
            )
        return live

    def clear(self, job: Job, namespace: str) -> int:
        with job.transaction(write=True):
            binding, _, _ = self.authority(job)
            count = job.rows(
                "SELECT count(*) FROM cache_entries WHERE binding_id=? AND namespace=? AND (expires_at_us IS NULL OR expires_at_us>?)",
                (binding, namespace, now_us()),
            )[0][0]
            job.rows(
                "DELETE FROM cache_entries WHERE binding_id=? AND namespace=?",
                (binding, namespace),
            )
        return cast(int, count)

    def find(
        self, job: Job, embedding: tuple[float, ...], namespace: str
    ) -> CacheMatch | None:
        try:
            query = normalized_vector(
                embedding, dimensions=self.config.space.dimensions
            )
        except (ValueError, TypeError, OverflowError):
            safe(CacheValidationError("Invalid SQLite query embedding"))
        with job.transaction():
            binding, _, _ = self.authority(job)
            observed = now_us()
            parameters = (binding, namespace, observed)
            count = job.rows(
                "SELECT count(*) FROM cache_entries WHERE binding_id=? AND namespace=? AND (expires_at_us IS NULL OR expires_at_us>?)",
                parameters,
            )[0][0]
            if not 0 <= count <= self.config.capacity:
                raise ValueError("Invalid snapshot size")
            matrix = np.empty((count, self.config.space.dimensions), dtype=np.float64)
            metadata: list[tuple[str, int]] = []
            job.prepare()
            cursor = job.connection.execute(
                "SELECT cache_key,revision_us,vector_blob FROM cache_entries WHERE binding_id=? AND namespace=? AND (expires_at_us IS NULL OR expires_at_us>?) ORDER BY revision_us,cache_key",
                parameters,
            )
            try:
                while batch := cursor.fetchmany(64):
                    job.check()
                    for key, revision, blob in batch:
                        if len(metadata) >= count:
                            raise ValueError("Inconsistent snapshot")
                        matrix[len(metadata)] = decode_vector(
                            blob, self.config.space.dimensions
                        )
                        metadata.append((key, revision))
            finally:
                cursor.close()
            if len(metadata) != count:
                raise ValueError("Incomplete snapshot")
        if count == 0:
            return None
        # End the WAL snapshot before the full shared float64 numerical kernel.
        index, score = nearest_index(query, cast(Sequence[Sequence[float]], matrix))
        job.check()
        key, revision = metadata[index]
        with job.transaction():
            current_binding, _, _ = self.authority(job)
            rows = job.rows(
                "SELECT p.payload_blob,e.vector_blob,e.expires_at_us FROM cache_entries e LEFT JOIN cache_payloads p USING(binding_id,cache_key) WHERE e.binding_id=? AND e.namespace=? AND e.cache_key=? AND e.revision_us=? AND (e.expires_at_us IS NULL OR e.expires_at_us>?)",
                (current_binding, namespace, key, revision, now_us()),
            )
            if not rows:
                return None
            payload, vector, expiry = rows[0]
            entry = decode_entry(
                payload, vector, key, namespace, revision, self.config.space.dimensions
            )
            return CacheMatch(
                entry=entry,
                similarity_score=score,
                expires_at=None if expiry is None else timestamp(expiry),
            )
