import os

import asyncpg
import pytest

from app.cache.infrastructure.database import initialize_official_schema


@pytest.fixture(autouse=True)
async def initialize_disposable_pg(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("pgvector") is None:
        return
    url = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=1, command_timeout=10)
    try:
        await initialize_official_schema(pool)
    finally:
        await pool.close()
