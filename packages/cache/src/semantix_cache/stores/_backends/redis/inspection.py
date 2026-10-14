"""Read-only Redis projection on a borrowed client under the public operation."""

from __future__ import annotations

import json
from typing import cast

from redis.asyncio import Redis

from ....errors import CacheStoreError
from ....inspection import InspectionEntry, InspectionPage, InspectionSort, remaining
from .format import _datetime, _raise_safe


async def inspect_page(
    client: Redis,
    *,
    script: str,
    keys: tuple[str, str, str],
    descriptor: list[str],
    namespace: str | None,
    namespaces: tuple[str, ...] | None,
    cache_key: str | None,
    offset: int,
    limit: int,
    sort: InspectionSort,
) -> InspectionPage:
    raw = await client.eval_ro(
        script,
        3,
        *keys,
        *descriptor,
        namespace or "",
        cache_key or "",
        json.dumps(namespaces),
        offset,
        limit,
        sort,
    )
    try:
        if not isinstance(raw, list):
            raise TypeError
        parts = cast(list[object], raw)
        if len(parts) != 2:
            raise ValueError
        total, rows = parts
        if type(total) is not int or total < 0 or not isinstance(rows, list):
            raise ValueError
        records = cast(list[object], rows)
        if len(records) > limit:
            raise ValueError
        result: list[InspectionEntry] = []
        for row in records:
            if not isinstance(row, list):
                raise TypeError
            fields = cast(list[object], row)
            if len(fields) != 11 or not all(isinstance(x, bytes) for x in fields):
                raise ValueError
            record = cast(list[bytes], fields)
            if record[10] not in (b"0", b"1") or (cache_key is None and record[2]):
                raise ValueError
            ns, key = record[0].decode("ascii").split("|")
            if (
                (namespace is not None and ns != namespace)
                or (namespaces is not None and ns not in namespaces)
                or (cache_key is not None and key != cache_key)
            ):
                raise ValueError
            expiry = None if not record[5] else _datetime(record[5])
            observed = _datetime(record[9])
            if expiry is not None and expiry <= observed:
                raise ValueError
            result.append(
                InspectionEntry(
                    cache_key=key,
                    namespace=ns,
                    prompt=record[1].decode("utf-8"),
                    response_preview=record[3].decode("utf-8"),
                    response_preview_truncated=record[10] == b"1",
                    response=record[2].decode("utf-8")
                    if cache_key is not None
                    else None,
                    created_at=_datetime(record[4]),
                    expires_at=expiry,
                    remaining_ttl_seconds=remaining(expiry, observed),
                    hit_count=int(record[6]),
                    last_accessed_at=None if not record[7] else _datetime(record[7]),
                    recency_rank=int(record[8]),
                )
            )
        return InspectionPage(
            items=tuple(result),
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(result) < total,
        )
    except (ValueError, TypeError, OverflowError):
        _raise_safe(CacheStoreError("Invalid Redis inspection metadata"))
