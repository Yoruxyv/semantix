import httpx
import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.providers.adapters.anthropic import AnthropicProvider
from tests.providers.support import MockHandler, mock_client


def provider(handler: MockHandler) -> AnthropicProvider:
    return AnthropicProvider(
        client=mock_client(handler),
        api_key="anthropic-secret",
        base_url="https://api.example.test",
        generation_model="generation-model",
        max_new_tokens=32,
    )


@pytest.mark.asyncio
async def test_parses_generation_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            request=request,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": "Anthropic answer",
                    },
                ],
            },
        )

    assert await provider(handler).generate("prompt") == "Anthropic answer"


@pytest.mark.asyncio
async def test_rejects_malformed_response() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"content": []},
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).generate("prompt")
