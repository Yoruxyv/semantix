"""MySQL-only frozen codecs; independent of sqlite3 and SQLite lifecycle."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast

import numpy as np
from numpy.typing import NDArray

from .._semantics import normalized_vector
from ..errors import CacheStoreError, SemantixCacheError
from ..models import CacheEntry

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MIN_US = -62135596800000000
MAX_US = 253402300799999999
MAX_INT = 9223372036854775807
MAX_PAYLOAD = 1230000
HEADER = struct.Struct("<4sBBHI")


def safe(error: SemantixCacheError) -> NoReturn:
    try:
        raise error from None
    except SemantixCacheError:
        error.__context__ = None
        raise


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
        safe(CacheStoreError("Invalid MySQL entry"))


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate payload field")
        result[key] = value
    return result


def decode_entry(
    payload: bytes,
    vector: bytes,
    key: str,
    namespace: str,
    revision: int,
    dimensions: int,
) -> CacheEntry:
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
    result = CacheEntry(
        **cast(dict[str, str], values),
        embedding=tuple(decode_vector(vector, dimensions)),
        created_at=timestamp(revision),
    )
    if result.prompt != values["prompt"]:
        raise ValueError("Noncanonical stored prompt")
    return result
