"""Optional concrete-store observations outside the mandatory CacheStore protocol.

Inspection never confirms a cache hit, renews TTL or updates hit/access/LRU
metadata. Stores exclude expired entries without explicit purge; native backend
expiry may proceed independently. The caller/server authorizes namespace scope.

InspectionEntry contains prompt/key metadata, a response_preview of at most 240
characters and no embedding. Lists leave response=None; a scoped detail read can
include the full response. Prompts, previews and explicit serialization remain
sensitive even though payloads are omitted from repr. Previewing is not redaction.
created_at is the observed revision; remaining_ttl_seconds and hit/access counters
are observations, not leases or durability guarantees. Persistence and clock
semantics belong to each store; MemoryStore counters are process-local.

InspectionPage contains an immutable items tuple, filtered total, requested
offset/limit and has_more. Pages are live observations: concurrent expiry,
writes or confirmations may shift later offsets, ordering and totals. Redis
prompt search can span several observations even within one call.

InspectionSort accepts newest, oldest, most_hit and nearest_expiry. Equal primary
sort values use newer revisions except oldest; cache keys break remaining ties.
No-expiry entries sort last for nearest_expiry. recency_rank is scoped access
order (1 is most recent), independent of display sorting and prompt filtering.
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
    """Validate list scope, paging, search length and sort without authorizing access.

    Raises:
        CacheValidationError: If namespace is invalid, offset is not a nonnegative
            integer, limit is outside 1-100, search is not text or exceeds 2,000
            characters, or sort is unsupported. Boolean paging values are rejected.
    """

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
    """Validate a detail-read filter; None is unrestricted and () allows no namespaces.

    This checks tuple structure/identifiers only. The caller must authorize scope.

    Raises:
        CacheValidationError: If the scope is not a tuple of valid namespaces.
    """

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
    """Filter, sort and slice an already validated metadata observation.

    Prompt search strips/casefolds text. This helper does not check authorization,
    expiry or paging arguments; concrete stores validate and collect live entries
    first. Sorting can mutate the supplied list when search is blank; recency_rank
    stays as supplied, independent of filtering/display order.

    Returns:
        Detached page with filtered total and has_more for this observation.
    """

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
