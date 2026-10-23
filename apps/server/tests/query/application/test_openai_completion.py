"""OpenAI completion approval must precede real QueryService cache writes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.core.exceptions import InvalidProviderResponseError
from app.embedding.service import EmbeddingService
from app.providers.adapters.mock import MockEmbeddingProvider
from app.providers.adapters.openai import OpenAIProvider
from app.query.application.service import QueryService
from tests.providers.support import mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend


@asynccontextmanager
async def openai_query(
    choice_fields: dict[str, object], message_fields: dict[str, object]
) -> AsyncIterator[tuple[QueryService, InMemoryCacheBackend, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-completion-fixture",
                "object": "chat.completion",
                "created": 1_792_728_000,
                "model": "generation-model",
                "choices": [
                    {
                        "index": 0,
                        **choice_fields,
                        "message": {
                            "role": "assistant",
                            "content": "fixture-private-answer",
                            **message_fields,
                        },
                    }
                ],
            },
        )

    async with mock_client(handler) as client:
        provider = OpenAIProvider(
            client=client,
            api_key="fixture-no-access",
            base_url="https://api.example.test/v1",
            embedding_model=None,
            generation_model="generation-model",
            embedding_dimensions=None,
            max_new_tokens=32,
        )
        backend = memory_backend(ttl_seconds=None)
        cache = SemanticCache(
            EmbeddingService(
                MockEmbeddingProvider(dimensions=TEST_EMBEDDING_DIMENSIONS),
                dimensions=TEST_EMBEDDING_DIMENSIONS,
            ),
            backend,
            0.92,
        )
        service = QueryService(cache, provider)
        try:
            async with asyncio.timeout(5):
                yield service, backend, requests
        finally:
            async with asyncio.timeout(2):
                await service.aclose(grace_seconds=1)
                await backend.store.aclose()


@pytest.mark.parametrize(
    ("choice_fields", "message_fields"),
    [
        *[
            pytest.param({"finish_reason": reason}, {}, id=name)
            for name, reason in (
                ("length", "length"),
                ("filtered", "content_filter"),
                ("tool-directed", "tool_calls"),
                ("legacy-function-directed", "function_call"),
                ("null-reason", None),
                ("unknown-reason", "fixture-private-reason"),
                ("malformed-reason", []),
            )
        ],
        *[
            pytest.param(choice, message, id=f"{name}-{completion}")
            for completion, choice in (
                ("stop", {"finish_reason": "stop"}),
                ("omitted", {}),
            )
            for name, message in (
                (
                    "tool-call",
                    {
                        "tool_calls": [
                            {
                                "id": "call_fixture",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ]
                    },
                ),
                (
                    "legacy-function",
                    {"function_call": {"name": "lookup", "arguments": "{}"}},
                ),
                ("refusal", {"refusal": "fixture-private-refusal"}),
            )
        ],
        pytest.param({"finish_reason": "stop"}, {"content": " \t\n "}, id="blank"),
    ],
)
async def test_rejected_openai_completion_is_never_written_or_confirmed(
    choice_fields: dict[str, object], message_fields: dict[str, object]
) -> None:
    async with openai_query(choice_fields, message_fields) as (
        service,
        backend,
        requests,
    ):
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
            assert (await backend.stats("default")).hits == 0


@pytest.mark.parametrize(
    "choice_fields", [{"finish_reason": "stop"}, {}], ids=["stop", "omitted"]
)
async def test_completed_or_omitted_openai_metadata_remains_cacheable(
    choice_fields: dict[str, object],
) -> None:
    async with openai_query(
        choice_fields, {"tool_calls": [], "function_call": None, "refusal": None}
    ) as (service, backend, requests):
        first = await service.execute("completion integrity")
        entry = await backend.store.inspect_entry(
            prompt_cache_key("completion integrity"), namespaces=("default",)
        )
        assert entry is not None
        assert entry.hit_count == 0
        assert entry.response == first.response == "fixture-private-answer"
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
