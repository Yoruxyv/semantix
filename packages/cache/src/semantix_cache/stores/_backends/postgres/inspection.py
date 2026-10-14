"""Read-only projection on the caller's existing connection and transaction."""

from __future__ import annotations

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from ....errors import CacheStoreError
from ....inspection import InspectionEntry, InspectionPage, InspectionSort, remaining


async def inspect_page(
    connection: PoolConnectionProxy[asyncpg.Record],
    *,
    layout: dict[str, str],
    scope: tuple[str, int, str | None, list[str] | None, str | None, str | None],
    offset: int,
    limit: int,
    sort: InspectionSort,
) -> InspectionPage:
    order = {
        "newest": "created_at DESC, cache_key, namespace",
        "oldest": "created_at, cache_key, namespace",
        "most_hit": "hit_count DESC, created_at DESC, cache_key, namespace",
        "nearest_expiry": "expires_at ASC NULLS LAST, created_at DESC, cache_key, namespace",
    }[sort]
    eligible = f"""SELECT cache_key, namespace, prompt, created_at, expires_at, hit_count, last_accessed_at, access_order FROM {layout["entries"]} WHERE embedding_space=$1 AND embedding_dimensions=$2
                AND (expires_at IS NULL OR expires_at>transaction_timestamp())
                AND ($3::text IS NULL OR namespace=$3)
                AND ($4::text[] IS NULL OR namespace=ANY($4))"""
    filtered = "($5::text IS NULL OR cache_key=$5) AND ($6::text IS NULL OR POSITION(LOWER($6) IN LOWER(prompt))>0)"
    total = await connection.fetchval(
        f"SELECT count(*) FROM ({eligible}) eligible WHERE {filtered}", *scope
    )
    rows = await connection.fetch(
        f"""WITH eligible AS MATERIALIZED ({eligible}), ranked AS (
                SELECT *, row_number() OVER (ORDER BY access_order DESC, created_at DESC, cache_key, namespace) AS recency_rank
                FROM eligible), page AS MATERIALIZED (
                SELECT * FROM ranked WHERE {filtered} ORDER BY {order} OFFSET $7 LIMIT $8)
                SELECT page.*, left(e.response,240) AS response_preview,
                    length(e.response)>240 AS response_preview_truncated,
                    CASE WHEN $5::text IS NULL THEN NULL ELSE e.response END AS response,
                    transaction_timestamp() AS observed_at
                FROM page JOIN {layout["entries"]} e
                ON e.embedding_space=$1 AND e.embedding_dimensions=$2
                    AND e.namespace=page.namespace AND e.cache_key=page.cache_key
                ORDER BY {", ".join("page." + field.strip() for field in order.split(","))}""",
        *scope,
        offset,
        limit,
    )
    try:
        metadata = tuple(
            InspectionEntry(
                cache_key=row["cache_key"],
                namespace=row["namespace"],
                prompt=row["prompt"],
                response_preview=row["response_preview"],
                response_preview_truncated=row["response_preview_truncated"],
                response=row["response"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                remaining_ttl_seconds=remaining(row["expires_at"], row["observed_at"]),
                hit_count=row["hit_count"],
                last_accessed_at=row["last_accessed_at"],
                recency_rank=row["recency_rank"],
            )
            for row in rows
        )
    except ValueError:
        raise CacheStoreError("Invalid PostgreSQL inspection metadata") from None
    return InspectionPage(
        items=metadata,
        total=int(total),
        offset=offset,
        limit=limit,
        has_more=offset + len(metadata) < int(total),
    )
