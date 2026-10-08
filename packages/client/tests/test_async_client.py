import gzip
import json
from typing import cast

import httpx
import pytest

from semantix_client import (
    CachePolicy,
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixRateLimitError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
    SemantixValidationError,
)

from .conftest import TrackingByteStream, make_async_client, query_response


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

    client = make_async_client(
        base_url="https://example.com",
        token="async-token",
        transport=httpx.MockTransport(handler),
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
async def test_async_query_serializes_requested_cache_ttl() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        assert payload["cache_ttl_seconds"] == 900
        return httpx.Response(200, json=query_response())

    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        await client.query("question", cache_ttl_seconds=900)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "pgvector", "redis"])
async def test_async_health_and_readiness(backend: str) -> None:
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
                "cache_backend": backend,
                "evaluation_dataset_storage": "session",
            },
        )

    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert (await client.health()).status == "ok"
        assert (await client.ready()).cache_backend == backend


@pytest.mark.asyncio
async def test_async_timeout_is_safe_and_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private timeout detail", request=request)

    async with make_async_client(
        base_url="https://example.com",
        token="async-secret",
        transport=httpx.MockTransport(handler),
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
    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(lambda request: response),
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
    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(lambda request: response),
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
    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(lambda request: response),
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

    async with make_async_client(
        base_url="https://example.com",
        token=token,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SemantixServerError) as caught:
            await client.query("question")
    assert token not in str(caught.value)
    assert caught.value.detail == "Leaked [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception_type", "retry_after"),
    [
        (403, SemantixAuthorizationError, None),
        (422, SemantixValidationError, None),
        (429, SemantixRateLimitError, "5"),
        (500, SemantixServerError, None),
    ],
)
async def test_async_http_errors_are_typed(
    status: int,
    exception_type: type[SemantixAPIError],
    retry_after: str | None,
) -> None:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    async with make_async_client(
        base_url="https://example.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                json={"error": "safe_code", "detail": "Safe detail."},
                headers=headers,
            )
        ),
    ) as client:
        with pytest.raises(exception_type) as caught:
            await client.query("question")
    assert caught.value.status_code == status
    assert caught.value.retry_after_seconds == (5 if retry_after else None)
