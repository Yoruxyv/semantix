"""Run with a clean installed artifact and runtime dependencies only."""

import asyncio
import importlib
import sys
import tempfile
import threading
from importlib.resources import files
from pathlib import Path

from semantix_cache import AsyncSemanticCache
from tests.wheel_smoke import Adapter


async def main() -> None:
    assert "sqlite3" not in sys.modules
    before = set(threading.enumerate())
    module = importlib.import_module("semantix_cache.stores.sqlite")
    assert set(threading.enumerate()) == before
    assert all(name not in sys.modules for name in ("redis", "asyncpg", "httpx"))
    assert module.__file__ is not None
    assert "site-packages" in Path(module.__file__).parts
    assert (
        files("semantix_cache.stores.sqlite_migrations")
        .joinpath("0001_cache.sql")
        .read_bytes()
        .startswith(b"CREATE TABLE")
    )
    adapter = Adapter()

    async def generate(prompt: str) -> str:
        return "completed"

    with tempfile.TemporaryDirectory(prefix="semantix-sqlite-wheel-") as directory:
        path = Path(directory) / "cache.db"
        await module.SQLiteStore.initialize_schema(
            path, embedding_space=adapter.embedding_space
        )
        async with (
            await module.SQLiteStore.connect(
                path, embedding_space=adapter.embedding_space
            ) as store,
            AsyncSemanticCache(embedder=adapter, store=store) as cache,
        ):
            first = await cache.resolve("first", generate=generate)
            second = await cache.resolve("second", generate=generate)
            assert first.cache_written and first.provider_called
            assert second.cache_hit and second.generation_skipped
        async with (
            await module.SQLiteStore.connect(
                path, embedding_space=adapter.embedding_space
            ) as store,
            AsyncSemanticCache(embedder=adapter, store=store) as cache,
        ):
            assert await cache.get("after reopen") is not None
            assert await cache.clear() == 1
    assert not any(
        thread.name.startswith("semantix-sqlite") for thread in threading.enumerate()
    )
    print(
        "Installed SQLite migration, dependency isolation, persistence and owned cleanup verified"
    )


if __name__ == "__main__":
    asyncio.run(main())
