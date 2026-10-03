import httpx
import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.providers.adapters.gemini import GeminiProvider
from tests.providers.support import MockHandler, mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS


def provider(handler: MockHandler) -> GeminiProvider:
    return GeminiProvider(
        client=mock_client(handler),
        api_key="gemini-secret",
        base_url="https://api.example.test/v1beta",
        embedding_model="models/embedding-model",
        generation_model="models/generation-model",
        embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
        max_new_tokens=32,
    )


@pytest.mark.asyncio
async def test_parses_embedding_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path.endswith("/models/embedding-model:embedContent")
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert b'"embedContentConfig"' in request.content
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
