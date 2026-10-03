from app.cache.domain.keys import prompt_cache_key


def test_prompt_cache_keys_are_stable_and_namespace_scoped() -> None:
    first = prompt_cache_key("semantic caching", namespace="tenant-a")

    assert prompt_cache_key("semantic caching", namespace="tenant-a") == first
    assert prompt_cache_key("semantic caching", namespace="tenant-b") != first
    assert prompt_cache_key("Semantic caching", namespace="tenant-a") != first
    assert len(first) == 64
