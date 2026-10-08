"""Optional concrete-store observation; the mandatory CacheStore is unchanged.

Snapshots are observations, never leases. Callers authorize namespaces first.
Listing contains bounded previews, no vectors, and does not change access order.
"""

from datetime import datetime
from typing import Literal, cast

from pydantic import Field

from ._semantics import namespace_value
from .errors import CacheValidationError
from .models import CacheKey, Namespace, Prompt, Response, Timestamp, _Model

InspectionSort = Literal["newest", "oldest", "most_hit", "nearest_expiry"]
PREVIEW_LIMIT = 240


class InspectionEntry(_Model):
    cache_key: CacheKey = Field(repr=False)
    namespace: Namespace
    prompt: Prompt = Field(repr=False)
    response_preview: str = Field(repr=False, min_length=1, max_length=PREVIEW_LIMIT)
    response_preview_truncated: bool
    response: Response | None = Field(default=None, repr=False)
    created_at: Timestamp
    expires_at: Timestamp | None
    remaining_ttl_seconds: float | None = Field(default=None, ge=0)
    hit_count: int = Field(ge=0)
    last_accessed_at: Timestamp | None
    recency_rank: int = Field(ge=1)
    is_expired: Literal[False] = False


class InspectionPage(_Model):
    items: tuple[InspectionEntry, ...] = Field(repr=False)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool


def inspection_arguments(
    namespace: str | None,
    offset: int,
    limit: int,
    search: str | None,
    sort: InspectionSort,
) -> None:
    try:
        if namespace is not None:
            namespace_value(namespace)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
            or not isinstance(sort, str)
            or sort not in {"newest", "oldest", "most_hit", "nearest_expiry"}
            or (
                search is not None
                and (not isinstance(search, str) or len(search) > 2000)
            )
        ):
            raise ValueError
    except ValueError:
        raise CacheValidationError("Invalid inspection arguments") from None


def inspection_namespaces(namespaces: tuple[str, ...] | None) -> None:
    if namespaces is not None:
        try:
            if not isinstance(cast(object, namespaces), tuple):
                raise TypeError
            for namespace in namespaces:
                namespace_value(namespace)
        except (ValueError, TypeError):
            raise CacheValidationError("Invalid inspection namespace scope") from None


def inspection_page(
    items: list[InspectionEntry],
    *,
    offset: int,
    limit: int,
    search: str | None,
    sort: InspectionSort,
) -> InspectionPage:
    needle = None if search is None else search.strip().casefold()
    if needle:
        items = [item for item in items if needle in item.prompt.casefold()]
    if sort == "oldest":
        items.sort(key=lambda item: (item.created_at, item.cache_key))
    elif sort == "most_hit":
        items.sort(
            key=lambda item: (
                -item.hit_count,
                -item.created_at.timestamp(),
                item.cache_key,
            )
        )
    elif sort == "nearest_expiry":
        items.sort(
            key=lambda item: (
                item.expires_at is None,
                float("inf")
                if item.expires_at is None
                else item.expires_at.timestamp(),
                -item.created_at.timestamp(),
                item.cache_key,
            )
        )
    else:
        items.sort(key=lambda item: (-item.created_at.timestamp(), item.cache_key))
    page = tuple(items[offset : offset + limit])
    return InspectionPage(
        items=page,
        total=len(items),
        offset=offset,
        limit=limit,
        has_more=offset + len(page) < len(items),
    )


def preview(response: str) -> str:
    return response[:PREVIEW_LIMIT]


def remaining(expires_at: datetime | None, observed_at: datetime) -> float | None:
    return (
        None
        if expires_at is None
        else max(0.0, (expires_at - observed_at).total_seconds())
    )
