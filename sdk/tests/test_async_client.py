import gzip
import json
from typing import cast

import httpx
import pytest

from semantix_client import (
    AsyncSemantixClient,
    CachePolicy,
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
)

from .conftest import TrackingByteStream, query_response


@pytest.mark.asyncio
async def test_async_query_serialization_and_lifecycle() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        assert request.url.path == "/api/v1/query"
        assert request.headers["accept-encoding"] == "identity"
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(
                200,
                content=b"not json",
                headers={"Content-Type": "application/json"},
            ),
            "malformed JSON",
        ),
        (
            httpx.Response(
                200,
                content=b"<html></html>",
                headers={"Content-Type": "text/html"},
            ),
            "unexpected content type",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=TrackingByteStream(b"x" * 1_048_577),
            ),
            "safety limit",
        ),
    ],
)
async def test_async_unexpected_success_body_is_safely_rejected(
    response: httpx.Response,
    message: str,
) -> None:
    async with AsyncSemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(SemantixResponseError, match=message):
            await client.query("question")


@pytest.mark.asyncio
async def test_async_encoded_success_is_rejected_before_body_iteration() -> None:
    stream = TrackingByteStream(gzip.compress(b"x" * 2_097_152))
    response = httpx.Response(
        200,
        headers={
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        stream=stream,
    )
    async with AsyncSemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(SemantixResponseError, match="content encoding"):
            await client.query("question")
    assert not stream.iterated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (401, SemantixAuthenticationError),
        (503, SemantixServerError),
    ],
)
async def test_async_encoded_error_preserves_status_type_without_reading_body(
    status: int,
    exception_type: type[SemantixAPIError],
) -> None:
    stream = TrackingByteStream(gzip.compress(b"private upstream body" * 100_000))
    response = httpx.Response(
        status,
        headers={
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        stream=stream,
    )
    async with AsyncSemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(exception_type) as caught:
            await client.query("question")
    assert caught.value.status_code == status
    assert caught.value.error_code == "http_error"
    assert not stream.iterated


@pytest.mark.asyncio
async def test_async_token_is_redacted_from_server_error() -> None:
    token = "async-super-secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": "internal_error", "detail": f"Leaked {token}"},
        )

    async with AsyncSemantixClient(
        base_url="https://example.com",
        token=token,
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SemantixServerError) as caught:
            await client.query("question")
    assert token not in str(caught.value)
    assert caught.value.detail == "Leaked [redacted]"
