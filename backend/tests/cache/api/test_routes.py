from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.core.config import Settings
from app.factory import create_app
from app.query.application.service import QueryService
from tests.support import memory_backend, unit_vector


class RouteEmbeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return unit_vector()


class Provider:
    async def generate(self, prompt: str) -> str:
        return f"Generated for {prompt}"


def test_cache_inspector_routes(settings: Settings) -> None:
    app = create_app(settings)
    cache = SemanticCache(
        RouteEmbeddings(),
        memory_backend(),
        0.92,
    )
    provider = Provider()

    with TestClient(app) as client:
        app.state.semantic_cache = cache
        app.state.query_service = QueryService(
            cache,
            provider,
        )

        assert (
            client.post(
                "/api/v1/query",
                json={"prompt": "source prompt"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/query",
                json={"prompt": "similar prompt"},
            ).json()["cache_hit"]
            is True
        )

        listing_response = client.get(
            "/api/v1/cache/entries",
            params={
                "search": "source",
                "sort": "most_hit",
                "limit": 10,
            },
        )
        listing = listing_response.json()
        assert listing_response.status_code == 200
        assert listing["total"] == 1
        assert listing["has_more"] is False
        assert listing["items"][0]["prompt"] == "source prompt"
        assert listing["items"][0]["namespace"] == "default"
        assert listing["items"][0]["hit_count"] == 1
        assert listing["items"][0]["last_accessed_at"] is not None
        assert listing["items"][0]["response_preview_truncated"] is False
        assert listing["items"][0]["response"] is None
        assert "embedding" not in listing["items"][0]

        cache_key = prompt_cache_key("source prompt")
        detail_response = client.get(f"/api/v1/cache/entries/{cache_key}")
        assert detail_response.status_code == 200
        assert detail_response.json()["cache_key"] == cache_key
        assert detail_response.json()["response"] == "Generated for source prompt"
        assert "embedding" not in detail_response.json()

        delete_response = client.delete(f"/api/v1/cache/entries/{cache_key}")
        assert delete_response.json() == {
            "deleted": True,
            "cache_key": cache_key,
        }

        missing_response = client.get(f"/api/v1/cache/entries/{cache_key}")
        assert missing_response.status_code == 404
        assert missing_response.json()["error"] == "cache_entry_not_found"
        assert client.get("/api/v1/cache/entries/not-a-cache-key").status_code == 422

        client.post(
            "/api/v1/query",
            json={"prompt": "new source"},
        )
        assert client.delete("/api/v1/cache").json() == {"cleared": True}
        assert client.get("/api/v1/cache/entries").json()["items"] == []
        assert (
            client.get(
                "/api/v1/cache/entries",
                params={"sort": "unsupported"},
            ).status_code
            == 422
        )


def test_namespace_stats_filter_and_clear(settings: Settings) -> None:
    app = create_app(settings)
    cache = SemanticCache(
        RouteEmbeddings(),
        memory_backend(),
        0.92,
    )

    with TestClient(app) as client:
        app.state.semantic_cache = cache
        app.state.query_service = QueryService(cache, Provider())

        alpha_miss = client.post(
            "/api/v1/query",
            json={
                "prompt": "shared prompt",
                "namespace": "tenant-alpha",
            },
        )
        beta_miss = client.post(
            "/api/v1/query",
            json={
                "prompt": "shared prompt",
                "namespace": "tenant-beta",
            },
        )
        alpha_hit = client.post(
            "/api/v1/query",
            json={
                "prompt": "similar prompt",
                "namespace": "tenant-alpha",
            },
        )

        assert alpha_miss.json()["cache_hit"] is False
        assert beta_miss.json()["cache_hit"] is False
        assert alpha_hit.json()["cache_hit"] is True
        assert client.get("/api/v1/cache/stats").json() == {
            "size": 2,
            "hits": 1,
            "misses": 2,
            "hit_rate": 1 / 3,
        }
        assert client.get(
            "/api/v1/cache/stats",
            params={"namespace": "tenant-alpha"},
        ).json() == {
            "size": 1,
            "hits": 1,
            "misses": 1,
            "hit_rate": 0.5,
        }

        alpha_entries = client.get(
            "/api/v1/cache/entries",
            params={"namespace": "tenant-alpha"},
        ).json()
        assert alpha_entries["total"] == 1
        assert alpha_entries["items"][0]["namespace"] == "tenant-alpha"

        assert client.delete(
            "/api/v1/cache",
            params={"namespace": "tenant-alpha"},
        ).json() == {"cleared": True}
        assert (
            client.get(
                "/api/v1/cache/entries",
                params={"namespace": "tenant-alpha"},
            ).json()["total"]
            == 0
        )
        assert client.get("/api/v1/cache/stats").json() == {
            "size": 1,
            "hits": 0,
            "misses": 1,
            "hit_rate": 0.0,
        }

        assert (
            client.get(
                "/api/v1/cache/entries",
                params={"namespace": "not valid"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/query",
                json={"prompt": "one", "namespace": "not valid"},
            ).status_code
            == 422
        )


def test_threshold_routes(settings: Settings) -> None:
    app = create_app(settings)
    cache = SemanticCache(
        RouteEmbeddings(),
        memory_backend(),
        0.92,
    )

    with TestClient(app) as client:
        app.state.semantic_cache = cache

        assert client.get("/api/v1/cache/threshold").json() == {"threshold": 0.92}
        assert client.put(
            "/api/v1/cache/threshold",
            json={"threshold": 0.84},
        ).json() == {"threshold": 0.84}
        assert (
            client.put(
                "/api/v1/cache/threshold",
                json={"threshold": 1.1},
            ).status_code
            == 422
        )
