# Copyright (c) 2026 Hans Valerie
# SPDX-License-Identifier: MIT
"""Cache-policy values supported by the public query API."""

from enum import Enum


class CachePolicy(str, Enum):  # noqa: UP042 - preserve public SDK behavior
    """Cache modes; authorization and namespace rules remain server-owned.

    Attributes:
        NORMAL: Read eligible cache entries and write generated misses.
        READ_ONLY: Read eligible entries without writing generated misses.
        REFRESH: Skip reads, generate a fresh answer, and permit a write.
        BYPASS: Skip reads and writes while permitting generation.
        PRIVATE: Skip reads and writes and minimize the server's query trace.
    """

    NORMAL = "normal"
    READ_ONLY = "read_only"
    REFRESH = "refresh"
    BYPASS = "bypass"
    PRIVATE = "private"


_POLICY_FIELDS: dict[CachePolicy, dict[str, bool]] = {
    CachePolicy.NORMAL: {
        "cache_enabled": True,
        "cache_read_enabled": True,
        "cache_write_enabled": True,
        "private": False,
    },
    CachePolicy.READ_ONLY: {
        "cache_enabled": True,
        "cache_read_enabled": True,
        "cache_write_enabled": False,
        "private": False,
    },
    CachePolicy.REFRESH: {
        "cache_enabled": True,
        "cache_read_enabled": False,
        "cache_write_enabled": True,
        "private": False,
    },
    CachePolicy.BYPASS: {
        "cache_enabled": False,
        "cache_read_enabled": False,
        "cache_write_enabled": False,
        "private": False,
    },
    CachePolicy.PRIVATE: {
        "cache_enabled": False,
        "cache_read_enabled": False,
        "cache_write_enabled": False,
        "private": True,
    },
}


def _policy_fields(policy: CachePolicy) -> dict[str, bool]:
    return dict(_POLICY_FIELDS[policy])
