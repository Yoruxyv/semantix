"""Execute only in an isolated installed wheel environment with the pgvector extra."""

import asyncio
import os
import sys
from datetime import UTC, datetime
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import semantix_cache
from semantix_cache import CacheEntry, EmbeddingSpace
from semantix_cache._semantics import prompt_cache_key

# Root remains minimal even when optional dependencies are installed.
assert "asyncpg" not in sys.modules
PgVectorStore = import_module("semantix_cache.stores.pgvector").PgVectorStore


async def main() -> None:
    dsn = os.environ["PGVECTOR_TEST_DATABASE_URL"]
    schema = "cache_wheel_" + uuid4().hex
    space = EmbeddingSpace(identity="wheel-persistence-v1", dimensions=2)
    async with await PgVectorStore.connect(
        dsn=dsn, embedding_space=space, schema=schema
    ) as migration:
        try:
            await migration.initialize_schema(migration_pool=migration._pool)
            await migration.put(
                CacheEntry(
                    cache_key=prompt_cache_key("wheel prompt", namespace="default"),
                    namespace="default",
                    prompt="wheel prompt",
                    response="wheel response",
                    embedding=(1.0, 0.0),
                    created_at=datetime.now(UTC),
                )
            )
            async with await PgVectorStore.connect(
                dsn=dsn, embedding_space=space, schema=schema
            ) as runtime:
                await runtime.validate_schema()
                match = await runtime.find_nearest((1, 0), namespace="default")
                assert match is not None and match.entry.response == "wheel response"
        finally:
            assert schema.startswith("cache_wheel_") and len(schema) == 44
            async with migration._pool.acquire() as connection:
                await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    assert semantix_cache.__file__ is not None
    assert "site-packages" in Path(semantix_cache.__file__).parts
    assert (
        files("semantix_cache.stores.migrations").joinpath("0001_cache.sql").is_file()
    )
    assert "app" not in sys.modules and "fastapi" not in sys.modules
    print("Installed pgvector wheel, migration resource and persistence verified")


if __name__ == "__main__":
    asyncio.run(main())
