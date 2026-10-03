from datetime import datetime
from typing import cast

from asyncpg import Record

from app.cache.api.schemas import CacheEntryMetadata
from app.cache.domain.metadata import (
    response_preview,
    response_preview_is_truncated,
)
from app.cache.domain.models import CacheEntry
from app.cache.domain.vector_validation import parse_vector_literal


def cache_entry_from_record(
    row: Record,
    *,
    dimensions: int,
) -> CacheEntry:
    return CacheEntry(
        cache_key=cast(str, row["cache_key"]),
        namespace=cast(str, row["namespace"]),
        prompt=cast(str, row["prompt"]),
        response=cast(str, row["response"]),
        embedding=parse_vector_literal(
            cast(str, row["embedding"]),
            dimensions=dimensions,
        ),
        created_at=cast(datetime, row["created_at"]),
    )


def cache_metadata_from_record(
    row: Record,
    *,
    include_response: bool = False,
) -> CacheEntryMetadata:
    expires_at = cast(datetime | None, row["expires_at"])
    observed_at = cast(datetime, row["observed_at"])
    remaining_ttl_seconds = (
        None
        if expires_at is None
        else max(0.0, (expires_at - observed_at).total_seconds())
    )
    return CacheEntryMetadata(
        cache_key=cast(str, row["cache_key"]),
        namespace=cast(str, row["namespace"]),
        prompt=cast(str, row["prompt"]),
        response_preview=response_preview(cast(str, row["response"])),
        response_preview_truncated=response_preview_is_truncated(
            cast(str, row["response"])
        ),
        response=cast(str, row["response"]) if include_response else None,
        created_at=cast(datetime, row["created_at"]),
        expires_at=expires_at,
        remaining_ttl_seconds=remaining_ttl_seconds,
        hit_count=int(row["hit_count"]),
        last_accessed_at=cast(datetime | None, row["last_accessed_at"]),
        recency_rank=int(row["recency_rank"]),
        is_expired=False,
    )
