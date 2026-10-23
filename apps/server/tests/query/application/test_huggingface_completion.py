"""Hugging Face completion approval precedes real QueryService cache writes."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.core.exceptions import InvalidProviderResponseError, QueryShuttingDownError
from app.embedding.service import EmbeddingService
from app.providers.adapters.huggingface import HuggingFaceProvider
from app.providers.adapters.mock import MockEmbeddingProvider
from app.query.application.service import QueryService
from semantix_cache import CacheClosedError
from tests.providers.support import mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend


@asynccontextmanager
async def huggingface_query(
    choice_fields: dict[str, object],
) -> AsyncIterator[tuple[QueryService, InMemoryCacheBackend, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fixture-private-dummy-key"
        assert json.loads(request.content) == {
            "model": "generation-model:nscale",
            "messages": [{"role": "user", "content": "completion integrity"}],
            "max_tokens": 32,
            "stream": False,
        }
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_fixture",
                "object": "chat.completion",
                "created": 1792713600,
                "model": "generation-model:nscale",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": " fixture-private-answer ",
                        },
                        **choice_fields,
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 32,
                    "total_tokens": 40,
                },
            },
        )

    client = mock_client(handler)
    try:
        async with client:
            provider = HuggingFaceProvider(
                client=client,
                api_key="fixture-private-dummy-key",
                inference_base_url=None,
                chat_base_url="https://huggingface.example.test/v1",
                embedding_model=None,
                generation_model="generation-model:nscale",
                embedding_dimensions=None,
                max_new_tokens=32,
            )
            backend = memory_backend(ttl_seconds=None)
            service = QueryService(
                SemanticCache(
                    EmbeddingService(
                        MockEmbeddingProvider(dimensions=TEST_EMBEDDING_DIMENSIONS),
                        dimensions=TEST_EMBEDDING_DIMENSIONS,
                    ),
                    backend,
                    0.92,
                ),
                provider,
            )
            try:
                async with asyncio.timeout(5):
                    yield service, backend, requests
            finally:
                async with asyncio.timeout(2):
                    try:
                        await service.aclose(grace_seconds=1)
                    finally:
                        await backend.store.aclose()
                    with pytest.raises(CacheClosedError):
                        await backend.store.inspect_entry(
                            prompt_cache_key("completion integrity"),
                            namespaces=("default",),
                        )
                    with pytest.raises(QueryShuttingDownError):
                        await service.execute("completion integrity")
    finally:
        assert client.is_closed


@pytest.mark.parametrize(
    "choice_fields",
    [
        *[
            pytest.param({"finish_reason": reason}, id=name)
            for name, reason in (
                ("length", "length"),
                ("tool-directed-reason", "tool_calls"),
                ("null-nonstreaming-reason", None),
                ("array-reason", []),
                ("object-reason", {}),
                ("numeric-reason", 1),
                ("boolean-reason", True),
            )
        ],
        # No tools are requested; mixed/contradictory responses are defensive controls.
        *[
            pytest.param(
                {
                    **metadata,
                    "message": {
                        "role": "assistant",
                        "content": "fixture-private-answer",
                        "tool_calls": [
                            {
                                "id": "call_fixture",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ],
                    },
                },
                id=name,
            )
            for name, metadata in (
                ("tool-marker-with-stop", {"finish_reason": "stop"}),
                ("tool-marker-without-reason", {}),
            )
        ],
        *[
            pytest.param(
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "fixture-private-answer",
                        "tool_calls": calls,
                    },
                },
                id=name,
            )
            for name, calls in (
                ("object-tool-calls", {}),
                ("string-tool-calls", "fixture-private-tool"),
                ("boolean-tool-calls", False),
            )
        ],
        *[
            pytest.param(
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                },
                id=name,
            )
            for name, content in (
                ("blank", " \t\n "),
                ("null-content", None),
                ("array-content", [{"type": "text", "text": "answer"}]),
            )
        ],
        pytest.param({"finish_reason": "stop", "message": []}, id="malformed-message"),
    ],
)
async def test_rejected_huggingface_completion_is_never_written_or_confirmed(
    choice_fields: dict[str, object],
) -> None:
    async with huggingface_query(choice_fields) as (service, backend, requests):
        with (
            patch.object(backend.store, "put", wraps=backend.store.put) as put,
            patch.object(
                backend.store, "record_hit", wraps=backend.store.record_hit
            ) as confirm,
        ):
            for expected_calls in (1, 2):
                with pytest.raises(InvalidProviderResponseError) as caught:
                    await service.execute("completion integrity")
                assert caught.value.status_code == 502
                assert caught.value.error_code == "invalid_upstream_response"
                assert (
                    caught.value.public_detail
                    == "The AI service returned an invalid response."
                )
                assert "fixture-private" not in str(caught.value)
                assert len(requests) == expected_calls
                assert (
                    await backend.store.inspect_entry(
                        prompt_cache_key("completion integrity"),
                        namespaces=("default",),
                    )
                    is None
                )
                put.assert_not_awaited()
                confirm.assert_not_awaited()
            stats = await backend.stats("default")
            assert stats.size == 0
            assert stats.hits == 0


@pytest.mark.parametrize(
    ("choice_fields", "answer"),
    [
        pytest.param({"finish_reason": "stop"}, "fixture-private-answer", id="stop"),
        pytest.param({}, "fixture-private-answer", id="reason-omitted"),
        # Unknown string/extension acceptance is compatibility, not route certification.
        pytest.param(
            {"finish_reason": "fixture_vendor_done"},
            "fixture-private-answer",
            id="uninterpreted-vendor-string",
        ),
        pytest.param(
            {"finish_reason": ""}, "fixture-private-answer", id="empty-string"
        ),
        *[
            pytest.param(
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": " fixture-private-answer ",
                        "tool_calls": calls,
                    },
                },
                "fixture-private-answer",
                id=name,
            )
            for name, calls in (("null-tool-calls", None), ("empty-tool-calls", []))
        ],
        pytest.param(
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "fixture-private-answer",
                    "refusal": "fixture-private-unstandardized-extension",
                },
            },
            "fixture-private-answer",
            id="unstandardized-refusal-extension",
        ),
        pytest.param(
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": " I cannot help with that. ",
                },
            },
            "I cannot help with that.",
            id="ordinary-refusal-prose",
        ),
    ],
)
async def test_completed_or_compatible_huggingface_text_remains_cacheable(
    choice_fields: dict[str, object], answer: str
) -> None:
    async with huggingface_query(choice_fields) as (service, backend, requests):
        with (
            patch.object(backend.store, "put", wraps=backend.store.put) as put,
            patch.object(
                backend.store, "record_hit", wraps=backend.store.record_hit
            ) as confirm,
        ):
            first = await service.execute("completion integrity")
            put.assert_awaited_once()
            confirm.assert_not_awaited()
            entry = await backend.store.inspect_entry(
                prompt_cache_key("completion integrity"), namespaces=("default",)
            )
            assert entry is not None
            assert entry.hit_count == 0
            assert entry.response == first.response == answer
            assert entry.created_at.tzinfo is not None
            assert not first.cache_hit
            assert first.provider_called
            assert not first.generation_skipped
            repeat = await service.execute("completion integrity")
            put.assert_awaited_once()
            confirm.assert_awaited_once_with(
                entry.cache_key,
                namespace="default",
                expected_created_at=entry.created_at,
            )
            after = await backend.store.inspect_entry(
                entry.cache_key, namespaces=("default",)
            )
            assert after is not None
            assert after.hit_count == 1
            assert after.created_at == entry.created_at == repeat.cache_entry_created_at
            assert after.response == repeat.response == first.response
            assert repeat.matched_cache_key == entry.cache_key
            assert repeat.cache_hit
            assert not repeat.provider_called
            assert repeat.generation_skipped
            assert len(requests) == 1
            stats = await backend.stats("default")
            assert stats.size == 1
            assert stats.hits == 1
