"""Required schema refusal must also hold for the actual runtime grants."""

import asyncio

import pytest

from examples.store_conformance import SPACE, StoreFactory
from semantix_cache import CacheStoreError
from semantix_cache.stores import _mysql_schema as schema
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, options, store_factory

__all__ = ["store_factory"]
pytestmark = pytest.mark.mysql


@pytest.mark.parametrize("object_type", ["trigger", "table"])
async def test_runtime_refuses_schema_drift_hidden_by_catalog_privileges(
    store_factory: StoreFactory, object_type: str
) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    name = store._config.database
    statement = (
        "CREATE TRIGGER foreign_trigger AFTER INSERT ON semantix_entries FOR EACH ROW SET @foreign_effect=1"
        if object_type == "trigger"
        else "CREATE TABLE foreign_data(secret VARBINARY(64))"
    )
    await asyncio.to_thread(admin, statement, name=name)
    # The setup account detects exactly the same harmless disposable schema drift.
    with pytest.raises(CacheStoreError, match="schema shape"):
        await MySQLStore.connect(
            **options(name),
            embedding_space=SPACE,
            default_ttl_seconds=None,
            max_size=32,
        )
    sql = (
        "SELECT count(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s"
        if object_type == "trigger"
        else "SELECT count(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s"
    )
    root_count = (await asyncio.to_thread(admin, sql, (name,), name=name))[0][0]
    runtime_count = (
        await store._worker.run(lambda job: job.rows(sql, (name,)), readonly=True)
    )[0][0]
    verifier_result = await store._worker.run(
        lambda job: job.rows("CALL semantix_verify()"), readonly=True
    )
    assert verifier_result == [(2, 0, schema.VERIFIER_BODY_CHECKSUM)]
    expected_root, expected_runtime = (1, 0) if object_type == "trigger" else (5, 4)
    current_rejected = fresh_rejected = False
    try:
        await store.find_nearest((1, 0), namespace="default")
    except CacheStoreError:
        current_rejected = True
    try:
        replacement = await MySQLStore.connect(
            **(
                options(name)
                | {"user": store._config.user, "password": store._config.password}
            ),
            embedding_space=SPACE,
            default_ttl_seconds=None,
            max_size=32,
        )
    except CacheStoreError:
        fresh_rejected = True
    else:
        async with replacement:
            assert await replacement.find_nearest((1, 0), namespace="default") is None
    observed = {
        "root_catalog_count": root_count,
        "runtime_catalog_count": runtime_count,
        "current_store_rejected": current_rejected,
        "fresh_connect_rejected": fresh_rejected,
    }
    assert observed == {
        "root_catalog_count": expected_root,
        "runtime_catalog_count": expected_runtime,
        "current_store_rejected": True,
        "fresh_connect_rejected": True,
    }
