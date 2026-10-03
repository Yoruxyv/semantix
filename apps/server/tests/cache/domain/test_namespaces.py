import pytest
from pydantic import TypeAdapter, ValidationError

from app.cache.domain.namespaces import CacheNamespace

namespace_adapter = TypeAdapter(CacheNamespace)


@pytest.mark.parametrize(
    "namespace",
    ["default", "tenant-a", "tenant_a", "tenant.example:prod"],
)
def test_cache_namespace_accepts_safe_identifiers(namespace: str) -> None:
    assert namespace_adapter.validate_python(namespace) == namespace


@pytest.mark.parametrize("namespace", ["", "-tenant", "tenant/a", "tenant a"])
def test_cache_namespace_rejects_unsafe_identifiers(namespace: str) -> None:
    with pytest.raises(ValidationError):
        namespace_adapter.validate_python(namespace)
