"""Public identity and private resource ownership survive backend relocation."""

import importlib
import inspect
import pickle
import subprocess
import sys

import pytest

from semantix_cache.stores import _mysql_cleanup as status_types
from semantix_cache.stores import mysql
from semantix_cache.stores._backends.mysql import cleanup

_PUBLIC_BINDINGS = {
    "mysql": (
        "CacheConfigurationError CacheEntry CacheMatch CacheStoreError "
        "CacheValidationError Configuration Database EmbeddingSpace MySQLCleanupStatus "
        "MySQLStore Path Self SemantixCacheError Sequence TracebackType Worker "
        "annotations asyncio cache_key_value datetime micros namespace_value safe "
        "startup_cleanup timeout"
    ),
    "sqlite": (
        "CacheConfigurationError CacheEntry CacheMatch CacheStoreError "
        "CacheValidationError Configuration Database EmbeddingSpace SQLiteStore Self "
        "Sequence TracebackType Worker annotations asyncio cache_key_value datetime "
        "micros namespace_value os safe timeout"
    ),
    "pgvector": (
        "AsyncExitStack AsyncGenerator CacheConfigurationError CacheEntry CacheMatch "
        "CacheStoreError CacheTimeoutError CacheValidationError EmbeddingSpace "
        "InspectionEntry InspectionPage InspectionSort Lifecycle PgVectorStore Pool "
        "PoolConnectionProxy Self SemantixCacheError Sequence TracebackType annotations "
        "asynccontextmanager asyncio asyncpg cache_key_value cast dataclass datetime "
        "files finite_number inspection_arguments inspection_namespaces namespace_value "
        "normalized_vector re remaining resolve_ttl sha256"
    ),
    "redis": (
        "AsyncGenerator Awaitable CacheConfigurationError CacheEntry CacheMatch "
        "CacheStoreError CacheTimeoutError CacheValidationError Callable Connection "
        "ConnectionPool DefaultParser EmbeddingSpace InspectionEntry InspectionPage "
        "InspectionSort InvalidResponse Lifecycle NDArray NoBackoff NoReturn Redis "
        "RedisConnectionError RedisStore RedisTimeoutError ResponseError Retry "
        "SSLConnection Self SemantixCacheError Sequence TracebackType UTC annotations "
        "asynccontextmanager asyncio cache_key_value cast dataclass datetime "
        "finite_number inspection_arguments inspection_namespaces json namespace_value "
        "nearest_index normalized_vector np re remaining resolve_ttl sha256 suppress "
        "timedelta urlsplit version"
    ),
}


@pytest.mark.parametrize(
    ("backend", "class_name"),
    [
        ("mysql", "MySQLStore"),
        ("sqlite", "SQLiteStore"),
        ("pgvector", "PgVectorStore"),
        ("redis", "RedisStore"),
    ],
)
def test_public_class_identity_and_bindings(backend: str, class_name: str) -> None:
    module = importlib.import_module("semantix_cache.stores." + backend)
    store = getattr(module, class_name)
    assert store.__module__ == module.__name__
    assert store.__qualname__ == class_name
    assert repr(store) == f"<class '{module.__name__}.{class_name}'>"
    assert inspect.getmodule(store) is module
    assert store.__mro__ == (store, object)
    assert pickle.loads(pickle.dumps(store)) is store  # noqa: S301 -- trusted in-process class roundtrip
    assert not hasattr(module, "__all__")
    assert {name for name in vars(module) if not name.startswith("_")} == set(
        _PUBLIC_BINDINGS[backend].split()
    )
    child = type("StoreSubclass", (store,), {})
    assert vars(store)["connect"].__get__(None, child).__self__ is child


def test_cleanup_status_retains_qualified_identity() -> None:
    status = status_types.MySQLCleanupStatus
    assert vars(mysql)["MySQLCleanupStatus"] is status
    assert vars(cleanup)["MySQLCleanupStatus"] is status
    assert status.__module__ == "semantix_cache.stores._mysql_cleanup"
    assert pickle.loads(pickle.dumps(status)) is status  # noqa: S301 -- trusted in-process class roundtrip
    receipt = status("synthetic", "retired", (), None, False)
    assert pickle.loads(pickle.dumps(receipt)) == receipt  # noqa: S301 -- trusted synthetic receipt roundtrip


def test_one_cleanup_registry_with_no_legacy_alias() -> None:
    assert vars(mysql)["startup_cleanup"] is cleanup
    assert cleanup.__name__ == "semantix_cache.stores._backends.mysql.cleanup"
    assert not any(
        hasattr(status_types, name)
        for name in ("_owners", "_failed", "_history", "_lock", "reserve", "retry")
    )
    assert "semantix_cache.stores._mysql_worker" not in sys.modules
    assert "semantix_cache.stores._mysql_database" not in sys.modules


def test_backend_packages_have_no_optional_import_side_effects() -> None:
    code = """
import sys
from semantix_cache import MemoryStore
import semantix_cache.stores
import semantix_cache.stores._backends
import semantix_cache.stores._backends.mysql
import semantix_cache.stores._backends.sqlite
import semantix_cache.stores._backends.redis
import semantix_cache.stores._backends.postgres
assert not {'pymysql', 'asyncpg', 'redis', 'sqlite3'} & sys.modules.keys()
"""
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/script; no shell or external inputs
        [sys.executable, "-I", "-B", "-c", code],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf8", errors="replace")
