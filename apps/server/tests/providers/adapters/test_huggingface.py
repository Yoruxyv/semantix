import httpx
import pytest

from app.core.exceptions import (
    InvalidProviderResponseError,
)
from app.providers.adapters.huggingface import HuggingFaceProvider
from tests.providers.support import (
    MockHandler,
    mock_client,
    no_wait_retrying,
)
from tests.support import TEST_EMBEDDING_DIMENSIONS


def provider(
    handler: MockHandler,
) -> HuggingFaceProvider:
    return HuggingFaceProvider(
        client=mock_client(handler),
        api_key="test",
        inference_base_url="https://example.test",
        chat_base_url="https://chat.example.test",
        embedding_model="embed",
        generation_model="generate",
        embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
        max_new_tokens=32,
        retry_factory=no_wait_retrying,
    )


@pytest.mark.asyncio
async def test_retries_then_succeeds() -> None:
    calls = 0

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal calls
        calls += 1

        if calls < 3:
            return httpx.Response(
                503,
                request=request,
            )

        return httpx.Response(
            200,
            request=request,
            json=[[1.0] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 1)],
        )

    assert (
        len(await provider(handler).create_embedding("x")) == TEST_EMBEDDING_DIMENSIONS
    )
    assert calls == 3


@pytest.mark.asyncio
async def test_generation() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test"
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "answer",
                        },
                    },
                ],
            },
        )

    assert await provider(handler).generate("x") == "answer"


@pytest.mark.asyncio
async def test_malformed_embedding() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={},
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).create_embedding("x")
