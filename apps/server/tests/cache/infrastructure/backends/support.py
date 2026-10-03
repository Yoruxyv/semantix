from datetime import UTC, datetime

from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.models import CacheEntry
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE
from tests.support import unit_vector


def cache_entry(
    prompt: str,
    response: str,
    *,
    namespace: str = DEFAULT_CACHE_NAMESPACE,
    vector_index: int,
) -> CacheEntry:
    return CacheEntry(
        cache_key=prompt_cache_key(prompt, namespace=namespace),
        namespace=namespace,
        prompt=prompt,
        response=response,
        embedding=unit_vector(vector_index),
        created_at=datetime.now(UTC),
    )
