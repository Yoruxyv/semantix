"""Real-file HTTP and authorization coverage; no database-specific routes."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.cache.infrastructure.sqlite_setup import initialize_sqlite
from app.core.config import Settings
from app.factory import create_app
from app.providers.factory import create_default_provider_registry
from semantix_cache import CacheEntry, CacheStoreError, EmbeddingSpace
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores.sqlite import SQLiteStore


@pytest.fixture
async def sqlite_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[FastAPI, list[int]]]:
    clock = [database.now_us()]
    monkeypatch.setattr(database, "now_us", lambda: clock[0])
    settings = Settings.model_validate(
        {
            "embedding_provider": "mock",
            "generation_provider": "mock",
            "mock_embedding_dimensions": 4,
            "cache_backend": "sqlite",
            "cache_sqlite_path": str(tmp_path / "http.db"),
            "max_cache_size": 4,
            "cache_ttl_seconds": 60,
            "allowed_origins": ["http://localhost"],
            "rate_limit": "10000/minute",
            "auth_mode": "token",
            "auth_principals": [
                {
                    "name": name,
                    "role": role,
                    "namespaces": scope,
                    "token_sha256": sha256(name.encode()).hexdigest(),
                }
                for name, role, scope in [
                    ("reader", "viewer", ["alpha"]),
                    ("writer", "operator", ["alpha"]),
                    ("alpha-admin", "admin", ["alpha"]),
                    ("global-admin", "admin", ["*"]),
                ]
            ],
        }
    )
    selected = create_default_provider_registry(settings).resolve("mock", "mock")
    await initialize_sqlite(settings, metadata=selected.embedding_metadata)
    await SQLiteStore.initialize_schema(
        tmp_path / "http.db",
        embedding_space=EmbeddingSpace(identity="unrelated", dimensions=4),
        max_size=4,
        default_ttl_seconds=60,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app, clock


def authorization(name: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + name}


async def test_inspection_authorization_exact_totals_and_no_side_effects(
    sqlite_app: tuple[FastAPI, list[int]],
) -> None:
    app, clock = sqlite_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    store = cast(OfficialStoreBackend, cache._backend).store
    await cache.store("Straße topic", "x" * 300, namespace="alpha")
    await cache.store("another topic", "short answer", namespace="alpha")
    await cache.store("private topic", "beta answer", namespace="beta")
    await cache.store("expired topic", "old answer", namespace="alpha", ttl_seconds=1)
    clock[0] += 1_000_000
    key = prompt_cache_key("Straße topic", namespace="alpha")
    before = await store.inspect_entry(key, namespaces=("alpha",))
    assert before is not None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/cache/stats")).status_code == 401
        for sort in ("newest", "oldest", "most_hit", "nearest_expiry"):
            response = await client.get(
                "/api/v1/cache/entries",
                headers=authorization("reader"),
                params={"search": "STRASSE", "sort": sort, "limit": 1},
            )
            assert response.status_code == 200
            page = response.json()
            assert page["total"] == 1
            assert len(page["items"]) == 1
            item = page["items"][0]
            assert item["response"] is None
            assert "embedding" not in item
            assert item["response_preview_truncated"] is True
        page = (
            await client.get(
                "/api/v1/cache/entries",
                headers=authorization("reader"),
                params={"offset": 1, "limit": 1},
            )
        ).json()
        assert page["total"] == 2
        assert len(page["items"]) == 1
        assert not page["has_more"]
        detail = await client.get(
            "/api/v1/cache/entries/" + key, headers=authorization("reader")
        )
        assert detail.status_code == 200
        assert detail.json()["response"] == "x" * 300
        assert (
            await client.get(
                "/api/v1/cache/entries",
                headers=authorization("reader"),
                params={"namespace": "beta"},
            )
        ).status_code == 403
        hidden = []
        for missing in (
            prompt_cache_key("private topic", namespace="beta"),
            prompt_cache_key("expired topic", namespace="alpha"),
            "f" * 64,
        ):
            response = await client.get(
                "/api/v1/cache/entries/" + missing, headers=authorization("reader")
            )
            assert response.status_code == 404
            hidden.append(response.json())
        assert hidden[0] == hidden[1] == hidden[2]
        for role in ("reader", "writer"):
            assert (
                await client.delete("/api/v1/cache", headers=authorization(role))
            ).status_code == 403
        assert (
            await client.put(
                "/api/v1/cache/threshold",
                headers=authorization("alpha-admin"),
                json={"threshold": 0.9},
            )
        ).status_code == 403
        assert (
            await client.delete(
                "/api/v1/cache/entries/"
                + prompt_cache_key("private topic", namespace="beta"),
                headers=authorization("alpha-admin"),
            )
        ).status_code == 404
    after = await store.inspect_entry(key, namespaces=("alpha",))
    assert after == before
    assert (await cache.stats("alpha")).hits == 0


async def test_scoped_and_binding_scoped_admin_clear(
    sqlite_app: tuple[FastAPI, list[int]],
) -> None:
    app, _ = sqlite_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    path = app.state.settings.cache_sqlite_path.get_secret_value()
    async with await SQLiteStore.connect(
        path,
        embedding_space=EmbeddingSpace(identity="unrelated", dimensions=4),
        max_size=4,
        default_ttl_seconds=60,
    ) as other:
        await other.put(
            CacheEntry(
                cache_key=prompt_cache_key("other", namespace="beta"),
                namespace="beta",
                prompt="other",
                response="preserved",
                embedding=(1, 0, 0, 0),
                created_at=datetime.now(UTC),
            )
        )
        await cache.store("alpha row", "alpha answer", namespace="alpha")
        await cache.store("beta row", "beta answer", namespace="beta")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.delete(
                    "/api/v1/cache/entries/"
                    + prompt_cache_key("alpha row", namespace="alpha"),
                    headers=authorization("alpha-admin"),
                )
            ).status_code == 200
            await cache.store("alpha row", "replacement", namespace="alpha")
            assert (
                await client.delete(
                    "/api/v1/cache", headers=authorization("alpha-admin")
                )
            ).status_code == 200
            assert (await cache.stats("alpha")).size == 0
            assert (await cache.stats("beta")).size == 1
            assert (
                await client.delete(
                    "/api/v1/cache", headers=authorization("global-admin")
                )
            ).status_code == 200
            assert (await cache.stats()).size == 0
            assert (await other.inspect_entries()).total == 1


async def test_semantic_threshold_confirmation_ttl_and_restart_readiness(
    sqlite_app: tuple[FastAPI, list[int]],
) -> None:
    app, clock = sqlite_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    store = cast(OfficialStoreBackend, cache._backend).store
    await cache.store(
        "source source", "supported cached response", namespace="alpha", ttl_seconds=1
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.put(
                "/api/v1/cache/threshold",
                headers=authorization("global-admin"),
                json={"threshold": 1.0},
            )
        ).status_code == 200
        hit = await client.post(
            "/api/v1/query",
            headers=authorization("writer"),
            json={"prompt": "source", "namespace": "alpha"},
        )
        assert hit.status_code == 200
        assert hit.json()["cache_hit"] is True
        assert hit.json()["similarity_score"] == pytest.approx(1.0, rel=0, abs=0)
        key = prompt_cache_key("source source", namespace="alpha")
        confirmed = await store.inspect_entry(key, namespaces=("alpha",))
        assert confirmed is not None
        assert confirmed.hit_count == 1
        clock[0] += 1_000_000
        expired = await client.post(
            "/api/v1/query",
            headers=authorization("writer"),
            json={"prompt": "source", "namespace": "alpha"},
        )
        assert expired.status_code == 200
        assert expired.json()["cache_hit"] is False
        ready = await client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["cache_backend"] == "sqlite"
        diagnostics = await client.get(
            "/api/v1/diagnostics", headers=authorization("global-admin")
        )
        assert diagnostics.json()["cache_backend"] == "sqlite"
        assert "http.db" not in diagnostics.text
        assert "cache_sqlite_path" not in diagnostics.text
        metrics = await client.get(
            "/api/v1/metrics", headers=authorization("global-admin")
        )
        assert metrics.status_code == 200


async def test_revision_invalidated_at_actual_confirmation_boundary(
    sqlite_app: tuple[FastAPI, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = sqlite_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    await cache.store("source", "stale cached answer", namespace="alpha")
    original = SQLiteStore.record_hit
    confirmations: list[bool] = []

    async def invalidate(
        store: SQLiteStore, key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        assert await store.delete_entry(key, namespace=namespace)
        result = await original(
            store, key, namespace=namespace, expected_created_at=expected_created_at
        )
        confirmations.append(result)
        return result

    monkeypatch.setattr(SQLiteStore, "record_hit", invalidate)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/query",
            headers=authorization("writer"),
            json={"prompt": "source", "namespace": "alpha"},
        )
    assert response.status_code == 200
    assert response.json()["cache_hit"] is False
    assert response.json()["provider_called"] is True
    assert response.json()["response"] != "stale cached answer"
    assert confirmations == [False]
    assert (await cache.stats("alpha")).hits == 0


async def test_concurrent_cold_requests_use_existing_coalescing(
    sqlite_app: tuple[FastAPI, list[int]],
) -> None:
    app, _ = sqlite_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/query",
                    headers=authorization("writer"),
                    json={"prompt": "cold source", "namespace": "alpha"},
                )
                for _ in range(8)
            )
        )
        assert all(response.status_code == 200 for response in responses)
        assert sum(response.json()["provider_called"] for response in responses) == 1
        assert (
            await client.post(
                "/api/v1/query",
                headers=authorization("writer"),
                json={"prompt": "cold source", "namespace": "alpha"},
            )
        ).json()["cache_hit"] is True


async def test_readiness_and_http_storage_errors_are_sanitized(
    sqlite_app: tuple[FastAPI, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = sqlite_app

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise CacheStoreError("private sentinel must not escape")

    monkeypatch.setattr(SQLiteStore, "inspect_entries", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ready = await client.get("/ready")
        assert ready.status_code == 503
        assert "private sentinel" not in ready.text
        diagnostics = await client.get(
            "/api/v1/diagnostics", headers=authorization("global-admin")
        )
        assert diagnostics.status_code == 200
        assert diagnostics.json()["cache_readiness"] == "unavailable"
        stats = await client.get("/api/v1/cache/stats", headers=authorization("reader"))
        assert stats.status_code == 500
        assert "private sentinel" not in stats.text
