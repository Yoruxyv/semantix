from dataclasses import dataclass

from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE


@dataclass(frozen=True, slots=True)
class QueryCachePolicy:
    namespace: str = DEFAULT_CACHE_NAMESPACE
    read_enabled: bool = True
    write_enabled: bool = True
    cache_ttl_seconds: float | None = None

    def coalescing_key(self, prompt: str) -> str:
        cache_key = prompt_cache_key(prompt, namespace=self.namespace)
        return (
            f"{cache_key}:read={int(self.read_enabled)}:write={int(self.write_enabled)}"
            f":ttl={self.cache_ttl_seconds}"
        )


DEFAULT_QUERY_CACHE_POLICY = QueryCachePolicy()
