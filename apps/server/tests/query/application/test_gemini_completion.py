"""Gemini completion approval must precede real QueryService cache writes."""

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
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.mock import MockEmbeddingProvider
from app.query.application.service import QueryService
from semantix_cache import CacheClosedError
from tests.providers.support import mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend


@asynccontextmanager
async def gemini_query(
    candidate_fields: dict[str, object],
) -> AsyncIterator[tuple[QueryService, InMemoryCacheBackend, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1beta/models/generation-model:generateContent"
        assert request.headers["x-goog-api-key"] == "fixture-private-dummy-key"
        assert json.loads(request.content) == {
            "contents": [{"role": "user", "parts": [{"text": "completion integrity"}]}],
            "generationConfig": {"maxOutputTokens": 32},
        }
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [{"text": " fixture-private-answer "}],
                        },
                        **candidate_fields,
                    }
                ],
                "modelVersion": "generation-model",
                "responseId": "fixture-response",
                "usageMetadata": {
                    "promptTokenCount": 8,
                    "candidatesTokenCount": 32,
                    "totalTokenCount": 40,
                },
            },
        )

    client = mock_client(handler)
    try:
        async with client:
            provider = GeminiProvider(
                client=client,
                api_key="fixture-private-dummy-key",
                base_url="https://gemini.example.test/v1beta",
                embedding_model=None,
                generation_model="models/generation-model",
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
    "candidate_fields",
    [
        *[
            pytest.param({"finishReason": reason}, id=name)
            for name, reason in (
                ("max-tokens", "MAX_TOKENS"),
                ("safety-with-residual-text", "SAFETY"),
                ("recitation", "RECITATION"),
                ("blocklist", "BLOCKLIST"),
                ("prohibited-content", "PROHIBITED_CONTENT"),
                ("other", "OTHER"),
                ("unexpected-tool-call", "UNEXPECTED_TOOL_CALL"),
                ("unspecified-reason", "FINISH_REASON_UNSPECIFIED"),
                ("null-reason", None),
                ("unknown-reason", "fixture-private-reason"),
                ("empty-reason", ""),
                ("malformed-reason", []),
            )
        ],
        pytest.param(
            {"finishReason": "CONTINUATION", "continuationToken": "Zml4dHVyZQ=="},
            id="continuation-requires-another-request",
        ),
        # The request enables no tools/thoughts; these are defensive wire controls.
        *[
            pytest.param(
                {
                    **metadata,
                    "content": {
                        "parts": [
                            {"text": "fixture-private-answer"},
                            {"functionCall": {"name": "lookup", "args": {}}},
                        ]
                    },
                },
                id=name,
            )
            for name, metadata in (
                ("function-call-with-stop", {"finishReason": "STOP"}),
                ("function-call-without-reason", {}),
            )
        ],
        pytest.param(
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "fixture-private-answer"},
                        {"toolCall": {"toolType": "GOOGLE_SEARCH_WEB", "args": {}}},
                    ]
                },
            },
            id="server-tool-call-requires-another-turn",
        ),
        pytest.param(
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": "fixture-private-answer", "functionCall": None}]
                },
            },
            id="malformed-function-marker",
        ),
        pytest.param(
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": "fixture-private-thought", "thought": True}]
                },
            },
            id="thought-only-is-not-an-answer",
        ),
        pytest.param(
            {"finishReason": "STOP", "content": {"parts": [{"text": " \t\n "}]}},
            id="blank",
        ),
        pytest.param(
            {"finishReason": "STOP", "content": {"parts": {"text": "answer"}}},
            id="malformed-parts-container",
        ),
        pytest.param({"finishReason": "STOP", "content": None}, id="missing-content"),
    ],
)
async def test_rejected_gemini_completion_is_never_written_or_confirmed(
    candidate_fields: dict[str, object],
) -> None:
    async with gemini_query(candidate_fields) as (service, backend, requests):
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
    ("candidate_fields", "answer"),
    [
        pytest.param({"finishReason": "STOP"}, "fixture-private-answer", id="stop"),
        pytest.param({}, "fixture-private-answer", id="reason-omitted"),
        pytest.param(
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "fixture-private-thought", "thought": True},
                        {
                            "text": " fixture-private-answer ",
                            "thought": False,
                            "thoughtSignature": "Zml4dHVyZQ==",
                        },
                    ]
                },
            },
            "fixture-private-answer",
            id="only-final-text-including-signed-text",
        ),
        pytest.param(
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        None,
                        {"inlineData": {"mimeType": "image/png", "data": ""}},
                        {"text": 7},
                        {"text": " first "},
                        {"text": " \n "},
                        {"text": " second "},
                    ]
                },
            },
            "first\nsecond",
            id="legacy-part-skipping-and-joining",
        ),
    ],
)
async def test_completed_or_legacy_gemini_text_remains_cacheable(
    candidate_fields: dict[str, object], answer: str
) -> None:
    async with gemini_query(candidate_fields) as (service, backend, requests):
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
