from app.query.domain.policies import QueryCachePolicy


def test_coalescing_key_isolates_namespaces_and_cache_modes() -> None:
    prompt = "shared prompt"
    default = QueryCachePolicy().coalescing_key(prompt)

    assert QueryCachePolicy().coalescing_key(prompt) == default
    assert QueryCachePolicy(namespace="tenant-a").coalescing_key(prompt) != default
    assert QueryCachePolicy(read_enabled=False).coalescing_key(prompt) != default
    assert QueryCachePolicy(write_enabled=False).coalescing_key(prompt) != default
    assert QueryCachePolicy(cache_ttl_seconds=60).coalescing_key(prompt) != default
