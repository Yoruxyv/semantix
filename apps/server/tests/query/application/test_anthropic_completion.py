"""Anthropic completion approval must precede QueryService cache writes."""

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
from app.providers.adapters.anthropic import AnthropicProvider
from app.providers.adapters.mock import MockEmbeddingProvider
from app.query.application.service import QueryService
from semantix_cache import CacheClosedError
from tests.providers.support import mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend

TEXT_BLOCKS: list[dict[str, object]] = [
    {"type": "text", "text": " first "},
    {"type": "text", "text": " second "},
]
TOOL_BLOCK: dict[str, object] = {
    "type": "tool_use",
    "id": "toolu_fixture",
    "name": "lookup",
    "input": {},
}


@asynccontextmanager
async def anthropic_query(
    stop_fields: dict[str, object], content: list[dict[str, object]]
) -> AsyncIterator[tuple[QueryService, InMemoryCacheBackend, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "fixture-no-access"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert json.loads(request.content) == {
            "model": "generation-model",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "completion integrity"}],
        }
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg_completion_fixture",
                "type": "message",
                "role": "assistant",
                "model": "generation-model",
                "content": content,
                "stop_sequence": None,
                "usage": {"input_tokens": 8, "output_tokens": 32},
                **stop_fields,
            },
        )

    client = mock_client(handler)
    try:
        async with client:
            provider = AnthropicProvider(
                client=client,
                api_key="fixture-no-access",
                base_url="https://api.example.test",
                generation_model="generation-model",
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
    ("stop_fields", "content"),
    [
        *[
            pytest.param({"stop_reason": reason}, TEXT_BLOCKS, id=name)
            for name, reason in (
                ("max-tokens", "max_tokens"),
                ("context-limit", "model_context_window_exceeded"),
                ("unknown-reason", "fixture-private-reason"),
                ("null-reason", None),
                ("malformed-reason", []),
            )
        ],
        pytest.param(
            {"stop_reason": "tool_use"}, [*TEXT_BLOCKS, TOOL_BLOCK], id="tool-directed"
        ),
        pytest.param(
            {"stop_reason": "pause_turn"},
            [
                *TEXT_BLOCKS,
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_fixture",
                    "name": "web_search",
                    "input": {"query": "fixture"},
                },
            ],
            id="paused",
        ),
        pytest.param(
            {"stop_reason": "refusal"},
            [{"type": "text", "text": "fixture-private-refusal"}],
            id="refusal",
        ),
        *[
            pytest.param(fields, [*TEXT_BLOCKS, TOOL_BLOCK], id=f"mixed-tool-{name}")
            for name, fields in (
                ("end-turn", {"stop_reason": "end_turn"}),
                ("omitted", {}),
            )
        ],
        pytest.param(
            {"stop_reason": "end_turn"},
            [{"type": "text", "text": " \t\n "}],
            id="blank",
        ),
    ],
)
async def test_rejected_anthropic_completion_is_never_written_or_confirmed(
    stop_fields: dict[str, object], content: list[dict[str, object]]
) -> None:
    async with anthropic_query(stop_fields, content) as (service, backend, requests):
        with (
            patch.object(backend.store, "put", wraps=backend.store.put) as put,
            patch.object(
                backend.store, "record_hit", wraps=backend.store.record_hit
            ) as confirm,
        ):
            for _ in range(2):
                with pytest.raises(InvalidProviderResponseError) as caught:
                    await service.execute("completion integrity")
                assert caught.value.status_code == 502
                assert caught.value.error_code == "invalid_upstream_response"
                assert (
                    caught.value.public_detail
                    == "The AI service returned an invalid response."
                )
                assert "fixture-private" not in str(caught.value)
                assert (
                    await backend.store.inspect_entry(
                        prompt_cache_key("completion integrity"),
                        namespaces=("default",),
                    )
                    is None
                )
            assert len(requests) == 2
            put.assert_not_awaited()
            confirm.assert_not_awaited()
            stats = await backend.stats("default")
            assert stats.size == 0
            assert stats.hits == 0


@pytest.mark.parametrize(
    ("stop_fields", "content"),
    [
        pytest.param({"stop_reason": "end_turn"}, TEXT_BLOCKS, id="end-turn"),
        pytest.param(
            {"stop_reason": "stop_sequence", "stop_sequence": "END"},
            TEXT_BLOCKS,
            id="stop-sequence",
        ),
        pytest.param({}, TEXT_BLOCKS, id="omitted"),
        pytest.param(
            {"stop_reason": "end_turn"},
            [
                {
                    "type": "thinking",
                    "thinking": "fixture-private-reasoning",
                    "signature": "Zml4dHVyZQ==",
                },
                {"type": "redacted_thinking", "data": "Zml4dHVyZQ=="},
                *TEXT_BLOCKS,
            ],
            id="thinking-is-not-answer-text",
        ),
    ],
)
async def test_terminal_or_omitted_anthropic_metadata_remains_cacheable(
    stop_fields: dict[str, object], content: list[dict[str, object]]
) -> None:
    async with anthropic_query(stop_fields, content) as (service, backend, requests):
        with patch.object(backend.store, "put", wraps=backend.store.put) as put:
            first = await service.execute("completion integrity")
            put.assert_awaited_once()
        entry = await backend.store.inspect_entry(
            prompt_cache_key("completion integrity"), namespaces=("default",)
        )
        assert entry is not None
        assert entry.hit_count == 0
        assert entry.response == first.response == "first\nsecond"
        assert entry.created_at.tzinfo is not None
        assert not first.cache_hit
        assert first.provider_called
        assert not first.generation_skipped
        with patch.object(
            backend.store, "record_hit", wraps=backend.store.record_hit
        ) as confirm:
            repeat = await service.execute("completion integrity")
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
