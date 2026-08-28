"""Immutable public response models and contract decoders."""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from .errors import SemantixResponseError

_CACHE_KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MAX_PROMPT_LENGTH = 2_000
_MAX_RESPONSE_LENGTH = 100_000


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Evidence returned by a Semantix query."""

    response: str
    cache_hit: bool
    similarity_score: float | None
    similarity_threshold: float
    matched_prompt: str | None
    matched_cache_key: str | None
    cache_entry_created_at: datetime | None
    cache_entry_age_seconds: float | None
    generation_skipped: bool
    provider_called: bool
    latency_ms: float


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Public liveness response from a Semantix server."""

    status: Literal["ok"]
    embedding_provider: str
    generation_provider: str


@dataclass(frozen=True, slots=True)
class ReadinessStatus:
    """Public dependency-readiness response from a Semantix server."""

    status: Literal["ready"]
    cache_backend: str
    evaluation_dataset_storage: str


def _invalid(field: str) -> SemantixResponseError:
    return SemantixResponseError(f"Invalid Semantix response field: {field}.")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SemantixResponseError("The Semantix response must be a JSON object.")
    return cast(dict[str, object], value)


def _required(data: dict[str, object], field: str) -> object:
    if field not in data:
        raise _invalid(field)
    return data[field]


def _string(
    data: dict[str, object],
    field: str,
    *,
    max_length: int,
) -> str:
    value = _required(data, field)
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise _invalid(field)
    return value


def _nullable_string(
    data: dict[str, object],
    field: str,
    *,
    max_length: int,
) -> str | None:
    value = _required(data, field)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise _invalid(field)
    return value


def _boolean(data: dict[str, object], field: str) -> bool:
    value = _required(data, field)
    if not isinstance(value, bool):
        raise _invalid(field)
    return value


def _number(
    data: dict[str, object],
    field: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    value = _required(data, field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(field)
    result = float(value)
    if (
        not math.isfinite(result)
        or result < minimum
        or (maximum is not None and result > maximum)
    ):
        raise _invalid(field)
    return result


def _nullable_number(
    data: dict[str, object],
    field: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float | None:
    if _required(data, field) is None:
        return None
    return _number(data, field, minimum=minimum, maximum=maximum)


def _nullable_datetime(data: dict[str, object], field: str) -> datetime | None:
    value = _required(data, field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(field)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _invalid(field) from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise _invalid(field)
    return result


def _decode_query_result(value: object) -> QueryResult:
    data = _object(value)
    result = QueryResult(
        response=_string(data, "response", max_length=_MAX_RESPONSE_LENGTH),
        cache_hit=_boolean(data, "cache_hit"),
        similarity_score=_nullable_number(
            data,
            "similarity_score",
            minimum=-1,
            maximum=1,
        ),
        similarity_threshold=_number(
            data,
            "similarity_threshold",
            minimum=0,
            maximum=1,
        ),
        matched_prompt=_nullable_string(
            data,
            "matched_prompt",
            max_length=_MAX_PROMPT_LENGTH,
        ),
        matched_cache_key=_nullable_string(
            data,
            "matched_cache_key",
            max_length=64,
        ),
        cache_entry_created_at=_nullable_datetime(data, "cache_entry_created_at"),
        cache_entry_age_seconds=_nullable_number(
            data,
            "cache_entry_age_seconds",
            minimum=0,
        ),
        generation_skipped=_boolean(data, "generation_skipped"),
        provider_called=_boolean(data, "provider_called"),
        latency_ms=_number(data, "latency_ms", minimum=0),
    )
    matched_fields = (
        result.matched_prompt,
        result.matched_cache_key,
        result.cache_entry_created_at,
        result.cache_entry_age_seconds,
    )
    if result.cache_hit:
        if (
            result.similarity_score is None
            or result.similarity_score < result.similarity_threshold
            or any(item is None for item in matched_fields)
            or result.matched_cache_key is None
            or _CACHE_KEY_PATTERN.fullmatch(result.matched_cache_key) is None
            or not result.generation_skipped
            or result.provider_called
        ):
            raise SemantixResponseError(
                "The Semantix query response contains inconsistent cache-hit evidence."
            )
    elif (
        any(item is not None for item in matched_fields)
        or result.generation_skipped == result.provider_called
    ):
        raise SemantixResponseError(
            "The Semantix query response contains inconsistent cache-miss evidence."
        )
    return result


def _decode_health(value: object) -> HealthStatus:
    data = _object(value)
    if _required(data, "status") != "ok":
        raise _invalid("status")
    return HealthStatus(
        status="ok",
        embedding_provider=_string(data, "embedding_provider", max_length=100),
        generation_provider=_string(data, "generation_provider", max_length=100),
    )


def _decode_readiness(value: object) -> ReadinessStatus:
    data = _object(value)
    if _required(data, "status") != "ready":
        raise _invalid("status")
    return ReadinessStatus(
        status="ready",
        cache_backend=_string(data, "cache_backend", max_length=100),
        evaluation_dataset_storage=_string(
            data,
            "evaluation_dataset_storage",
            max_length=100,
        ),
    )
