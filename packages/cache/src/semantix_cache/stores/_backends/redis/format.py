"""Pure Redis binary evidence, exact scoring and safe errors; no client ownership."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast

import numpy as np
from numpy.typing import NDArray

from ...._semantics import (
    cache_key_value,
    namespace_value,
    nearest_index,
    normalized_vector,
)
from ....errors import CacheStoreError, SemantixCacheError
from ....models import CacheEntry, CacheMatch

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _raise_safe(error: SemantixCacheError) -> NoReturn:
    # asynccontextmanager throws the raw body exception back into the generator.
    # Clear implicit chaining after the raise; bare re-raise preserves this chain.
    try:
        raise error from RuntimeError(str(error))
    except SemantixCacheError:
        error.__context__ = None
        raise


def _micros(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Expected an aware datetime")
    delta = value.astimezone(UTC) - _EPOCH
    return str((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds)


def _datetime(value: bytes) -> datetime:
    return _EPOCH + timedelta(microseconds=int(value))


def _row(raw: object) -> tuple[bytes, bytes, bytes, bytes]:
    if not isinstance(raw, list):
        raise TypeError("Invalid Redis response row")
    parts = cast(list[object], raw)
    if len(parts) != 4 or not all(isinstance(part, bytes) for part in parts):
        raise ValueError("Invalid Redis response row")
    return cast(tuple[bytes, bytes, bytes, bytes], tuple(parts))


def _score(
    query: NDArray[np.float64], rows: object, dimensions: int, namespace: str
) -> tuple[bytes, bytes, float] | None:
    try:
        if not isinstance(rows, list):
            raise TypeError("Invalid snapshot")
        candidates: list[tuple[int, str, bytes, bytes, NDArray[np.float64]]] = []
        for row in cast(list[object], rows):
            member, revision, expiry, blob = _row(row)
            scope, key = member.decode("ascii").split("|")
            if namespace_value(scope) != namespace:
                raise ValueError("Invalid snapshot scope")
            cache_key_value(key)
            _datetime(revision)
            if expiry:
                _datetime(expiry)
            if len(blob) != dimensions * 8:
                raise ValueError("Invalid stored vector")
            vector = np.frombuffer(blob, dtype="<f8")
            candidates.append((int(revision), key, member, revision, vector))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if not candidates:
            return None
        vectors = cast(Sequence[Sequence[float]], [row[4] for row in candidates])
        # Packed <f8 already guarantees numeric component types and dimensions.
        # Validate finite magnitudes with NumPy, then reuse the shared cosine kernel.
        matrix = np.asarray(vectors, dtype=np.float64)
        with np.errstate(over="ignore", invalid="ignore"):
            valid = (
                np.isfinite(matrix).all()
                and np.isfinite(np.linalg.norm(matrix, axis=1)).all()
            )
        if not valid:
            raise ValueError("Invalid stored vector magnitude")
        index, similarity = nearest_index(
            query, cast(Sequence[Sequence[float]], matrix)
        )
        return candidates[index][2], candidates[index][3], similarity
    except (ValueError, TypeError, OverflowError):
        _raise_safe(CacheStoreError("Invalid stored Redis vector snapshot"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate payload key")
        result[key] = value
    return result


def _decode(
    raw: object, member: bytes, dimensions: int, similarity: float
) -> CacheMatch:
    try:
        payload, blob, revision, expiry = _row(raw)
        try:
            values: object = json.loads(
                payload.decode("utf-8"), object_pairs_hook=_unique_object
            )
        except RecursionError:
            _raise_safe(CacheStoreError("Invalid stored Redis winner"))
        if not isinstance(values, dict):
            raise TypeError("Invalid payload")
        data = cast(dict[object, object], values)
        if set(data) != {"cache_key", "namespace", "prompt", "response"} or not all(
            isinstance(v, str) for v in data.values()
        ):
            raise ValueError("Invalid payload")
        strings = cast(dict[str, str], data)
        scope, key = member.decode("ascii").split("|")
        if strings["namespace"] != scope or strings["cache_key"] != key:
            raise ValueError("Invalid payload scope")
        if len(blob) != dimensions * 8:
            raise ValueError("Invalid stored vector")
        vector = np.frombuffer(blob, dtype="<f8")
        normalized_vector(cast(Sequence[float], vector), dimensions=dimensions)
        entry = CacheEntry(
            cache_key=strings["cache_key"],
            namespace=strings["namespace"],
            prompt=strings["prompt"],
            response=strings["response"],
            embedding=tuple(float(v) for v in vector),
            created_at=_datetime(revision),
        )
        return CacheMatch(
            entry=entry,
            similarity_score=similarity,
            expires_at=None if not expiry else _datetime(expiry),
        )
    except (ValueError, TypeError, OverflowError):
        _raise_safe(CacheStoreError("Invalid stored Redis winner"))
