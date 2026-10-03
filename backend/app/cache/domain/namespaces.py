"""Cache namespace validation and defaults."""

from typing import Annotated

from pydantic import StringConstraints

from semantix_cache._semantics import (
    CACHE_NAMESPACE_PATTERN,
    DEFAULT_CACHE_NAMESPACE,
    MAX_CACHE_NAMESPACE_LENGTH,
)

__all__ = [
    "CACHE_NAMESPACE_PATTERN",
    "DEFAULT_CACHE_NAMESPACE",
    "MAX_CACHE_NAMESPACE_LENGTH",
    "AuthorizedNamespaceScope",
    "CacheNamespace",
]

CacheNamespace = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MAX_CACHE_NAMESPACE_LENGTH,
        pattern=CACHE_NAMESPACE_PATTERN,
    ),
]

AuthorizedNamespaceScope = frozenset[str] | None
