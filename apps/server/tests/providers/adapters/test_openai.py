import httpx
import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.providers.adapters.openai import OpenAIProvider
from tests.providers.support import MockHandler, mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS


def provider(handler: MockHandler) -> OpenAIProvider:
    return OpenAIProvider(
        client=mock_client(handler),
        api_key="openai-secret",
        base_url="https://api.example.test/v1",
        embedding_model="embedding-model",
        generation_model="generation-model",
        embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
        max_new_tokens=32,
    )


@pytest.mark.asyncio
async def test_parses_embedding_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer openai-secret"
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "embedding": [
                            1.0,
                            0.0,
                            0.0,
                            0.0,
                        ],
                    },
                ],
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
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "OpenAI answer",
                        },
                    },
                ],
            },
        )

    assert await provider(handler).generate("prompt") == "OpenAI answer"


@pytest.mark.asyncio
async def test_rejects_malformed_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"data": []},
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).create_embedding("prompt")
