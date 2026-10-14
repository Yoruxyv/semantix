"""Real owned SQLite fixtures; probes stay outside the public store contract."""

import asyncio
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from time import time_ns
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from examples.store_conformance import SPACE, HitMetadata, StoreCase, StoreFactory
from semantix_cache import EmbeddingSpace
from semantix_cache._semantics import nearest_index
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores._backends.sqlite.format import timestamp
from semantix_cache.stores.sqlite import SQLiteStore


@contextmanager
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        db.close()


def state(path: Path) -> tuple[list[tuple[Any, ...]], ...]:
    with connection(path) as db:
        return (
            db.execute("SELECT * FROM binding_state ORDER BY 1,2").fetchall(),
            db.execute("SELECT * FROM cache_entries ORDER BY 1,2").fetchall(),
            db.execute("SELECT * FROM cache_payloads ORDER BY 1,2").fetchall(),
        )


@asynccontextmanager
async def block_lookup(
    store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[asyncio.Event]:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = nearest_index

    def nearest(query: NDArray[np.float64], matrix: Any) -> tuple[int, float]:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Test worker was not released")
        return original(query, matrix)

    with monkeypatch.context() as patch:
        patch.setattr(database, "nearest_index", nearest)
        try:
            yield entered
        finally:
            release.set()
            await store.find_nearest((1, 0), namespace="default")


@pytest.fixture
async def store_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[StoreFactory]:
    stores: list[SQLiteStore] = []
    path = tmp_path / "conformance.db"
    clock = [time_ns() // 1000]
    monkeypatch.setattr(database, "now_us", lambda: clock[0])

    async def factory(
        capacity: int = 32, ttl: float | None = None, *, space: EmbeddingSpace = SPACE
    ) -> StoreCase:
        await SQLiteStore.initialize_schema(
            path, embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
        )
        store = await SQLiteStore.connect(
            path, embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
        )
        stores.append(store)

        async def expire() -> None:
            clock[0] += 31536001 * 1000000

        async def metadata(key: str, namespace: str) -> HitMetadata | None:
            with connection(path) as db:
                row = db.execute(
                    "SELECT e.hit_count,e.last_accessed_at_us FROM cache_entries e JOIN binding_state b USING(binding_id) WHERE b.identity=? AND b.dimensions=? AND e.cache_key=? AND e.namespace=?",
                    (space.identity, space.dimensions, key, namespace),
                ).fetchone()
            return (
                None
                if row is None
                else HitMetadata(row[0], None if row[1] is None else timestamp(row[1]))
            )

        return StoreCase(
            store, expire, metadata, lambda: block_lookup(store, monkeypatch)
        )

    try:
        yield factory
    finally:
        for store in stores:
            await store.aclose()


@pytest.fixture
async def sqlite_store(tmp_path: Path) -> AsyncIterator[SQLiteStore]:
    path = tmp_path / "store.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    store = await SQLiteStore.connect(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    try:
        yield store
    finally:
        await store.aclose()
