"""Protect common wire/output contracts without importing the server from the library."""

import json
from typing import TypedDict

import httpx
import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.providers.adapters.anthropic import AnthropicProvider
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.huggingface import HuggingFaceProvider
from app.providers.adapters.ollama import OllamaProvider
from app.providers.adapters.openai import OpenAIProvider
from app.providers.protocols import EmbeddingProvider, GenerationProvider
from semantix_cache import (
    EmbeddingAdapter,
    EmbeddingError,
    EmbeddingSpace,
    GenerationError,
)
from semantix_cache.adapters.anthropic import AnthropicGenerationAdapter
from semantix_cache.adapters.gemini import (
    GeminiEmbeddingAdapter,
    GeminiGenerationAdapter,
)
from semantix_cache.adapters.huggingface import (
    HuggingFaceEmbeddingAdapter,
    HuggingFaceGenerationAdapter,
)
from semantix_cache.adapters.ollama import (
    OllamaEmbeddingAdapter,
    OllamaGenerationAdapter,
)
from semantix_cache.adapters.openai import (
    OpenAIEmbeddingAdapter,
    OpenAIGenerationAdapter,
)

NAMES = ["openai", "huggingface", "gemini", "ollama"]
GEN_NAMES = [*NAMES, "anthropic"]
SPACE = EmbeddingSpace(identity="parity:model-r1:d2:raw", dimensions=2)
BASE = "https://provider.example/v1"
LOCAL = "http://localhost:11434"
KEY = "fixture-credential-no-access"
MODEL = "org/model"  # Model-path encoding, including Gemini models/ normalization.


class Options(TypedDict):
    client: httpx.AsyncClient
    api_key: str
    base_url: str
    embedding_model: str
    generation_model: str
    embedding_dimensions: int
    max_new_tokens: int


def server(
    name: str, client: httpx.AsyncClient
) -> (
    OpenAIProvider
    | HuggingFaceProvider
    | GeminiProvider
    | OllamaProvider
    | AnthropicProvider
):
    options: Options = {
        "client": client,
        "api_key": KEY,
        "base_url": BASE,
        "embedding_model": MODEL,
        "generation_model": MODEL,
        "embedding_dimensions": 2,
        "max_new_tokens": 512,
    }
    if name == "openai":
        return OpenAIProvider(**options)
    if name == "gemini":
        options["embedding_model"] = "models/" + MODEL
        options["generation_model"] = "models/" + MODEL
        return GeminiProvider(**options)
    if name == "huggingface":
        return HuggingFaceProvider(
            client=client,
            api_key=KEY,
            inference_base_url=BASE,
            chat_base_url=BASE,
            embedding_model=MODEL,
            generation_model=MODEL,
            embedding_dimensions=2,
            max_new_tokens=512,
        )
    if name == "ollama":
        return OllamaProvider(
            client=client,
            base_url=LOCAL,
            embedding_model=MODEL,
            generation_model=MODEL,
            embedding_dimensions=2,
            max_new_tokens=512,
        )
    return AnthropicProvider(
        client=client,
        api_key=KEY,
        base_url=BASE,
        generation_model=MODEL,
        max_new_tokens=512,
    )


class EmbeddedOptions(TypedDict):
    client: httpx.AsyncClient
    api_key: str
    model: str
    base_url: str


def embedded_embedding(name: str, client: httpx.AsyncClient) -> EmbeddingAdapter:
    options: EmbeddedOptions = {
        "client": client,
        "api_key": KEY,
        "model": MODEL,
        "base_url": BASE,
    }
    if name == "openai":
        return OpenAIEmbeddingAdapter(**options, embedding_space=SPACE)
    if name == "gemini":
        options["model"] = "models/" + MODEL
        return GeminiEmbeddingAdapter(**options, embedding_space=SPACE)
    if name == "huggingface":
        return HuggingFaceEmbeddingAdapter(**options, embedding_space=SPACE)
    return OllamaEmbeddingAdapter(
        client=client, model=MODEL, base_url=LOCAL, embedding_space=SPACE
    )


def embedded_generation(name: str, client: httpx.AsyncClient) -> GenerationProvider:
    options: EmbeddedOptions = {
        "client": client,
        "api_key": KEY,
        "model": MODEL,
        "base_url": BASE,
    }
    if name == "openai":
        return OpenAIGenerationAdapter(**options)
    if name == "gemini":
        options["model"] = "models/" + MODEL
        return GeminiGenerationAdapter(**options)
    if name == "huggingface":
        return HuggingFaceGenerationAdapter(**options)
    if name == "ollama":
        return OllamaGenerationAdapter(client=client, model=MODEL, base_url=LOCAL)
    return AnthropicGenerationAdapter(**options)


def embedding_payload(name: str, *, malformed: bool) -> object:
    value = [1.0] if malformed else [3.0, 4.0]
    if name == "openai":
        return {"data": [{"embedding": value}]}
    if name == "gemini":
        return {"embedding": {"values": value}}
    if name == "huggingface":
        return [[value, value]] if malformed else [[[0.0, 0.0], [6.0, 8.0]]]
    return {"embeddings": [value]}


def generation_payload(name: str, *, malformed: bool) -> object:
    value = " " if malformed else " completed "
    if name in ("openai", "huggingface"):
        return {"choices": [{"finish_reason": "stop", "message": {"content": value}}]}
    if name == "gemini":
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": value}, {"text": value}]},
                }
            ]
        }
    if name == "anthropic":
        return {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": value},
                {"type": "text", "text": value},
            ],
        }
    return {"done": True, "done_reason": "stop", "response": value}


def assert_same_request(left: httpx.Request, right: httpx.Request) -> None:
    assert left.method == right.method == "POST"
    assert left.url == right.url
    assert json.loads(left.content) == json.loads(right.content)
    for header in (
        "authorization",
        "x-goog-api-key",
        "x-api-key",
        "anthropic-version",
        "content-type",
        "accept-encoding",
    ):
        assert left.headers.get(header) == right.headers.get(header)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("malformed", [False, True])
async def test_embedding_wire_and_output_parity(name: str, malformed: bool) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=embedding_payload(name, malformed=malformed))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = server(name, client)
        assert isinstance(provider, EmbeddingProvider)
        adapter = embedded_embedding(name, client)
        if malformed:
            with pytest.raises(InvalidProviderResponseError):
                await provider.create_embedding("test")
            with pytest.raises(EmbeddingError):
                await adapter.embed("test")
        else:
            result = await provider.create_embedding("test")
            assert tuple(result) == tuple(await adapter.embed("test"))
        assert_same_request(*requests)
        assert not client.is_closed


@pytest.mark.parametrize("name", GEN_NAMES)
@pytest.mark.parametrize("malformed", [False, True])
async def test_generation_wire_and_output_parity(name: str, malformed: bool) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=generation_payload(name, malformed=malformed))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = server(name, client)
        adapter = embedded_generation(name, client)
        if malformed:
            with pytest.raises(InvalidProviderResponseError):
                await provider.generate("test")
            with pytest.raises(GenerationError):
                await adapter.generate("test")
        else:
            assert await provider.generate("test") == await adapter.generate("test")
        assert_same_request(*requests)
        assert not client.is_closed
