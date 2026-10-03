"""Private semantics shared by the embedded facade and server boundary wrappers."""

import hashlib
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from numbers import Real
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

MAX_PROMPT_LENGTH = 2_000
MAX_RESPONSE_LENGTH = 100_000
MAX_REQUEST_CACHE_TTL_SECONDS = 31_536_000
MAX_MEMORY_CACHE_SIZE = 5_000
DEFAULT_CACHE_NAMESPACE = "default"
MAX_CACHE_NAMESPACE_LENGTH = 64
CACHE_NAMESPACE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_REPEATED_WHITESPACE = re.compile(r"[ \t]+")
Lookup = TypeVar("Lookup")


class SemanticValidationError(ValueError):
    """ValueError also recognized by Pydantic's boundary validators."""


def sanitize_prompt(value: str) -> str:
    return _REPEATED_WHITESPACE.sub(" ", _CONTROL_CHARACTERS.sub(" ", value)).strip()


def canonical_prompt(value: object) -> str:
    if not isinstance(value, str):
        raise SemanticValidationError("Prompt must be text")
    result = sanitize_prompt(value)
    if not 1 <= len(result) <= MAX_PROMPT_LENGTH:
        raise ValueError("Prompt is outside the supported length")
    return result


def valid_response(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_RESPONSE_LENGTH
    ):
        raise ValueError("Completed response is invalid")
    return value


def namespace_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(CACHE_NAMESPACE_PATTERN, value) is None
    ):
        raise ValueError("Namespace is invalid")
    return value


def cache_key_value(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Cache key is invalid")
    return value


def prompt_cache_key(prompt: str, *, namespace: str = DEFAULT_CACHE_NAMESPACE) -> str:
    digest = hashlib.sha256()
    digest.update(namespace.encode("utf-8"))
    digest.update(b"\0")
    digest.update(prompt.encode("utf-8"))
    return digest.hexdigest()


def finite_number(value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SemanticValidationError("Expected a finite number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError("Number is outside the supported range") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("Number is outside the supported range")
    return result


def ttl_value(value: object) -> float | None:
    if value is None:
        return None
    result = finite_number(value, minimum=0.0, maximum=MAX_REQUEST_CACHE_TTL_SECONDS)
    if result == 0:
        raise ValueError("TTL must be positive")
    return result


def resolve_ttl(requested: float | None, default: float | None) -> float | None:
    requested = ttl_value(requested)
    default = ttl_value(default)
    if requested is None:
        return default
    return requested if default is None else min(requested, default)


def validate_ttl_policy(ttl: float | None, *, write_enabled: bool) -> None:
    ttl_value(ttl)
    if ttl is not None and not write_enabled:
        raise ValueError(
            "cache_ttl_seconds requires a cache policy that permits writes"
        )


def threshold_eligible(score: float, threshold: float) -> bool:
    return score >= threshold


def normalized_vector(
    values: Sequence[float], *, dimensions: int
) -> NDArray[np.float64]:
    if isinstance(values, np.ndarray) and values.ndim != 1:
        raise ValueError("Embedding must have one dimension")
    if isinstance(values, (str, bytes)) or not isinstance(
        values, (Sequence, np.ndarray)
    ):
        raise SemanticValidationError("Embedding must be a numeric sequence")
    if len(values) != dimensions:
        raise ValueError("Embedding dimensions do not match")
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
        raise ValueError("Embedding components must be numbers")
    with np.errstate(over="ignore", invalid="ignore"):
        try:
            vector = np.asarray(values, dtype=np.float64)
        except OverflowError:
            raise ValueError("Embedding contains invalid components") from None
        if vector.ndim != 1 or not np.isfinite(vector).all():
            raise ValueError("Embedding contains invalid components")
        norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= np.finfo(np.float64).eps:
        raise ValueError("Embedding has zero or invalid magnitude")
    return vector / norm


def nearest_index(
    query: NDArray[np.float64], embeddings: Sequence[Sequence[float]]
) -> tuple[int, float]:
    matrix = np.asarray(embeddings, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms <= np.finfo(np.float64).eps):
        raise ValueError("Embedding has zero or invalid magnitude")
    scores = (matrix @ query) / (norms * float(np.linalg.norm(query)))
    index = int(np.argmax(scores))
    return index, max(-1.0, min(1.0, float(scores[index])))


async def resolve_flow(
    *,
    read_enabled: bool,
    write_enabled: bool,
    lookup: Callable[[], Awaitable[Lookup]],
    hit_response: Callable[[Lookup | None], str | None],
    generate: Callable[[], Awaitable[str]],
    write: Callable[[str, Lookup | None], Awaitable[None]],
) -> tuple[Lookup | None, str]:
    """Share ordering without coupling either product's public result model."""
    found = await lookup() if read_enabled else None
    if found is not None:
        response = hit_response(found)
        if response is not None:
            return found, response
    response = await generate()
    if write_enabled:
        await write(response, found)
    return found, response
