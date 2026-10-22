"""Real verified-TLS MySQL HTTP and authorization coverage; no database-specific routes."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.official import OfficialStoreBackend
from app.cache.infrastructure.mysql_setup import initialize_mysql
from app.core.config import Settings
from app.factory import create_app
from app.providers.registry import EmbeddingMetadata
from semantix_cache import CacheEntry, CacheStoreError, EmbeddingSpace
from semantix_cache.stores.mysql import MySQLStore
from tests.cache.mysql_support import admin, mysql_settings, receipt

__all__ = ["mysql_settings"]
pytestmark = pytest.mark.mysql


@pytest.fixture
async def mysql_app(mysql_settings: Settings) -> AsyncIterator[FastAPI]:
    config = receipt()
    await initialize_mysql(
        mysql_settings,
        metadata=EmbeddingMetadata(4, "unrelated"),
        setup_user=SecretStr(str(config["user"])),
        setup_password=SecretStr(os.environ["MYSQL_TEST_PASSWORD"]),
    )
    app = create_app(mysql_settings)
    async with app.router.lifespan_context(app):
        yield app


async def expire(app: FastAPI, prompt: str) -> None:
    settings = cast(Settings, app.state.settings)
    assert settings.cache_mysql_database is not None
    await asyncio.to_thread(
        admin,
        "UPDATE semantix_entries SET expires_at_us=1 WHERE cache_key=%s",
        (prompt_cache_key(prompt, namespace="alpha").encode("ascii"),),
        database=settings.cache_mysql_database.get_secret_value(),
    )


def authorization(name: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + name}


async def test_inspection_authorization_exact_totals_and_no_side_effects(
    mysql_app: FastAPI,
) -> None:
    app = mysql_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    store = cast(OfficialStoreBackend, cache._backend).store
    await cache.store("Straße topic", "x" * 300, namespace="alpha")
    await cache.store("another topic", "short answer", namespace="alpha")
    await cache.store("private topic", "beta answer", namespace="beta")
    await cache.store("expired topic", "old answer", namespace="alpha", ttl_seconds=1)
    await expire(app, "expired topic")
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
    assert after is not None
    # Remaining TTL is a live clock observation; persisted metadata must not change.
    assert after.model_dump(exclude={"remaining_ttl_seconds"}) == before.model_dump(
        exclude={"remaining_ttl_seconds"}
    )
    assert after.remaining_ttl_seconds is not None
    assert before.remaining_ttl_seconds is not None
    assert 0 < after.remaining_ttl_seconds <= before.remaining_ttl_seconds
    assert (await cache.stats("alpha")).hits == 0


async def test_scoped_and_binding_scoped_admin_clear(
    mysql_app: FastAPI,
) -> None:
    app = mysql_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    settings = cast(Settings, app.state.settings)
    assert settings.cache_mysql_address
    assert settings.cache_mysql_tls_hostname
    assert settings.cache_mysql_ca_file
    assert settings.cache_mysql_database
    assert settings.cache_mysql_user
    assert settings.cache_mysql_password
    async with await MySQLStore.connect(
        address=settings.cache_mysql_address.get_secret_value(),
        port=settings.cache_mysql_port,
        tls_hostname=settings.cache_mysql_tls_hostname.get_secret_value(),
        ca_file=settings.cache_mysql_ca_file.get_secret_value(),
        database=settings.cache_mysql_database.get_secret_value(),
        user=settings.cache_mysql_user.get_secret_value(),
        password=settings.cache_mysql_password.get_secret_value(),
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
    mysql_app: FastAPI,
) -> None:
    app = mysql_app
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
        await expire(app, "source source")
        expired = await client.post(
            "/api/v1/query",
            headers=authorization("writer"),
            json={"prompt": "source", "namespace": "alpha"},
        )
        assert expired.status_code == 200
        assert expired.json()["cache_hit"] is False
        ready = await client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["cache_backend"] == "mysql"
        diagnostics = await client.get(
            "/api/v1/diagnostics", headers=authorization("global-admin")
        )
        assert diagnostics.json()["cache_backend"] == "mysql"
        assert "cache_mysql_password" not in diagnostics.text
        for secret in app.state.settings.configured_secrets():
            assert secret not in diagnostics.text
        metrics = await client.get(
            "/api/v1/metrics", headers=authorization("global-admin")
        )
        assert metrics.status_code == 200


async def test_revision_invalidated_at_actual_confirmation_boundary(
    mysql_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = mysql_app
    cache = cast(SemanticCache, app.state.semantic_cache)
    await cache.store("source", "stale cached answer", namespace="alpha")
    original = MySQLStore.record_hit
    confirmations: list[bool] = []

    async def invalidate(
        store: MySQLStore, key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        assert await store.delete_entry(key, namespace=namespace)
        result = await original(
            store, key, namespace=namespace, expected_created_at=expected_created_at
        )
        confirmations.append(result)
        return result

    monkeypatch.setattr(MySQLStore, "record_hit", invalidate)
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
    mysql_app: FastAPI,
) -> None:
    app = mysql_app
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
    mysql_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = mysql_app

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise CacheStoreError("private sentinel must not escape")

    monkeypatch.setattr(MySQLStore, "inspect_entries", unavailable)
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


async def test_persistence_across_application_restart(mysql_settings: Settings) -> None:
    replies: list[dict[str, object]] = []
    for _ in range(2):
        app = create_app(mysql_settings)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            result = await client.post(
                "/api/v1/query",
                headers=authorization("writer"),
                json={"prompt": "persistent response", "namespace": "alpha"},
            )
            assert result.status_code == 200
            replies.append(result.json())
    assert replies[0]["cache_hit"] is False
    assert replies[0]["provider_called"] is True
    assert replies[1]["cache_hit"] is True
    assert replies[1]["provider_called"] is False
    assert replies[0]["response"] == replies[1]["response"]
