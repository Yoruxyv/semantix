"""Validation and serialization for cache vectors."""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from app.core.exceptions import CacheStorageError


def validated_cache_vector(
    values: Sequence[float] | NDArray[np.float64],
    *,
    dimensions: int,
    description: str,
) -> NDArray[np.float64]:
    vector: NDArray[np.float64] = np.asarray(values, dtype=np.float64)
    if vector.shape != (dimensions,) or not np.isfinite(vector).all():
        raise CacheStorageError(f"{description} embedding is invalid")
    if float(np.linalg.norm(vector)) <= np.finfo(np.float64).eps:
        raise CacheStorageError("Zero magnitude embedding")
    return vector


def vector_literal(vector: NDArray[np.float64]) -> str:
    return "[" + ",".join(format(float(value), ".17g") for value in vector) + "]"


def parse_vector_literal(
    value: str,
    *,
    dimensions: int,
) -> list[float]:
    if not value.startswith("[") or not value.endswith("]"):
        raise CacheStorageError("Stored embedding is invalid")

    vector: NDArray[np.float64] = np.fromstring(
        value[1:-1],
        dtype=np.float64,
        sep=",",
    )
    validated = validated_cache_vector(
        vector,
        dimensions=dimensions,
        description="Stored",
    )
    return [float(component) for component in validated]
