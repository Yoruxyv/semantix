"""Release boundary checks for the intentional SDK 0.1.0 surface."""

import ast
import asyncio
import gc
import inspect
import json
import re
from collections.abc import AsyncIterator
from dataclasses import fields
from pathlib import Path

import httpx
import pytest

import semantix_client as sdk
from semantix_client.models import (
    _decode_health,
    _decode_query_result,
    _decode_readiness,
)

from .conftest import query_response

EXPORTS = {
    "AsyncSemantixClient",
    "CachePolicy",
    "HealthStatus",
    "QueryResult",
    "ReadinessStatus",
    "SemantixAPIError",
    "SemantixAuthenticationError",
    "SemantixAuthorizationError",
    "SemantixClient",
    "SemantixConfigurationError",
    "SemantixError",
    "SemantixRateLimitError",
    "SemantixResponseError",
    "SemantixServerError",
    "SemantixTimeoutError",
    "SemantixTransportError",
    "SemantixValidationError",
}
QUERY_FIELDS = (
    "response",
    "cache_hit",
    "similarity_score",
    "similarity_threshold",
    "matched_prompt",
    "matched_cache_key",
    "cache_entry_created_at",
    "cache_entry_age_seconds",
    "generation_skipped",
    "provider_called",
    "latency_ms",
)
ROOT = Path(__file__).resolve().parents[1]


def test_public_exports_models_and_signatures() -> None:
    assert set(sdk.__all__) == EXPORTS
    assert {member.name: member.value for member in sdk.CachePolicy} == {
        "NORMAL": "normal",
        "READ_ONLY": "read_only",
        "REFRESH": "refresh",
        "BYPASS": "bypass",
        "PRIVATE": "private",
    }
    assert tuple(field.name for field in fields(sdk.QueryResult)) == QUERY_FIELDS
    assert tuple(field.name for field in fields(sdk.HealthStatus)) == (
        "status",
        "embedding_provider",
        "generation_provider",
    )
    assert tuple(field.name for field in fields(sdk.ReadinessStatus)) == (
        "status",
        "cache_backend",
        "evaluation_dataset_storage",
    )
    for client_type in (sdk.SemantixClient, sdk.AsyncSemantixClient):
        constructor = inspect.signature(client_type)
        assert tuple(constructor.parameters) == ("base_url", "token", "timeout")
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in constructor.parameters.values()
        )
        assert constructor.parameters["token"].default is None
        # Exact public API signature default, not a computed float comparison.
        assert constructor.parameters["timeout"].default == 30.0  # noqa: RUF069
        query = inspect.signature(client_type.query)
        assert tuple(query.parameters) == (
            "self",
            "prompt",
            "namespace",
            "policy",
            "cache_ttl_seconds",
        )
        assert (
            query.parameters["prompt"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        assert all(
            query.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            for name in ("namespace", "policy", "cache_ttl_seconds")
        )
        assert query.parameters["namespace"].default == "default"
        assert query.parameters["policy"].default is sdk.CachePolicy.NORMAL
        assert query.parameters["cache_ttl_seconds"].default is None
        assert query.return_annotation is sdk.QueryResult
        assert (
            inspect.signature(client_type.health).return_annotation is sdk.HealthStatus
        )
        assert (
            inspect.signature(client_type.ready).return_annotation
            is sdk.ReadinessStatus
        )
    error = sdk.SemantixAPIError(
        status_code=429, error_code="rate_limited", detail=None
    )
    assert vars(error) == {
        "status_code": 429,
        "error_code": "rate_limited",
        "detail": None,
        "retry_after_seconds": None,
    }


def test_sync_async_operation_parity() -> None:
    def operations(client_type: type) -> set[str]:
        return {
            name
            for name, value in vars(client_type).items()
            if not name.startswith("_")
            and callable(value)
            and name not in {"close", "aclose"}
        }

    assert (
        operations(sdk.SemantixClient)
        == operations(sdk.AsyncSemantixClient)
        == {"query", "health", "ready"}
    )
    for operation in ("query", "health", "ready"):
        sync = getattr(sdk.SemantixClient, operation)
        async_ = getattr(sdk.AsyncSemantixClient, operation)
        assert inspect.signature(sync) == inspect.signature(async_)
        assert not inspect.iscoroutinefunction(sync)
        assert inspect.iscoroutinefunction(async_)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", list(sdk.CachePolicy))
async def test_sync_async_wire_and_decode_parity(policy: sdk.CachePolicy) -> None:
    requests: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=query_response())

    with sdk.SemantixClient._for_test(
        base_url="https://example.com", transport=httpx.MockTransport(handler)
    ) as sync:
        sync_result = sync.query("question", namespace="sample", policy=policy)
    async with sdk.AsyncSemantixClient._for_test(
        base_url="https://example.com", transport=httpx.MockTransport(handler)
    ) as async_:
        async_result = await async_.query("question", namespace="sample", policy=policy)
    assert sync_result == async_result
    assert len(requests) == 2
    assert requests[0] == requests[1]


def test_nullable_query_keys_are_required_by_decoder() -> None:
    payload = query_response()
    assert tuple(payload) == QUERY_FIELDS
    assert _decode_query_result(payload).similarity_score is None
    for name in QUERY_FIELDS:
        with pytest.raises(sdk.SemantixResponseError):
            _decode_query_result(
                {key: value for key, value in payload.items() if key != name}
            )


@pytest.mark.parametrize("provider", ["-bad", "bad space", "a" * 51, "bad/name"])
def test_health_rejects_invalid_provider_names(provider: str) -> None:
    with pytest.raises(sdk.SemantixResponseError):
        _decode_health(
            {
                "status": "ok",
                "embedding_provider": provider,
                "generation_provider": "mock",
            }
        )
    assert (
        _decode_health(
            {
                "status": "ok",
                "embedding_provider": "A:ok_1",
                "generation_provider": "mock",
            }
        ).status
        == "ok"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("cache_backend", "redis"), ("evaluation_dataset_storage", "sqlite")],
)
def test_readiness_rejects_unknown_storage(field: str, value: str) -> None:
    payload = {
        "status": "ready",
        "cache_backend": "memory",
        "evaluation_dataset_storage": "session",
    }
    payload[field] = value
    with pytest.raises(sdk.SemantixResponseError):
        _decode_readiness(payload)


def test_import_boundary_and_public_docs() -> None:
    forbidden = {
        "app",
        "backend",
        "fastapi",
        "asyncpg",
        "numpy",
        "pydantic",
        "sqlalchemy",
        "starlette",
        "psycopg",
    }
    for source in (ROOT / "src" / "semantix_client").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert text.startswith(
            "# Copyright (c) 2026 Hans Valerie\n# SPDX-License-Identifier: MIT\n"
        )
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            elif (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                    or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_module"
                    )
                )
            ):
                names = [node.args[0].value]
            else:
                continue
            assert not any(name.split(".")[0] in forbidden for name in names)
    for name in sdk.__all__:
        assert len(inspect.getdoc(getattr(sdk, name)) or "") >= 40, name


def test_readme_python_examples_compile_and_relative_links_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for example in re.findall(r"```python\n(.*?)\n```", readme, flags=re.DOTALL):
        compile(example, "sdk/README.md", "exec")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme):
        repository_prefix = "https://github.com/Yoruxyv/semantix/blob/main/"
        if target.startswith(repository_prefix):
            assert (
                ROOT.parent / target.removeprefix(repository_prefix).split("#", 1)[0]
            ).exists(), target
        elif "://" not in target and not target.startswith("#"):
            assert (ROOT / target.split("#", 1)[0]).exists(), target


@pytest.mark.asyncio
@pytest.mark.filterwarnings("error::ResourceWarning")
async def test_64_concurrent_queries_and_in_progress_cancellation() -> None:
    calls = 0
    gate = asyncio.Semaphore(8)
    started = asyncio.Event()
    streams: list[SlowStream] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        prompt = json.loads(request.content)["prompt"]
        if prompt == "slow":
            stream = SlowStream(started)
            streams.append(stream)
            return httpx.Response(
                200, headers={"Content-Type": "application/json"}, stream=stream
            )
        async with gate:
            await asyncio.sleep(0)
            return httpx.Response(200, json=query_response(response=prompt))

    client = sdk.AsyncSemantixClient._for_test(
        base_url="https://example.com", transport=httpx.MockTransport(handler)
    )
    transport_id = id(client._transport._client)
    async with client:
        results = await asyncio.wait_for(
            asyncio.gather(*(client.query(f"question-{index}") for index in range(64))),
            timeout=5,
        )
        assert len(results) == 64
        assert all(
            result.response == f"question-{index}" and result.provider_called
            for index, result in enumerate(results)
        )
        assert calls == 64
        assert id(client._transport._client) == transport_id
        pending = asyncio.create_task(client.query("slow"))
        await asyncio.wait_for(started.wait(), timeout=2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert streams[0].closed
    assert client._transport._client.is_closed
    gc.collect()


class SlowStream(httpx.AsyncByteStream):
    def __init__(self, started: asyncio.Event) -> None:
        self.started = started
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        await asyncio.Event().wait()
        yield b"{}"

    async def aclose(self) -> None:
        self.closed = True
