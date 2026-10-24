"""Real PostgreSQL hit-confirmation failures at the official HTTP boundary."""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.factory import create_app
from app.providers.protocols import GenerationProvider
from app.query.application.service import QueryService
from semantix_cache import CacheClosedError
from semantix_cache.stores.pgvector import PgVectorStore

pytestmark = pytest.mark.pgvector


@dataclass(frozen=True)
class HitState:
    response: str
    created_at: datetime
    expires_at: datetime
    hit_count: int
    last_accessed_at: datetime | None
    access_order: int


async def persisted_hit(
    pool: asyncpg.Pool,
    store: PgVectorStore,
    namespace: str,
    key: str,
) -> HitState:
    """Read authoritative state through a connection independent of the store."""
    row = await pool.fetchrow(
        """SELECT response, created_at, expires_at, hit_count,
                  last_accessed_at, access_order
           FROM semantix_cache.workbench_cache_entries
           WHERE embedding_space=$1 AND embedding_dimensions=$2
             AND namespace=$3 AND cache_key=$4""",
        store.embedding_space.identity,
        store.embedding_space.dimensions,
        namespace,
        key,
    )
    assert row is not None
    assert isinstance(row["created_at"], datetime)
    assert isinstance(row["expires_at"], datetime)
    return HitState(
        response=row["response"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        hit_count=row["hit_count"],
        last_accessed_at=row["last_accessed_at"],
        access_order=row["access_order"],
    )


@pytest.mark.parametrize("committed", [False, True], ids=["before-commit", "lost-ack"])
async def test_uncertain_hit_commit_does_not_report_success_or_replay(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    committed: bool,
) -> None:
    """Preserve uncertain native effects without reporting a confirmed HTTP hit."""
    url = os.environ["PGVECTOR_TEST_DATABASE_URL"]  # Parent fixture guards absence.
    settings = Settings(
        cache_backend="pgvector",
        cache_pgvector_schema="semantix_cache",
        cache_pgvector_table_prefix="workbench_",
        database_url=url,
        database_pool_min_size=2,
        database_pool_max_size=3,
        embedding_provider="mock",
        generation_provider="mock",
        cache_ttl_seconds=600,
        max_cache_size=10,
        rate_limit="1000/minute",
        auth_mode="disabled",
        coordination_backend="memory",
        prompt_typo_correction_enabled=False,
        allowed_origins=["http://localhost:5173"],
    )
    app = create_app(settings)
    namespace = "pg_hit_" + uuid4().hex
    prompt = "uncertain hit acknowledgement"
    key = prompt_cache_key(prompt, namespace=namespace)
    payload = {"prompt": prompt, "namespace": namespace}

    async with asyncio.timeout(30):
        async with app.router.lifespan_context(app):
            backend = cast(OfficialStoreBackend, app.state.semantic_cache._backend)
            store = backend.store
            assert isinstance(store, PgVectorStore)
            pool = store._pool
            service = cast(QueryService, app.state.query_service)
            provider = cast(GenerationProvider, app.state.generation_provider)

            async with (
                asyncpg.create_pool(
                    url, min_size=1, max_size=1, command_timeout=5
                ) as inspection,
                pool.acquire(timeout=2) as unrelated,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client,
            ):
                unrelated_pid = unrelated.get_server_pid()
                with (
                    patch.object(store, "put", wraps=store.put) as put,
                    patch.object(
                        provider, "generate", wraps=provider.generate
                    ) as generate,
                ):
                    seed = await client.post("/api/v1/query", json=payload)
                    assert seed.status_code == 200
                    assert seed.json()["cache_hit"] is False
                    assert seed.json()["provider_called"] is True
                    initial = await persisted_hit(inspection, store, namespace, key)
                    assert initial.hit_count == 0
                    assert initial.expires_at > initial.created_at

                    control = await client.post("/api/v1/query", json=payload)
                    assert control.status_code == 200
                    assert control.json()["cache_hit"] is True
                    before = await persisted_hit(inspection, store, namespace, key)
                    assert before.hit_count == 1
                    assert before.created_at.utcoffset() is not None
                    assert before.expires_at.utcoffset() is not None

                    execute = asyncpg.Connection.execute
                    fetchval = asyncpg.Connection.fetchval
                    selected: asyncpg.Connection[asyncpg.Record] | None = None
                    updates = 0
                    commits = 0
                    updated = asyncio.Event()
                    committed_once = asyncio.Event()
                    terminated_before_commit = asyncio.Event()

                    async def observe_update(
                        connection: asyncpg.Connection[asyncpg.Record],
                        query: str,
                        *args: object,
                        column: int = 0,
                        **options: float | None,
                    ) -> object:
                        nonlocal selected, updates
                        is_hit = (
                            args
                            == (
                                store.embedding_space.identity,
                                store.embedding_space.dimensions,
                                namespace,
                                key,
                                before.created_at,
                            )
                            and "UPDATE" in query.upper()
                            and "hit_count" in query
                        )
                        if is_hit:
                            selected = connection
                            updates += 1
                        result: object = await fetchval(
                            connection, query, *args, column=column, **options
                        )
                        if is_hit:
                            assert result is True
                            updated.set()
                        return result

                    async def interrupt_commit(
                        connection: asyncpg.Connection[asyncpg.Record],
                        query: str,
                        *args: object,
                        **options: float | None,
                    ) -> str:
                        nonlocal commits
                        if query == "COMMIT;" and connection is selected:
                            commits += 1
                            assert updated.is_set()
                            assert connection.get_server_pid() != unrelated_pid
                            if committed:
                                assert (
                                    await execute(connection, query, *args, **options)
                                    == "COMMIT"
                                )
                                committed_once.set()
                                connection.terminate()
                                raise OSError("private-hit-commit-endpoint")
                            connection.add_termination_listener(
                                lambda _: terminated_before_commit.set()
                            )
                            assert await inspection.fetchval(
                                "SELECT pg_terminate_backend($1)",
                                connection.get_server_pid(),
                            )
                            await asyncio.wait_for(
                                terminated_before_commit.wait(), timeout=2
                            )
                        return await execute(connection, query, *args, **options)

                    with monkeypatch.context() as fault:
                        fault.setattr(asyncpg.Connection, "fetchval", observe_update)
                        fault.setattr(asyncpg.Connection, "execute", interrupt_commit)
                        response = await client.post("/api/v1/query", json=payload)

                    assert updates == commits == 1
                    assert committed_once.is_set() is committed
                    assert terminated_before_commit.is_set() is not committed
                    assert response.status_code == CacheStorageError.status_code
                    assert response.json() == {
                        "error": CacheStorageError.error_code,
                        "detail": CacheStorageError.public_detail,
                    }
                    assert "private-hit-commit-endpoint" not in response.text

                    after = await persisted_hit(inspection, store, namespace, key)
                    assert after.hit_count == before.hit_count + int(committed)
                    assert after.created_at == before.created_at
                    assert after.expires_at == before.expires_at
                    assert after.response == before.response
                    if not committed:
                        assert after == before
                    put.assert_awaited_once()
                    generate.assert_awaited_once()
                    assert store._state.active == 0
                    assert await unrelated.fetchval("SELECT pg_backend_pid()") == (
                        unrelated_pid
                    )
                    assert pool.get_size() - pool.get_idle_size() == 1

                    # A completed shared result must not satisfy this later request.
                    async with asyncio.timeout(2):
                        await asyncio.gather(*tuple(service._coalescer._cleanup_tasks))
                    assert not service._coalescer._in_flight
                    follow = await client.post("/api/v1/query", json=payload)
                    assert follow.status_code == 200
                    assert follow.json()["cache_hit"] is True
                    assert follow.json()["provider_called"] is False
                    assert follow.json()["generation_skipped"] is True
                    assert follow.json()["matched_cache_key"] == key
                    assert (
                        datetime.fromisoformat(follow.json()["cache_entry_created_at"])
                        == before.created_at
                    )
                    recovered = await persisted_hit(inspection, store, namespace, key)
                    assert recovered.hit_count == after.hit_count + 1
                    assert recovered.created_at == before.created_at
                    assert recovered.expires_at == before.expires_at
                    assert recovered.response == before.response
                    put.assert_awaited_once()
                    generate.assert_awaited_once()
                    request.node.user_properties.extend(
                        [
                            (
                                "persisted_hit_counts",
                                f"{initial.hit_count},{before.hit_count},"
                                f"{after.hit_count},{recovered.hit_count}",
                            ),
                            ("cache_revision", before.created_at.isoformat()),
                            ("absolute_expiry", before.expires_at.isoformat()),
                            ("selected_hit_updates", updates),
                            ("selected_commit_attempts", commits),
                        ]
                    )
            assert pool.get_size() == pool.get_idle_size()
        assert service._active_requests == 0
        assert not service._coalescer._in_flight
        assert pool.get_size() == 0
        with pytest.raises(CacheClosedError):
            await store.validate_schema()
