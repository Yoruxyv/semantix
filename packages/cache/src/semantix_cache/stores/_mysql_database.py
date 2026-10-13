"""InnoDB authority and exhaustive snapshot scoring, only on the owned worker."""

# ruff: noqa: S608
# SQL composition uses only fixed module-owned clauses/clock SQL; values are bound.

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np

from .._semantics import (
    cache_key_value,
    namespace_value,
    nearest_index,
    normalized_vector,
    resolve_ttl,
)
from ..errors import CacheConfigurationError, CacheValidationError
from ..models import CacheEntry, CacheMatch
from . import _mysql_schema as schema
from ._mysql_config import Configuration
from ._mysql_format import (
    MAX_INT,
    MAX_PAYLOAD,
    MAX_US,
    decode_entry,
    decode_vector,
    encode_entry,
    micros,
    timestamp,
)
from ._mysql_worker import Job


class Database:
    def __init__(self, config: Configuration) -> None:
        self.config = config

    def open(self, job: Job, *, initialize: bool = False) -> None:
        if initialize:
            with schema.initialize(job), job.transaction(write=True):
                self.binding(job, create=True, write=True)
        else:
            schema.session(job)
            schema.validate(job)
            with job.transaction():
                self.binding(job)

    def binding(
        self, job: Job, *, create: bool = False, write: bool = False
    ) -> tuple[int, int | None, int]:
        digest, dimensions, identity, capacity, ttl = self.config.descriptor
        sql = "SELECT binding_id,identity_utf8,capacity,default_ttl_hex,last_revision_us,access_counter FROM semantix_bindings WHERE identity_sha256=%s AND dimensions=%s"
        rows = job.rows(sql + (" FOR UPDATE" if write else ""), (digest, dimensions))
        if not rows and create:
            job.rows(
                "INSERT INTO semantix_bindings(identity_sha256,dimensions,identity_utf8,capacity,default_ttl_hex) VALUES(%s,%s,%s,%s,%s)",
                self.config.descriptor,
            )
            rows = job.rows(sql + " FOR UPDATE", (digest, dimensions))
        if len(rows) != 1 or rows[0][1:4] != (identity, capacity, ttl):
            raise CacheConfigurationError(
                "MySQL binding is missing or its identity/capacity/TTL policy differs; initialize explicitly"
            )
        binding, _, _, _, revision, access = rows[0]
        if (
            type(binding) is not int
            or binding <= 0
            or type(access) is not int
            or not 0 <= access <= MAX_INT
        ):
            raise ValueError("Invalid MySQL binding ledger")
        if revision is not None:
            timestamp(revision)
        # Binding lock serializes writers; exact entry locks complete before fresh clocks.
        entries = job.rows(
            "SELECT e.cache_key,e.namespace,e.revision_us,e.expires_at_us,e.hit_count,e.last_accessed_at_us,e.access_seq,OCTET_LENGTH(e.vector_blob),OCTET_LENGTH(p.payload_blob) FROM semantix_entries e LEFT JOIN semantix_payloads p USING(binding_id,cache_key) WHERE e.binding_id=%s ORDER BY e.cache_key LIMIT %s"
            + (" FOR UPDATE" if write else ""),
            (binding, capacity + 1),
        )
        if len(entries) > capacity:
            raise ValueError("MySQL binding exceeds capacity")
        for (
            key,
            namespace,
            entry_revision,
            expiry,
            hits,
            accessed,
            sequence,
            vector_size,
            payload_size,
        ) in entries:
            cache_key_value(key.decode("ascii"))
            namespace_value(namespace.decode("ascii"))
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
                or vector_size != 12 + dimensions * 8
                or payload_size is None
                or not 0 < payload_size <= MAX_PAYLOAD
            ):
                raise ValueError("Invalid MySQL entry ledger or payload pairing")
        if job.rows(
            "SELECT 1 FROM semantix_payloads p LEFT JOIN semantix_entries e USING(binding_id,cache_key) WHERE p.binding_id=%s AND e.cache_key IS NULL LIMIT 1",
            (binding,),
        ):
            raise ValueError("Orphan MySQL payload")
        return binding, revision, access

    def authority(
        self, job: Job, *, write: bool = False
    ) -> tuple[int, int | None, int]:
        schema.validate(job)
        return self.binding(job, write=write)

    def put(self, job: Job, entry: CacheEntry, ttl: float | None) -> None:
        entry, vector, payload = encode_entry(entry, self.config.space.dimensions)
        duration = resolve_ttl(ttl, self.config.ttl)
        requested = micros(entry.created_at)
        with job.transaction(write=True):
            binding, last, access = self.authority(job, write=True)
            revision = requested if last is None else max(requested, last + 1)
            if revision > MAX_US or access == MAX_INT:
                raise ValueError("MySQL revision or recency exhausted")
            observed = job.rows("SELECT " + schema.NOW)[0][0]
            expiry = None
            if duration is not None:
                numerator, denominator = duration.as_integer_ratio()
                expiry = observed + numerator * 1000000 // denominator
                timestamp(expiry)
            job.rows(
                "DELETE FROM semantix_entries WHERE binding_id=%s AND expires_at_us<=%s",
                (binding, observed),
            )
            job.rows(
                "INSERT INTO semantix_entries(binding_id,cache_key,namespace,revision_us,expires_at_us,hit_count,last_accessed_at_us,access_seq,vector_blob) VALUES(%s,%s,%s,%s,%s,0,NULL,%s,%s) AS incoming ON DUPLICATE KEY UPDATE namespace=incoming.namespace,revision_us=incoming.revision_us,expires_at_us=incoming.expires_at_us,hit_count=0,last_accessed_at_us=NULL,access_seq=incoming.access_seq,vector_blob=incoming.vector_blob",
                (
                    binding,
                    entry.cache_key.encode("ascii"),
                    entry.namespace.encode("ascii"),
                    revision,
                    expiry,
                    access + 1,
                    vector,
                ),
            )
            job.rows(
                "INSERT INTO semantix_payloads VALUES(%s,%s,%s) AS incoming ON DUPLICATE KEY UPDATE payload_blob=incoming.payload_blob",
                (binding, entry.cache_key.encode("ascii"), payload),
            )
            job.rows(
                "UPDATE semantix_bindings SET last_revision_us=%s,access_counter=%s WHERE binding_id=%s",
                (revision, access + 1, binding),
            )
            job.rows(
                "DELETE FROM semantix_entries WHERE binding_id=%s AND expires_at_us<="
                + schema.NOW,
                (binding,),
            )
            overflow = (
                job.rows(
                    "SELECT count(*) FROM semantix_entries WHERE binding_id=%s",
                    (binding,),
                )[0][0]
                - self.config.capacity
            )
            if overflow > 0:
                victims = job.rows(
                    "SELECT cache_key FROM semantix_entries WHERE binding_id=%s ORDER BY access_seq,revision_us,cache_key LIMIT %s",
                    (binding, overflow),
                )
                for (key,) in victims:
                    job.rows(
                        "DELETE FROM semantix_entries WHERE binding_id=%s AND cache_key=%s",
                        (binding, key),
                    )

    def record_hit(self, job: Job, key: str, namespace: str, expected: int) -> bool:
        with job.transaction(write=True):
            binding, _, access = self.authority(job, write=True)
            parameters = (
                binding,
                namespace.encode("ascii"),
                key.encode("ascii"),
                expected,
            )
            rows = job.rows(
                "SELECT hit_count FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND cache_key=%s AND revision_us=%s AND (expires_at_us IS NULL OR expires_at_us>"
                + schema.NOW
                + ")",
                parameters,
            )
            if not rows:
                return False
            if access == MAX_INT or rows[0][0] == MAX_INT:
                raise ValueError("MySQL hit or recency counter exhausted")
            job.rows(
                "UPDATE semantix_entries SET hit_count=hit_count+1,last_accessed_at_us="
                + schema.NOW
                + ",access_seq=%s WHERE binding_id=%s AND namespace=%s AND cache_key=%s AND revision_us=%s AND (expires_at_us IS NULL OR expires_at_us>"
                + schema.NOW
                + ")",
                (access + 1, *parameters),
            )
            changed = job.affected == 1
            if changed:
                job.rows(
                    "UPDATE semantix_bindings SET access_counter=%s WHERE binding_id=%s",
                    (access + 1, binding),
                )
        return changed

    def delete(self, job: Job, key: str, namespace: str) -> bool:
        with job.transaction(write=True):
            binding, _, _ = self.authority(job, write=True)
            parameters = (binding, namespace.encode("ascii"), key.encode("ascii"))
            live = bool(
                job.rows(
                    "SELECT 1 FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND cache_key=%s AND (expires_at_us IS NULL OR expires_at_us>"
                    + schema.NOW
                    + ")",
                    parameters,
                )
            )
            job.rows(
                "DELETE FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND cache_key=%s",
                parameters,
            )
        return live

    def clear(self, job: Job, namespace: str) -> int:
        with job.transaction(write=True):
            binding, _, _ = self.authority(job, write=True)
            parameters = (binding, namespace.encode("ascii"))
            count = job.rows(
                "SELECT count(*) FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND (expires_at_us IS NULL OR expires_at_us>"
                + schema.NOW
                + ")",
                parameters,
            )[0][0]
            job.rows(
                "DELETE FROM semantix_entries WHERE binding_id=%s AND namespace=%s",
                parameters,
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
            raise CacheValidationError("Invalid MySQL query embedding") from None
        with job.transaction():
            binding, _, _ = self.authority(job)
            observed = job.rows("SELECT " + schema.NOW)[0][0]
            parameters = (binding, namespace.encode("ascii"), observed)
            count = job.rows(
                "SELECT count(*) FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND (expires_at_us IS NULL OR expires_at_us>%s)",
                parameters,
            )[0][0]
            if type(count) is not int or not 0 <= count <= self.config.capacity:
                raise ValueError("Invalid MySQL snapshot size")
            matrix = np.empty((count, self.config.space.dimensions), dtype=np.float64)
            metadata: list[tuple[bytes, int]] = []
            last_revision, last_key = -62135596800000001, b""
            while True:
                page = job.rows(
                    "SELECT cache_key,revision_us,vector_blob FROM semantix_entries WHERE binding_id=%s AND namespace=%s AND (expires_at_us IS NULL OR expires_at_us>%s) AND (revision_us>%s OR (revision_us=%s AND cache_key>%s)) ORDER BY revision_us,cache_key LIMIT 64",
                    (*parameters, last_revision, last_revision, last_key),
                )
                if not page:
                    break
                for key, revision, blob in page:
                    if len(metadata) >= count:
                        raise ValueError("Inconsistent MySQL snapshot")
                    matrix[len(metadata)] = decode_vector(
                        blob, self.config.space.dimensions
                    )
                    metadata.append((key, revision))
                last_key, last_revision = metadata[-1]
            if len(metadata) != count:
                raise ValueError("Incomplete MySQL snapshot")
        if count == 0:
            return None
        # End the snapshot before using the unchanged complete float64 kernel.
        index, score = nearest_index(query, cast(Sequence[Sequence[float]], matrix))
        job.check()
        key, revision = metadata[index]
        with job.transaction():
            binding, _, _ = self.authority(job)
            rows = job.rows(
                "SELECT p.payload_blob,e.vector_blob,e.expires_at_us FROM semantix_entries e JOIN semantix_payloads p USING(binding_id,cache_key) WHERE e.binding_id=%s AND e.namespace=%s AND e.cache_key=%s AND e.revision_us=%s AND (e.expires_at_us IS NULL OR e.expires_at_us>"
                + schema.NOW
                + ")",
                (binding, namespace.encode("ascii"), key, revision),
            )
            if not rows:
                return None
            payload, vector, expiry = rows[0]
            entry = decode_entry(
                payload,
                vector,
                key.decode("ascii"),
                namespace,
                revision,
                self.config.space.dimensions,
            )
            return CacheMatch(
                entry=entry,
                similarity_score=score,
                expires_at=None if expiry is None else timestamp(expiry),
            )
