import json

import httpx
import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.providers.adapters.gemini import GeminiProvider
from tests.providers.support import MockHandler, mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS


def provider(
    handler: MockHandler, *, dimensions: int = TEST_EMBEDDING_DIMENSIONS
) -> GeminiProvider:
    return GeminiProvider(
        client=mock_client(handler),
        api_key="gemini-secret",
        base_url="https://api.example.test/v1beta",
        embedding_model="models/embedding-model",
        generation_model="models/generation-model",
        embedding_dimensions=dimensions,
        max_new_tokens=32,
    )


@pytest.mark.asyncio
async def test_parses_embedding_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path.endswith("/models/embedding-model:embedContent")
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert json.loads(request.content) == {
            "model": "models/embedding-model",
            "content": {"parts": [{"text": "prompt"}]},
            "outputDimensionality": TEST_EMBEDDING_DIMENSIONS,
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "embedding": {
                    "values": [
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                },
            },
        )

    assert await provider(handler).create_embedding("prompt") == [
        1.0,
        0.0,
        0.0,
        0.0,
    ]


@pytest.mark.asyncio
async def test_parses_generation_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path.endswith("/models/generation-model:generateContent")
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "Gemini answer",
                                },
                            ],
                        },
                    },
                ],
            },
        )

    assert await provider(handler).generate("prompt") == "Gemini answer"


@pytest.mark.asyncio
async def test_rejects_malformed_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"candidates": []},
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).generate("prompt")


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_dimensions", [768, 3072])
async def test_requested_dimensions_are_not_silently_changed(
    returned_dimensions: int,
) -> None:
    values = [1.0] + [0.0] * (returned_dimensions - 1)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(request.content) == {
            "model": "models/embedding-model",
            "content": {"parts": [{"text": "prompt"}]},
            "outputDimensionality": 768,
        }
        return httpx.Response(200, json={"embedding": {"values": values}})

    if returned_dimensions == 768:
        assert (
            await provider(handler, dimensions=768).create_embedding("prompt") == values
        )
    else:
        with pytest.raises(InvalidProviderResponseError):
            await provider(handler, dimensions=768).create_embedding("prompt")
    assert calls == 1
