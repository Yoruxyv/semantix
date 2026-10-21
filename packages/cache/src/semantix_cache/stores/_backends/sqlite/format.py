"""SQLite-only configuration, frozen schema and lossless storage codecs."""

from __future__ import annotations

import json
import os
import re
import stat
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import NoReturn, cast

import numpy as np
from numpy.typing import NDArray

from ...._semantics import (
    cache_key_value,
    canonical_prompt,
    finite_number,
    namespace_value,
    normalized_vector,
    prompt_cache_key,
    resolve_ttl,
    valid_response,
)
from ....errors import CacheConfigurationError, CacheStoreError, SemantixCacheError
from ....models import CacheEntry, EmbeddingSpace

try:
    import sqlite3
except ImportError:
    raise ImportError(
        "SQLiteStore needs Python's standard-library sqlite3 module"
    ) from None

__all__ = ["sqlite3"]

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MIN_US = -62135596800000000
MAX_US = 253402300799999999
MAX_INT = 9223372036854775807
MAX_PAYLOAD = 1230000
OWNER = "semantix-cache:sqlite:v1"
APPLICATION_ID = 0x534D5843
MIGRATION = (
    files("semantix_cache.stores._backends.sqlite.migrations")
    .joinpath("0001_cache.sql")
    .read_bytes()
)
CHECKSUM = sha256(MIGRATION).hexdigest()
STATEMENTS = tuple(
    part.strip() for part in MIGRATION.decode("utf-8").split(";") if part.strip()
)
HEADER = struct.Struct("<4sBBHI")


def safe(error: SemantixCacheError) -> NoReturn:
    try:
        raise error from None
    except SemantixCacheError:
        error.__context__ = None
        raise


def runtime_gate() -> None:
    # Upstream's WAL-reset fixes also exist in these two exercised backports.
    version = sqlite3.sqlite_version_info
    if (
        sqlite3.threadsafety == 0
        or (version < (3, 51, 3) and version not in ((3, 44, 6), (3, 50, 7)))
        or version == (3, 52, 0)
    ):
        raise CacheConfigurationError(
            "SQLiteStore requires thread-capable SQLite >=3.51.3, excluding withdrawn 3.52.0, "
            "or WAL-patched upstream 3.44.6/3.50.7; "
            "use a supported Python runtime or another store"
        )


def timeout(value: float) -> float:
    result = finite_number(value, minimum=0.0, maximum=86400.0)
    if result == 0:
        raise ValueError("Invalid timeout")
    return result


def checked_path(value: str | os.PathLike[str]) -> Path:
    raw = os.fspath(value)
    if (
        not isinstance(raw, str)
        or not raw
        or "\0" in raw
        or raw == ":memory:"
        or raw.lower().startswith("file:")
        or raw.startswith(("\\\\", "//"))
    ):
        raise ValueError("Invalid database path")
    path = Path(raw).absolute()
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part != path:
                raise ValueError("Missing parent directory") from None
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError("Linked paths are unsupported")
        if part == path and not stat.S_ISREG(info.st_mode):
            raise ValueError("Database must be a regular file")
    # Reparse checks precede canonicalization; ordinary Windows 8.3 aliases are safe.
    return path.resolve()


@dataclass(frozen=True)
class Configuration:
    path: Path
    space: EmbeddingSpace
    capacity: int
    ttl: float | None
    timeout: float
    close_timeout: float

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        space: EmbeddingSpace,
        capacity: int,
        ttl: float | None,
        operation_timeout: float,
        close_timeout: float,
    ) -> Configuration:
        runtime_gate()
        try:
            validated = EmbeddingSpace.model_validate(space.model_dump())
            validated.identity.encode("utf-8")
            if (
                len(validated.identity) > 1024
                or "\0" in validated.identity
                or validated.dimensions > 16000
                or isinstance(capacity, bool)
                or not isinstance(capacity, int)
                or not 1 <= capacity <= 5000
                or capacity * validated.dimensions * 8 > 64 * 1024 * 1024
            ):
                raise ValueError("Invalid bounds")
            return cls(
                checked_path(path),
                validated,
                capacity,
                resolve_ttl(None, ttl),
                timeout(operation_timeout),
                timeout(close_timeout),
            )
        except (ValueError, TypeError, AttributeError, OSError):
            safe(
                CacheConfigurationError(
                    "Invalid SQLite store configuration or file path"
                )
            )

    @property
    def descriptor(self) -> tuple[str, int, int, str | None]:
        return (
            self.space.identity,
            self.space.dimensions,
            self.capacity,
            None if self.ttl is None else self.ttl.hex(),
        )


def micros(value: datetime) -> int:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Expected aware timestamp")
    delta = value.astimezone(UTC) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def timestamp(value: int) -> datetime:
    if type(value) is not int or not MIN_US <= value <= MAX_US:
        raise ValueError("Invalid stored timestamp")
    return EPOCH + timedelta(microseconds=value)


def vector_blob(vector: NDArray[np.float64]) -> bytes:
    return (
        HEADER.pack(b"SMXV", 1, 1, 0, len(vector))
        + vector.astype("<f8", copy=False).tobytes()
    )


def decode_vector(blob: bytes, dimensions: int) -> NDArray[np.float64]:
    if (
        not isinstance(blob, bytes)
        or len(blob) != HEADER.size + dimensions * 8
        or HEADER.unpack_from(blob) != (b"SMXV", 1, 1, 0, dimensions)
    ):
        raise ValueError("Invalid stored vector codec")
    vector = np.frombuffer(blob, dtype="<f8", offset=HEADER.size)
    with np.errstate(over="ignore", invalid="ignore"):
        norm = float(np.linalg.norm(vector))
    if (
        not np.isfinite(vector).all()
        or not np.isfinite(norm)
        or norm <= np.finfo(np.float64).eps
    ):
        raise ValueError("Invalid stored vector")
    return vector


def encode_entry(entry: CacheEntry, dimensions: int) -> tuple[CacheEntry, bytes, bytes]:
    try:
        checked = CacheEntry.model_validate(entry.model_dump())
        vector = normalized_vector(checked.embedding, dimensions=dimensions)
        payload = json.dumps(
            {
                field: getattr(checked, field)
                for field in ("cache_key", "namespace", "prompt", "response")
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("Oversized payload")
        return checked, vector_blob(vector), payload
    except (ValueError, TypeError, AttributeError, OverflowError):
        safe(CacheStoreError("Invalid SQLite entry"))


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate payload field")
        result[key] = value
    return result


def decode_payload(payload: bytes, key: str, namespace: str) -> dict[str, str]:
    """Validate the existing payload codec without materializing a vector."""
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD:
        raise ValueError("Invalid stored payload")
    decoded: object = json.loads(
        payload.decode("ascii"), object_pairs_hook=unique_object
    )
    if not isinstance(decoded, dict):
        raise TypeError("Invalid stored payload object")
    values = cast(dict[str, object], decoded)
    if (
        set(values) != {"cache_key", "namespace", "prompt", "response"}
        or not all(isinstance(value, str) for value in values.values())
        or values["cache_key"] != key
        or values["namespace"] != namespace
    ):
        raise ValueError("Invalid stored payload fields")
    checked = cast(dict[str, str], values)
    prompt = canonical_prompt(checked["prompt"])
    if prompt != checked["prompt"]:
        raise ValueError("Noncanonical stored prompt")
    if prompt_cache_key(
        prompt, namespace=namespace_value(namespace)
    ) != cache_key_value(key):
        raise ValueError("Cache key does not match stored prompt and namespace")
    valid_response(checked["response"])
    return checked


def decode_entry(
    payload: bytes,
    vector: bytes,
    key: str,
    namespace: str,
    revision: int,
    dimensions: int,
) -> CacheEntry:
    return CacheEntry(
        **decode_payload(payload, key, namespace),
        embedding=tuple(decode_vector(vector, dimensions)),
        created_at=timestamp(revision),
    )


def schema_shape() -> dict[str, str]:
    result: dict[str, str] = {}
    for statement in STATEMENTS:
        match = re.search(r"CREATE (?:TABLE|INDEX) (\w+)", statement)
        if match is None:
            raise RuntimeError("Invalid packaged SQLite migration")
        result[match[1]] = " ".join(statement.split())
    return result
