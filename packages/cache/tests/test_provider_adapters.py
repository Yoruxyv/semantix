"""Offline provider contracts, failure bounds and borrowed-resource ownership."""

import asyncio
import inspect
import json
import time
import traceback
from collections.abc import AsyncIterator
from typing import Protocol, TypedDict

import httpx
import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheValidationError,
    EmbeddingAdapter,
    EmbeddingError,
    EmbeddingSpace,
    GenerationError,
    MemoryStore,
)
from semantix_cache.adapters import openai as openai_module
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

EMBEDDERS = ("openai", "huggingface", "gemini", "ollama")
GENERATORS = (*EMBEDDERS, "anthropic")
KINDS = tuple(
    (name, kind)
    for kind, names in (("embed", EMBEDDERS), ("generate", GENERATORS))
    for name in names
)
SPACE = EmbeddingSpace(identity="fixture:test-model:revision-1:d2:raw", dimensions=2)
TEST_KEY = "fixture-credential-no-access"
MODEL = "test-model"


class EmbeddingResource(EmbeddingAdapter, Protocol):
    async def aclose(self) -> None: ...


class GenerationResource(Protocol):
    async def generate(self, prompt: str) -> str: ...
    async def aclose(self) -> None: ...


class Options(TypedDict):
    client: httpx.AsyncClient
    model: str
    timeout_seconds: float
    max_response_bytes: int


def embedder(
    name: str, client: httpx.AsyncClient, *, timeout: float = 30.0, limit: int = 1048576
) -> EmbeddingResource:
    options: Options = {
        "client": client,
        "model": MODEL,
        "timeout_seconds": timeout,
        "max_response_bytes": limit,
    }
    if name == "openai":
        return OpenAIEmbeddingAdapter(
            **options, api_key=TEST_KEY, embedding_space=SPACE
        )
    if name == "huggingface":
        return HuggingFaceEmbeddingAdapter(
            **options, api_key=TEST_KEY, embedding_space=SPACE
        )
    if name == "gemini":
        return GeminiEmbeddingAdapter(
            **options, api_key=TEST_KEY, embedding_space=SPACE
        )
    if name == "ollama":
        return OllamaEmbeddingAdapter(**options, embedding_space=SPACE)
    raise AssertionError("Unknown test fixture")


def generator(
    name: str, client: httpx.AsyncClient, *, timeout: float = 30.0, limit: int = 1048576
) -> GenerationResource:
    options: Options = {
        "client": client,
        "model": MODEL,
        "timeout_seconds": timeout,
        "max_response_bytes": limit,
    }
    if name == "openai":
        return OpenAIGenerationAdapter(**options, api_key=TEST_KEY)
    if name == "huggingface":
        return HuggingFaceGenerationAdapter(**options, api_key=TEST_KEY)
    if name == "gemini":
        return GeminiGenerationAdapter(**options, api_key=TEST_KEY)
    if name == "ollama":
        return OllamaGenerationAdapter(**options)
    if name == "anthropic":
        return AnthropicGenerationAdapter(**options, api_key=TEST_KEY)
    raise AssertionError("Unknown test fixture")


def embedding_payload(name: str, value: object = (3.0, 4.0)) -> object:
    if isinstance(value, tuple):
        value = list(value)
    if name == "openai":
        return {"data": [{"embedding": value}]}
    if name == "huggingface":
        return [value]
    if name == "gemini":
        return {"embedding": {"values": value}}
    return {"embeddings": [value]}


def generation_payload(name: str, value: object = " completed ") -> object:
    if name in ("openai", "huggingface"):
        return {"choices": [{"message": {"content": value}, "finish_reason": "stop"}]}
    if name == "gemini":
        return {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": value}]}}
            ]
        }
    if name == "anthropic":
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": value}]}
    return {"response": value, "done": True, "done_reason": "stop"}


async def invoke(
    name: str,
    kind: str,
    client: httpx.AsyncClient,
    *,
    request_bound: float = 30.0,
    limit: int = 1048576,
) -> object:
    if kind == "embed":
        return await embedder(name, client, timeout=request_bound, limit=limit).embed(
            "private prompt"
        )
    return await generator(name, client, timeout=request_bound, limit=limit).generate(
        "private prompt"
    )


@pytest.mark.parametrize(("name", "kind"), KINDS)
async def test_success_request_and_borrowed_client(name: str, kind: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = embedding_payload(name) if kind == "embed" else generation_payload(name)
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await invoke(name, kind, client) == (
            (3.0, 4.0) if kind == "embed" else "completed"
        )
        request = requests[0]
        assert request.method == "POST"
        assert request.headers["accept-encoding"] == "identity"
        body = json.loads(request.content)
        if kind == "embed":
            adapter = embedder(name, client)
            assert adapter.embedding_space == SPACE
            await adapter.aclose()
            await adapter.aclose()
            with pytest.raises(CacheClosedError):
                await adapter.embed("test")
        else:
            gen = generator(name, client)
            await gen.aclose()
            with pytest.raises(CacheClosedError):
                await gen.generate("test")
            if name in ("openai", "huggingface", "ollama"):
                assert body["stream"] is False
        assert not client.is_closed
        if name != "ollama":
            assert (
                TEST_KEY
                in request.headers[
                    {"gemini": "x-goog-api-key", "anthropic": "x-api-key"}.get(
                        name, "authorization"
                    )
                ]
            )
        assert TEST_KEY not in repr(adapter if kind == "embed" else gen)


@pytest.mark.parametrize(("name", "kind"), KINDS)
@pytest.mark.parametrize("status", [302, 400, 401, 429, 503])
async def test_http_error_is_safe_and_not_retried(
    name: str, kind: str, status: int
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            text=TEST_KEY + "private body",
            headers={"Location": "https://other.example"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        with pytest.raises(
            EmbeddingError if kind == "embed" else GenerationError
        ) as caught:
            await invoke(name, kind, client)
        assert str(status) in str(caught.value)
        assert caught.value.__cause__ is not None
        rendered = "".join(traceback.format_exception(caught.value))
        assert TEST_KEY not in rendered
        assert "private body" not in rendered
        assert calls == 1


@pytest.mark.parametrize(("name", "kind"), KINDS)
@pytest.mark.parametrize(
    "failure", ["json", "declared-size", "stream-size", "encoded", "request", "timeout"]
)
async def test_transport_failures_are_bounded_and_safe(
    name: str, kind: str, failure: str
) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        if failure == "request":
            raise httpx.ConnectError(
                TEST_KEY + "https://private.example?secret private prompt",
                request=request,
            )
        if failure == "timeout":
            await asyncio.sleep(10)
        if failure == "declared-size":
            return httpx.Response(
                200, headers={"Content-Length": "1000"}, stream=Chunks([b"{}"])
            )
        if failure == "stream-size":
            return httpx.Response(
                200, stream=Chunks([b"[" + b" " * 16, b" " * 16 + b"]"])
            )
        if failure == "encoded":
            return httpx.Response(
                200,
                headers={"Content-Encoding": "br"},
                stream=Chunks([b"private body"]),
            )
        return httpx.Response(200, content=TEST_KEY + "private response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(
            EmbeddingError if kind == "embed" else GenerationError
        ) as caught:
            await invoke(name, kind, client, request_bound=0.02, limit=32)
        rendered = "".join(traceback.format_exception(caught.value))
        assert TEST_KEY not in rendered
        assert "private.example" not in rendered
        assert "private response" not in rendered
        assert not client.is_closed


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("name", EMBEDDERS)
@pytest.mark.parametrize(
    "value",
    [
        [],
        [1.0],
        [1.0, 2.0, 3.0],
        [True, 2],
        [0.0, 0.0],
        [float("nan"), 1.0],
        [float("inf"), 1.0],
        ["private response", 1.0],
        None,
    ],
)
async def test_invalid_embedding_rejected(name: str, value: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=json.dumps(embedding_payload(name, value))
            )
        )
    ) as client:
        with pytest.raises(EmbeddingError):
            await embedder(name, client).embed("test")


@pytest.mark.parametrize("name", GENERATORS)
@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "x" * 100001, 1, {"private": "response"}],
    ids=["none", "empty", "blank", "oversized", "number", "mapping"],
)
async def test_invalid_generation_rejected(name: str, value: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=generation_payload(name, value))
        )
    ) as client:
        with pytest.raises(GenerationError):
            await generator(name, client).generate("test")


@pytest.mark.parametrize("name", GENERATORS)
async def test_incomplete_generation_never_written(name: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(
            (
                "/embeddings",
                ":embedContent",
                "/api/embed",
                "/pipeline/feature-extraction",
            )
        ):
            return httpx.Response(200, json=embedding_payload("openai"))
        payload = generation_payload(name)
        assert isinstance(payload, dict)
        if name in ("openai", "huggingface"):
            payload = {
                "choices": [
                    {"message": {"content": "partial"}, "finish_reason": "length"}
                ]
            }
        elif name == "gemini":
            payload = {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "partial"}]},
                    }
                ]
            }
        elif name == "anthropic":
            payload["stop_reason"] = "max_tokens"
        else:
            payload["done_reason"] = "length"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        emb = embedder("openai", client)
        async with (
            MemoryStore(embedding_space=SPACE) as store,
            AsyncSemanticCache(embedder=emb, store=store) as cache,
        ):
            with pytest.raises(GenerationError):
                await cache.resolve("test", generate=generator(name, client).generate)
            assert await cache.get("test") is None


@pytest.mark.parametrize(("name", "kind"), KINDS)
async def test_cancellation_and_busy_close(name: str, kind: str) -> None:
    started = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled request resumed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        task: asyncio.Task[object]
        if kind == "embed":
            emb = embedder(name, client)
            task = asyncio.create_task(emb.embed("test"))
            resource: EmbeddingResource | GenerationResource = emb
        else:
            gen = generator(name, client)
            task = asyncio.create_task(gen.generate("test"))
            resource = gen
        await asyncio.wait_for(started.wait(), timeout=1)
        with pytest.raises(CacheBusyError):
            await resource.aclose()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await resource.aclose()
        assert not client.is_closed


@pytest.mark.parametrize(("name", "kind"), KINDS)
async def test_input_validation_precedes_http(name: str, kind: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid input reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        call = (
            embedder(name, client).embed
            if kind == "embed"
            else generator(name, client).generate
        )
        with pytest.raises(CacheValidationError):
            await call(" " * 2001)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 10**400])
def test_invalid_timeout_configuration(timeout: float) -> None:
    client = httpx.AsyncClient()
    with pytest.raises(CacheConfigurationError):
        embedder("openai", client, timeout=timeout)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://private.example",
        "https://user:password@private.example",
        "https://private.example?token=value",
        "https://private.example#secret",
        "https://private.example:99999",
        "https://private.example\\path",
    ],
)
def test_invalid_hosted_url_is_safe(base_url: str) -> None:
    with pytest.raises(CacheConfigurationError) as caught:
        OpenAIEmbeddingAdapter(
            client=httpx.AsyncClient(),
            api_key=TEST_KEY,
            model=MODEL,
            embedding_space=SPACE,
            base_url=base_url,
        )
    assert "private.example" not in str(caught.value)


async def test_huggingface_pooling_and_readonly_metadata() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[[[1, 2], [3, 4]]])
        )
    ) as client:
        adapter = embedder("huggingface", client)
        assert await adapter.embed("test") == (2.0, 3.0)
        assert isinstance(
            inspect.getattr_static(type(adapter), "embedding_space"), property
        )


def test_frozen_openai_constructor() -> None:
    signature = inspect.signature(OpenAIEmbeddingAdapter)
    assert list(signature.parameters) == [
        "client",
        "api_key",
        "model",
        "embedding_space",
        "base_url",
        "timeout_seconds",
        "max_response_bytes",
    ]
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY for p in signature.parameters.values()
    )
    assert signature.parameters["base_url"].default == "https://api.openai.com/v1"
    assert signature.parameters["timeout_seconds"].default == pytest.approx(30.0)
    assert signature.parameters["max_response_bytes"].default == 1048576


@pytest.mark.parametrize(("name", "kind"), KINDS)
@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"data": []}, {"choices": [None]}],
    ids=["null", "list", "object", "empty-data", "invalid-choice"],
)
async def test_malformed_provider_shapes(name: str, kind: str, payload: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(EmbeddingError if kind == "embed" else GenerationError):
            await invoke(name, kind, client)


@pytest.mark.parametrize("name", ["openai", "huggingface", "gemini"])
async def test_tool_calls_or_refusals_require_application_handling(name: str) -> None:
    if name == "gemini":
        payload = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": "partial"},
                            {"functionCall": {"name": "tool"}},
                        ]
                    },
                }
            ]
        }
    else:
        payload = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "partial",
                        "tool_calls": [{"type": "function"}],
                    },
                }
            ]
        }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(GenerationError):
            await generator(name, client).generate("test")


@pytest.mark.parametrize("name", ["openai", "ollama"])
async def test_single_input_rejects_multiple_embeddings(name: str) -> None:
    payload = (
        {"data": [{"embedding": [1, 2]}, {"embedding": [3, 4]}]}
        if name == "openai"
        else {"embeddings": [[1, 2], [3, 4]]}
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(EmbeddingError):
            await embedder(name, client).embed("test")


async def test_multiblock_generation_excludes_thoughts() -> None:
    payload = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "private thought", "thought": True},
                        {"text": " final "},
                        {"text": " answer "},
                    ]
                },
            }
        ]
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        assert await generator("gemini", client).generate("test") == "final\nanswer"


@pytest.mark.parametrize("response", ["success", "oversized", "status"])
async def test_response_stream_always_closed(response: str) -> None:
    stream = Chunks([b'{"data":[{"embedding":[3,4]}]}'])
    status = 400 if response == "status" else 200
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, stream=stream)
        )
    ) as client:
        adapter = embedder(
            "openai", client, limit=8 if response == "oversized" else 1048576
        )
        if response == "success":
            assert tuple(await adapter.embed("test")) == (3.0, 4.0)
        else:
            with pytest.raises(EmbeddingError):
                await adapter.embed("test")
        assert stream.closed


async def test_swallowed_external_cancellation_still_propagates() -> None:
    started = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return httpx.Response(200, json=embedding_payload("openai"))
        raise AssertionError("Request unexpectedly resumed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = embedder("openai", client)
        task = asyncio.create_task(adapter.embed("test"))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await adapter.aclose()


async def test_swallowed_deadline_still_fails_safely() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return httpx.Response(200, json=embedding_payload("openai"))
        raise AssertionError("Request unexpectedly resumed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(EmbeddingError, match="deadline"):
            await embedder("openai", client, timeout=0.01).embed("test")


async def test_async_context_closes_only_adapter() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=embedding_payload("openai"))
        )
    ) as client:
        async with OpenAIEmbeddingAdapter(
            client=client, api_key=TEST_KEY, model=MODEL, embedding_space=SPACE
        ) as adapter:
            assert tuple(await adapter.embed("test")) == (3, 4)
        assert not client.is_closed
        with pytest.raises(CacheClosedError):
            await adapter.__aenter__()


@pytest.mark.parametrize("value", ["", "bad\nvalue", " bad "])
def test_invalid_configuration_text(value: str) -> None:
    with pytest.raises(CacheConfigurationError):
        OpenAIGenerationAdapter(
            client=httpx.AsyncClient(), api_key=TEST_KEY, model=value
        )


@pytest.mark.parametrize("value", ["bad value", "clé"])
def test_invalid_key_is_safe(value: str) -> None:
    with pytest.raises(CacheConfigurationError) as caught:
        OpenAIGenerationAdapter(client=httpx.AsyncClient(), api_key=value, model=MODEL)
    assert value not in str(caught.value)


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_response_limit(limit: int) -> None:
    with pytest.raises(CacheConfigurationError):
        embedder("openai", httpx.AsyncClient(), limit=limit)


@pytest.mark.parametrize(
    "base_url", ["http://localhost:11434/path", "http://localhost:11434?token=value"]
)
def test_ollama_origin_validation(base_url: str) -> None:
    with pytest.raises(CacheConfigurationError):
        OllamaGenerationAdapter(
            client=httpx.AsyncClient(), model=MODEL, base_url=base_url
        )


async def test_huggingface_zero_token_row_pooling() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[[[0, 0], [2, 4]]])
        )
    ) as client:
        assert tuple(await embedder("huggingface", client).embed("test")) == (1.0, 2.0)


@pytest.mark.parametrize(("name", "kind"), KINDS)
async def test_closed_borrowed_client_uses_integration_error(
    name: str, kind: str
) -> None:
    client = httpx.AsyncClient()
    await client.aclose()
    with pytest.raises(
        EmbeddingError if kind == "embed" else GenerationError, match="client is closed"
    ):
        await invoke(name, kind, client)


def test_constructed_invalid_metadata_is_revalidated() -> None:
    invalid = EmbeddingSpace.model_construct(identity="", dimensions=0)
    with pytest.raises(CacheConfigurationError):
        OpenAIEmbeddingAdapter(
            client=httpx.AsyncClient(),
            api_key=TEST_KEY,
            model=MODEL,
            embedding_space=invalid,
        )


async def test_anthropic_tool_block_is_not_final_text() -> None:
    payload = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "partial"},
            {"type": "tool_use", "name": "tool"},
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(GenerationError):
            await generator("anthropic", client).generate("test")


@pytest.mark.parametrize(("name", "kind"), KINDS)
async def test_programming_error_in_transport_propagates(name: str, kind: str) -> None:
    error = ValueError("Caller transport programming failure")

    def handle(request: httpx.Request) -> httpx.Response:
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(
            ValueError, match="Caller transport programming failure"
        ) as caught:
            await invoke(name, kind, client)
        assert caught.value is error


async def test_deadline_includes_provider_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_parse(payload: object) -> str:
        time.sleep(0.02)
        return "completed"

    monkeypatch.setattr(openai_module, "chat_text", slow_parse)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=generation_payload("openai"))
        )
    ) as client:
        with pytest.raises(GenerationError, match="deadline"):
            await generator("openai", client, timeout=0.01).generate("test")


async def test_unparseably_large_content_length_is_safe() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": "9" * 5000}, stream=Chunks([b"{}"])
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(EmbeddingError, match="maximum size"):
            await embedder("openai", client).embed("test")
