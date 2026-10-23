"""Ollama completion approval must precede real QueryService cache writes."""

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
from app.providers.adapters.mock import MockEmbeddingProvider
from app.providers.adapters.ollama import OllamaProvider
from app.query.application.service import QueryService
from semantix_cache import CacheClosedError
from tests.providers.support import mock_client
from tests.support import TEST_EMBEDDING_DIMENSIONS, memory_backend


@asynccontextmanager
async def ollama_query(
    fields: dict[str, object],
) -> AsyncIterator[tuple[QueryService, InMemoryCacheBackend, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        assert json.loads(request.content) == {
            "model": "generation-model",
            "prompt": "completion integrity",
            "stream": False,
            "options": {"num_predict": 32},
        }
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "generation-model",
                "created_at": "2026-10-23T00:00:00Z",
                "response": " fixture-private-answer ",
                "total_duration": 1_000_000,
                "load_duration": 100_000,
                "prompt_eval_count": 8,
                "prompt_eval_duration": 100_000,
                "eval_count": 32,
                "eval_duration": 800_000,
                **fields,
            },
        )

    client = mock_client(handler)
    try:
        async with client:
            provider = OllamaProvider(
                client=client,
                base_url="http://ollama.example.test:11434",
                embedding_model=None,
                generation_model="generation-model",
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
    "fields",
    [
        *[
            pytest.param({"done": True, "done_reason": reason}, id=name)
            for name, reason in (
                ("length", "length"),
                ("load-is-not-generation", "load"),
                ("unload-is-not-generation", "unload"),
                ("unknown-reason", "fixture-private-reason"),
                ("empty-reason", ""),
                ("malformed-reason", []),
            )
        ],
        pytest.param({"done_reason": "length"}, id="length-without-done"),
        *[
            pytest.param({"done": done, "done_reason": "stop"}, id=name)
            for name, done in (
                ("nonterminal", False),
                ("null-done", None),
                ("string-done", "true"),
                ("numeric-done", 1),
            )
        ],
        pytest.param(
            {"done": True, "done_reason": "stop", "error": "fixture-private-error"},
            id="reported-error-with-text",
        ),
        pytest.param(
            {"done": True, "done_reason": "stop", "error": 0},
            id="malformed-error-with-text",
        ),
        pytest.param(
            {"done": True, "done_reason": "stop", "response": " \t\n "},
            id="blank",
        ),
        pytest.param(
            {"done": True, "done_reason": "stop", "response": 7},
            id="invalid-text",
        ),
    ],
)
async def test_rejected_ollama_completion_is_never_written_or_confirmed(
    fields: dict[str, object],
) -> None:
    async with ollama_query(fields) as (service, backend, requests):
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
    "fields",
    [
        pytest.param({"done": True, "done_reason": "stop"}, id="completed"),
        pytest.param({"done": True}, id="reason-omitted"),
        pytest.param({"done_reason": "stop"}, id="done-omitted"),
        pytest.param({}, id="markers-omitted"),
        pytest.param({"done": True, "done_reason": None}, id="legacy-null-reason"),
        pytest.param(
            {"done": True, "done_reason": "stop", "error": None}, id="null-error"
        ),
        pytest.param(
            {"done": True, "done_reason": "stop", "error": ""}, id="empty-error"
        ),
    ],
)
async def test_completed_or_legacy_ollama_metadata_remains_cacheable(
    fields: dict[str, object],
) -> None:
    async with ollama_query(fields) as (service, backend, requests):
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
            assert entry.response == first.response == "fixture-private-answer"
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
