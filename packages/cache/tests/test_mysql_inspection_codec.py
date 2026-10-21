"""Offline validation of MySQL payload projection and public argument boundaries.

These checks do not substitute for the real-MySQL transaction/lifecycle suite.
"""

import json
from typing import cast

import pytest

from semantix_cache import CacheValidationError
from semantix_cache.inspection import InspectionSort
from semantix_cache.stores._backends.mysql.database import inspection_entry
from semantix_cache.stores._backends.mysql.format import (
    MAX_PAYLOAD,
    decode_entry,
    decode_payload,
    encode_entry,
    micros,
)
from semantix_cache.stores.mysql import MySQLStore

from .test_memory import entry


@pytest.mark.parametrize(
    "response",
    ["answer", "\u00e9\U0001f642" * 121, " " * 240 + "answer"],
    ids=["short", "unicode", "leading-whitespace"],
)
def test_payload_projection_preserves_full_entry_validation(response: str) -> None:
    value = entry("Stra\u00dfe identifier", namespace="alpha").model_copy(
        update={"response": response}
    )
    checked, vector, payload = encode_entry(value, 2)
    projected = decode_payload(payload, value.cache_key, value.namespace)
    assert projected == {
        field: getattr(checked, field)
        for field in ("cache_key", "namespace", "prompt", "response")
    }
    assert (
        decode_entry(
            payload,
            vector,
            value.cache_key,
            value.namespace,
            micros(value.created_at),
            2,
        )
        == checked
    )
    with pytest.raises(ValueError, match="Invalid stored vector codec"):
        decode_entry(
            payload,
            b"invalid vector",
            value.cache_key,
            value.namespace,
            micros(value.created_at),
            2,
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b'{"x":1,"x":2}',
        b'{"cache_key":null}',
        b"\xff",
        b'"text"',
        b"x" * (MAX_PAYLOAD + 1),
    ],
    ids=["array", "duplicate", "null", "invalid-encoding", "scalar", "oversize"],
)
def test_payload_structure_is_not_weakened(payload: bytes) -> None:
    value = entry("valid")
    with pytest.raises((ValueError, TypeError)):
        decode_payload(payload, value.cache_key, value.namespace)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("cache_key", "0" * 64),
        ("namespace", "foreign"),
        ("prompt", "different prompt"),
        ("prompt", " valid "),
        ("prompt", ""),
        ("response", " "),
        ("response", "x" * 100001),
        ("response", 1),
        ("extra", "field"),
    ],
    ids=[
        "key",
        "namespace",
        "changed-prompt",
        "noncanonical",
        "empty-prompt",
        "blank-response",
        "long-response",
        "response-type",
        "extra-field",
    ],
)
def test_payload_invariants_are_not_weakened(field: str, replacement: object) -> None:
    value = entry("valid")
    _, _, blob = encode_entry(value, 2)
    payload = json.loads(blob)
    payload[field] = replacement
    with pytest.raises((ValueError, TypeError)):
        decode_payload(
            json.dumps(payload).encode("ascii"), value.cache_key, value.namespace
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("offset", -1),
        ("offset", True),
        ("offset", 1.0),
        ("limit", 0),
        ("limit", 101),
        ("limit", False),
        ("namespace", "bad|scope"),
        ("search", 42),
        ("search", "x" * 2001),
        ("sort", "bad"),
    ],
    ids=[
        "negative-offset",
        "bool-offset",
        "float-offset",
        "zero-limit",
        "large-limit",
        "bool-limit",
        "namespace",
        "search-type",
        "search-length",
        "sort",
    ],
)
async def test_list_validation_precedes_worker_access(
    field: str, value: object
) -> None:
    # No initialized owner exists: invalid inputs must fail before worker access.
    store = object.__new__(MySQLStore)
    options = {field: value}
    with pytest.raises(CacheValidationError):
        await store.inspect_entries(
            namespace=cast(str | None, options.get("namespace")),
            offset=cast(int, options.get("offset", 0)),
            limit=cast(int, options.get("limit", 20)),
            search=cast(str | None, options.get("search")),
            sort=cast(InspectionSort, options.get("sort", "newest")),
        )


@pytest.mark.parametrize(
    ("key", "scope"), [("bad", None), ("0" * 64, "alpha"), ("0" * 64, ("bad|scope",))]
)
async def test_detail_validation_precedes_worker_access(
    key: str, scope: object
) -> None:
    store = object.__new__(MySQLStore)
    with pytest.raises(CacheValidationError):
        await store.inspect_entry(key, namespaces=cast(tuple[str, ...] | None, scope))


@pytest.mark.parametrize("detail", [False, True])
def test_detached_projection_preserves_ttl_and_payload_privacy(detail: bool) -> None:
    value = entry("projection", namespace="alpha").model_copy(
        update={"response": "\u00e9" * 241}
    )
    _, _, blob = encode_entry(value, 2)
    payload = decode_payload(blob, value.cache_key, value.namespace)
    observed = micros(value.created_at)
    row = (
        value.cache_key,
        value.namespace,
        observed,
        observed + 1234567,
        2,
        observed - 1,
        9,
        2,
    )
    result = inspection_entry(row, payload, observed, detail=detail)
    assert result.remaining_ttl_seconds == pytest.approx(1.234567, rel=0, abs=1e-12)
    assert result.hit_count == 2
    assert result.recency_rank == 2
    assert result.created_at == value.created_at
    assert result.response_preview == value.response[:240]
    assert result.response_preview_truncated
    assert result.response == (value.response if detail else None)
    assert "embedding" not in result.model_dump()
    payload["prompt"] = "changed after projection"
    assert result.prompt == "projection"
