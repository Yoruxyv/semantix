import json
from typing import cast

import httpx
import pytest

from semantix import AsyncSemantixClient, CachePolicy, SemantixTimeoutError

from .conftest import query_response


@pytest.mark.asyncio
async def test_async_query_serialization_and_lifecycle() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        assert request.url.path == "/api/v1/query"
        assert request.headers["authorization"] == "Bearer async-token"
        assert payload == {
            "prompt": "question",
            "namespace": "support",
            "cache_enabled": True,
            "cache_read_enabled": False,
            "cache_write_enabled": True,
            "private": False,
        }
        return httpx.Response(200, json=query_response())

    client = AsyncSemantixClient(
        base_url="https://example.com",
        token="async-token",
        _http_transport=httpx.MockTransport(handler),
    )
    async with client:
        result = await client.query(
            "question",
            namespace="support",
            policy=CachePolicy.REFRESH,
        )
        assert result.response == "answer"
        assert not client._transport._client.is_closed
    assert client._transport._client.is_closed
    await client.aclose()


@pytest.mark.asyncio
async def test_async_health_and_readiness() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "embedding_provider": "mock",
                    "generation_provider": "mock",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "cache_backend": "memory",
                "evaluation_dataset_storage": "session",
            },
        )

    async with AsyncSemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        assert (await client.health()).status == "ok"
        assert (await client.ready()).status == "ready"


@pytest.mark.asyncio
async def test_async_timeout_is_safe_and_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private timeout detail", request=request)

    async with AsyncSemantixClient(
        base_url="https://example.com",
        token="async-secret",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SemantixTimeoutError) as caught:
            await client.query("question")
    assert calls == 1
    assert "private" not in str(caught.value)
