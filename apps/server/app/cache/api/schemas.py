"""Define live-cache observations and explicit administration responses.

CacheEntryMetadata contains sensitive prompt text and a response preview;
detail reads can include the full response, while listings leave response
null. The server substitutes an omission message for truncated previews.
Vectors are absent. Hit counts, recency ranks and remaining TTL describe an
observation, not a confirmed lookup hit, lease or stable cross-request snapshot.

Metadata timestamps must be timezone-aware, and expires_at and remaining TTL
must be present together or both null. Page length is bounded by limit and
has_more must agree with offset, item count and total. Supported presentation
orders are newest, oldest, most_hit and nearest_expiry. Threshold models bound
one global similarity value; namespace authorization belongs to the router.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.cache.domain.namespaces import CacheNamespace
from app.core.limits import (
    MAX_PROMPT_LENGTH,
    MAX_RESPONSE_PREVIEW_LENGTH,
)

CacheEntrySort = Literal["newest", "oldest", "most_hit", "nearest_expiry"]


class CacheStatsResponse(StrictModel):
    size: int = Field(ge=0)
    hits: int = Field(ge=0)
    misses: int = Field(ge=0)
    hit_rate: float = Field(ge=0, le=1)


class ClearCacheResponse(StrictModel):
    cleared: Literal[True]


class DeleteCacheEntryResponse(StrictModel):
    deleted: Literal[True]
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")


class CacheEntryMetadata(StrictModel):
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    namespace: CacheNamespace
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    response_preview: str = Field(min_length=1, max_length=MAX_RESPONSE_PREVIEW_LENGTH)
    response_preview_truncated: bool
    response: str | None = Field(default=None, min_length=1)
    created_at: datetime
    expires_at: datetime | None = None
    remaining_ttl_seconds: float | None = Field(default=None, ge=0)
    hit_count: int = Field(ge=0)
    last_accessed_at: datetime | None = None
    recency_rank: int = Field(ge=1)
    is_expired: bool

    @field_validator("created_at", "expires_at", "last_accessed_at")
    @classmethod
    def require_metadata_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Cache metadata timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_expiry(self) -> "CacheEntryMetadata":
        if (self.expires_at is None) != (self.remaining_ttl_seconds is None):
            raise ValueError(
                "expires_at and remaining_ttl_seconds must both be present or null"
            )
        return self


class CacheEntryListResponse(StrictModel):
    items: list[CacheEntryMetadata]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    has_more: bool

    @model_validator(mode="after")
    def validate_page(self) -> "CacheEntryListResponse":
        if len(self.items) > self.limit:
            raise ValueError("Cache inspector page exceeds its declared limit")
        if self.has_more != (self.offset + len(self.items) < self.total):
            raise ValueError("has_more does not match the cache inspector page")
        return self


class CacheThresholdRequest(StrictModel):
    threshold: float = Field(ge=0, le=1)


class CacheThresholdResponse(StrictModel):
    threshold: float = Field(ge=0, le=1)
