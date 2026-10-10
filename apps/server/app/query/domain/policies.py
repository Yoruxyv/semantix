"""Carry independent read/write permissions for one already-authorized namespace.

The default policy reads and writes in default with no explicit TTL override.
QueryService validates TTL/write compatibility and resolves the backend cap
before sharing work; this dataclass does not validate permissions or values.
Its coalescing key is a transient grouping key, not durable entry identity or
an authorization boundary.
"""

from dataclasses import dataclass

from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE


@dataclass(frozen=True, slots=True)
class QueryCachePolicy:
    """Immutable namespace, read/write flags and optional TTL for query execution.

    Read-only permits hits without writes; refresh skips reads but permits writes;
    disabling both bypasses cache operations while still allowing shared generation.
    """

    namespace: str = DEFAULT_CACHE_NAMESPACE
    read_enabled: bool = True
    write_enabled: bool = True
    cache_ttl_seconds: float | None = None

    def coalescing_key(self, prompt: str) -> str:
        """Combine the canonical namespace-aware prompt key with flags and TTL.

        QueryService calls this on its effective policy, so equal resolved TTLs can
        share work. The suffix does not change the underlying stored cache key.
        """
        cache_key = prompt_cache_key(prompt, namespace=self.namespace)
        return (
            f"{cache_key}:read={int(self.read_enabled)}:write={int(self.write_enabled)}"
            f":ttl={self.cache_ttl_seconds}"
        )


DEFAULT_QUERY_CACHE_POLICY = QueryCachePolicy()
