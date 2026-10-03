import json

import httpx
import pytest

from app.core.exceptions import (
    InvalidProviderResponseError,
    ProviderRequestError,
    ProviderRetryableError,
)
from app.providers.adapters.ollama import OllamaProvider
from tests.providers.support import (
    MockHandler,
    mock_client,
    no_wait_retrying,
)
from tests.support import TEST_EMBEDDING_DIMENSIONS, unit_vector


def provider(handler: MockHandler) -> OllamaProvider:
    return OllamaProvider(
        client=mock_client(handler),
        base_url="http://ollama.test:11434",
        embedding_model="embedding-model",
        generation_model="generation-model",
        embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
        max_new_tokens=32,
        retry_factory=no_wait_retrying,
    )


@pytest.mark.asyncio
async def test_posts_current_embedding_payload_and_parses_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        assert json.loads(request.content) == {
            "model": "embedding-model",
            "input": "prompt",
            "dimensions": TEST_EMBEDDING_DIMENSIONS,
        }
        return httpx.Response(
            200,
            request=request,
            json={"embeddings": [unit_vector()]},
        )

    assert await provider(handler).create_embedding("prompt") == unit_vector()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"embeddings": []},
        {"embeddings": [["not-a-number", 0.0, 0.0, 0.0]]},
        {"embeddings": [[1.0]]},
        {"embeddings": [unit_vector(), unit_vector()]},
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_embedding_payloads(
    payload: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=payload,
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).create_embedding("prompt")


@pytest.mark.asyncio
async def test_posts_non_streaming_generation_payload_and_parses_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        assert json.loads(request.content) == {
            "model": "generation-model",
            "prompt": "prompt",
            "stream": False,
            "options": {
                "num_predict": 32,
            },
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "response": "Ollama answer",
                "done": True,
            },
        )

    assert await provider(handler).generate("prompt") == "Ollama answer"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"response": None},
        {"response": "   "},
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_generation_payloads(
    payload: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=payload,
        )

    with pytest.raises(InvalidProviderResponseError):
        await provider(handler).generate("prompt")


@pytest.mark.asyncio
async def test_retries_server_failure_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"response": "recovered"},
        )

    assert await provider(handler).generate("prompt") == "recovered"
    assert calls == 3


@pytest.mark.asyncio
async def test_network_failures_exhaust_retry_policy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "local connection failed",
            request=request,
        )

    with pytest.raises(ProviderRetryableError):
        await provider(handler).generate("prompt")


@pytest.mark.asyncio
async def test_provider_error_does_not_expose_prompt_or_body() -> None:
    prompt = "private prompt value"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            request=request,
            json={"error": f"rejected {prompt}"},
        )

    with pytest.raises(ProviderRequestError) as error:
        await provider(handler).generate(prompt)

    assert prompt not in str(error.value)
    assert "rejected" not in str(error.value)
