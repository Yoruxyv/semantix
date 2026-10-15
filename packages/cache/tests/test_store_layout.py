"""Public identity and private resource ownership survive backend relocation."""

import importlib
import inspect
import pickle
import subprocess
import sys
from hashlib import sha256
from importlib.resources import files

import pytest

from semantix_cache.stores import _mysql_cleanup as status_types
from semantix_cache.stores import mysql
from semantix_cache.stores._backends.mysql import cleanup, schema

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
import semantix_cache.stores._backends.redis.format
import semantix_cache.stores._backends.postgres
import semantix_cache.stores._backends.postgres.migrations
import semantix_cache.stores._backends.sqlite.migrations
import semantix_cache.stores._backends.mysql.migrations
assert not {'pymysql', 'asyncpg', 'redis', 'sqlite3'} & sys.modules.keys()
"""
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/script; no shell or external inputs
        [sys.executable, "-I", "-B", "-c", code],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf8", errors="replace")


@pytest.mark.parametrize(
    ("provider", "resource", "checksum"),
    [
        (
            "postgres",
            "0001_cache.sql",
            "f1c4f8bcc6e78b7245e5b0e3dd5e445f0cef8d0c411a2375eab9cb5f05fba2ec",
        ),
        (
            "sqlite",
            "0001_cache.sql",
            "2438f440a3f76a4c406ecbec8b14e0620bc5d91d02b2b1d8bfa618478d23d4e2",
        ),
        (
            "mysql",
            "0001_cache.sql",
            "2a2b9d29118053d8091871c30369ac0c629fa03d7291722ca1a0ba840f13cd13",
        ),
        (
            "mysql",
            "0001_shape.json",
            "16a9f2160175f20f5678f9d1f86f874ce4b349f2c55b2ed50b15d3ab93b49fc2",
        ),
        (
            "mysql",
            "0002_verifier.sql",
            "1def57a91b81fe74c08cd71557fbc3dabf0e31480e92549e018e5cef838146a7",
        ),
    ],
)
def test_provider_migration_frozen_bytes(
    provider: str, resource: str, checksum: str
) -> None:
    data = (
        files("semantix_cache.stores._backends." + provider + ".migrations")
        .joinpath(resource)
        .read_bytes()
    )
    assert sha256(data).hexdigest() == checksum


def test_mysql_verifier_body_digest_is_unchanged() -> None:
    assert schema.VERIFIER_BODY_CHECKSUM == (
        "c1aab7237816fe3b0d02f951c34117d5f22fb8641bb6675666d5f32791ec4a14"
    )
