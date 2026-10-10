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
    """Convert to float64 and check shape, finite components and near-zero magnitude.

    Require shape (dimensions,) and norm greater than float64 epsilon; do not divide
    by the norm or check embedding-space identity. np.asarray may share the supplied
    array. Conversion errors are not universally mapped, and finite components do
    not imply a separately checked finite norm.

    Args:
        values: Numeric sequence/array to convert.
        dimensions: Expected component count supplied by the caller.
        description: Caller-controlled internal error context for invalid shape/values.

    Returns:
        Validated float64 array without unit-length normalization.

    Raises:
        CacheStorageError: Explicit shape/nonfinite or near-zero checks fail.
    """
    vector: NDArray[np.float64] = np.asarray(values, dtype=np.float64)
    if vector.shape != (dimensions,) or not np.isfinite(vector).all():
        raise CacheStorageError(f"{description} embedding is invalid")
    if float(np.linalg.norm(vector)) <= np.finfo(np.float64).eps:
        raise CacheStorageError("Zero magnitude embedding")
    return vector


def vector_literal(vector: NDArray[np.float64]) -> str:
    """Format components as bracketed comma-separated .17g PostgreSQL vector text.

    This formatter adds no vector validation or identity guarantee. It is not a
    promise of bit-for-bit roundtripping through every database/backend.
    """
    return "[" + ",".join(format(float(value), ".17g") for value in vector) + "]"


def parse_vector_literal(
    value: str,
    *,
    dimensions: int,
) -> list[float]:
    """Parse a bracketed stored literal with NumPy, then validate its vector shape.

    Bracket errors and explicit vector checks raise CacheStorageError. NumPy parsing/
    conversion errors are not universally caught; this is not a strict independent
    parser or embedding-space binding check.

    Args:
        value: Stored bracketed comma-separated vector text.
        dimensions: Required component count for the parsed vector.

    Returns:
        Float components without unit normalization.
    """
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
