"""Cache namespace validation and defaults.

CacheNamespace applies the shared bounded identifier pattern; partition identity
does not grant access. Security dependencies decide which namespaces a principal
may use. AuthorizedNamespaceScope is an already-authorized set for key operations:
None permits any namespace, while an empty frozenset permits none. Neither type
alias performs authentication or replaces route-level authorization.
"""

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
