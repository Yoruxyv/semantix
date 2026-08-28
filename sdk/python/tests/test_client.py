import gzip
import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import cast

import httpx
import pytest

from semantix_client import (
    CachePolicy,
    QueryResult,
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixClient,
    SemantixConfigurationError,
    SemantixRateLimitError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
    SemantixTransportError,
    SemantixValidationError,
)

from .conftest import TrackingByteStream, query_response


def request_json(request: httpx.Request) -> dict[str, object]:
    return cast(dict[str, object], json.loads(request.content))


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (CachePolicy.NORMAL, (True, True, True, False)),
        (CachePolicy.READ_ONLY, (True, True, False, False)),
        (CachePolicy.REFRESH, (True, False, True, False)),
        (CachePolicy.BYPASS, (False, False, False, False)),
        (CachePolicy.PRIVATE, (False, False, False, True)),
    ],
)
def test_query_serializes_policy_and_authentication(
    policy: CachePolicy,
    expected: tuple[bool, bool, bool, bool],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request_json(request)
        assert request.method == "POST"
        assert request.url.path == "/prefix/api/v1/query"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["authorization"] == "Bearer token-value"
        assert payload["prompt"] == "Where can I reset my password?"
        assert payload["namespace"] == "support"
        assert (
            payload["cache_enabled"],
            payload["cache_read_enabled"],
            payload["cache_write_enabled"],
            payload["private"],
        ) == expected
        return httpx.Response(200, json=query_response(additive_field="ignored"))

    with SemantixClient(
        base_url="https://semantix.example/prefix/",
        token="token-value",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        result = client.query(
            "Where can I reset my password?",
            namespace="support",
            policy=policy,
        )

    assert result.response == "answer"
    assert not result.cache_hit
    with pytest.raises(FrozenInstanceError):
        result.response = "changed"  # type: ignore[misc]


def test_token_is_optional_and_default_namespace_is_serialized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert request.url.path == "/api/v1/query"
        assert request_json(request)["namespace"] == "default"
        return httpx.Response(
            200,
            json=query_response(),
            headers={"Content-Encoding": "Identity"},
        )

    client = SemantixClient(
        base_url="http://localhost:8000/",
        _http_transport=httpx.MockTransport(handler),
    )
    client.query("question")
    client.close()
    client.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "localhost:8000",
        "ftp://localhost",
        "https://",
        "https://user:password@example.com",
        "https://example.com?query=1",
        "https://example.com#fragment",
        "https://example.com:invalid",
    ],
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(SemantixConfigurationError):
        SemantixClient(base_url=base_url)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_unbounded_or_nonpositive_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(SemantixConfigurationError):
        SemantixClient(base_url="https://example.com", timeout=timeout)


def test_blank_or_header_unsafe_token_is_rejected_without_echoing_it() -> None:
    for token in ("", "   ", "secret\r\nheader"):
        with pytest.raises(SemantixConfigurationError) as caught:
            SemantixClient(base_url="https://example.com", token=token)
        if token:
            assert token not in str(caught.value)


def test_health_and_readiness_are_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "embedding_provider": "mock",
                    "generation_provider": "mock",
                    "future": True,
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "cache_backend": "memory",
                "evaluation_dataset_storage": "session",
                "future": True,
            },
        )

    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        assert client.health().embedding_provider == "mock"
        assert client.ready().cache_backend == "memory"


def test_cache_hit_and_current_miss_variants_decode() -> None:
    responses = iter(
        [
            query_response(
                cache_hit=True,
                similarity_score=0.97,
                matched_prompt="question",
                matched_cache_key="a" * 64,
                cache_entry_created_at="2026-08-28T03:00:00Z",
                cache_entry_age_seconds=5.0,
                generation_skipped=True,
                provider_called=False,
            ),
            query_response(similarity_score=0.7),
            query_response(generation_skipped=True, provider_called=False),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        hit = client.query("question")
        nearest_miss = client.query("other")
        coalesced_miss = client.query("coalesced")

    assert hit.cache_entry_created_at is not None
    assert hit.cache_entry_created_at.utcoffset() is not None
    assert nearest_miss.similarity_score == 0.7
    assert coalesced_miss.generation_skipped
    assert not coalesced_miss.provider_called


@pytest.mark.parametrize(
    "payload",
    [
        {},
        query_response(cache_hit="false"),
        query_response(similarity_score=2),
        query_response(cache_hit=True),
        query_response(matched_prompt="unexpected"),
        query_response(latency_ms=-1),
        query_response(cache_entry_created_at="2026-08-28T03:00:00"),
    ],
)
def test_invalid_query_response_is_rejected(payload: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=transport,
    ) as client:
        with pytest.raises(SemantixResponseError):
            client.query("question")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(
                200,
                content=b"not json",
                headers={"Content-Type": "application/json"},
            ),
            "malformed JSON",
        ),
        (
            httpx.Response(
                200,
                content=b"<html></html>",
                headers={"Content-Type": "text/html"},
            ),
            "unexpected content type",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=TrackingByteStream(b"x" * 1_048_577),
            ),
            "safety limit",
        ),
    ],
)
def test_unexpected_success_body_is_safely_rejected(
    response: httpx.Response,
    message: str,
) -> None:
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(SemantixResponseError, match=message):
            client.query("question")


def test_encoded_success_is_rejected_before_body_iteration() -> None:
    stream = TrackingByteStream(gzip.compress(b"x" * 2_097_152))
    response = httpx.Response(
        200,
        headers={
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        stream=stream,
    )
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(SemantixResponseError, match="content encoding"):
            client.query("question")
    assert not stream.iterated


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (401, SemantixAuthenticationError),
        (403, SemantixAuthorizationError),
        (422, SemantixValidationError),
        (429, SemantixRateLimitError),
        (500, SemantixServerError),
        (503, SemantixServerError),
        (409, SemantixAPIError),
        (302, SemantixAPIError),
    ],
)
def test_http_errors_are_typed(
    status: int,
    exception_type: type[SemantixAPIError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": "safe_code", "detail": "Safe detail."},
            headers={"Retry-After": "12"},
        )

    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(exception_type) as caught:
            client.query("question")

    assert caught.value.status_code == status
    assert caught.value.error_code == "safe_code"
    assert caught.value.detail == "Safe detail."
    assert caught.value.retry_after_seconds == 12


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (401, SemantixAuthenticationError),
        (403, SemantixAuthorizationError),
        (422, SemantixValidationError),
        (429, SemantixRateLimitError),
        (500, SemantixServerError),
        (409, SemantixAPIError),
    ],
)
def test_encoded_http_error_preserves_status_type_without_reading_body(
    status: int,
    exception_type: type[SemantixAPIError],
) -> None:
    stream = TrackingByteStream(gzip.compress(b"private upstream body" * 100_000))
    response = httpx.Response(
        status,
        headers={
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        stream=stream,
    )
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(lambda request: response),
    ) as client:
        with pytest.raises(exception_type) as caught:
            client.query("question")
    assert caught.value.status_code == status
    assert caught.value.error_code == "http_error"
    assert not stream.iterated


def test_non_json_error_body_is_not_exposed() -> None:
    secret_body = "<html>private upstream details</html>"
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                502,
                text=secret_body,
                headers={"Content-Type": "text/html"},
            )
        ),
    ) as client:
        with pytest.raises(SemantixServerError) as caught:
            client.query("question")
    assert secret_body not in str(caught.value)


def test_malformed_json_error_body_preserves_status_category() -> None:
    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
        ),
    ) as client:
        with pytest.raises(SemantixServerError) as caught:
            client.query("question")
    assert caught.value.status_code == 503
    assert caught.value.error_code == "http_error"


def test_token_is_redacted_from_server_error() -> None:
    token = "super-secret-token"
    with SemantixClient(
        base_url="https://example.com",
        token=token,
        _http_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                500,
                json={"error": "internal_error", "detail": f"Leaked {token}"},
            )
        ),
    ) as client:
        with pytest.raises(SemantixServerError) as caught:
            client.query("question")
    assert token not in str(caught.value)
    assert caught.value.detail == "Leaked [redacted]"


@pytest.mark.parametrize(
    ("error", "exception_type"),
    [
        (httpx.ReadTimeout("secret transport detail"), SemantixTimeoutError),
        (httpx.ConnectError("secret transport detail"), SemantixTransportError),
    ],
)
def test_transport_failures_are_safe_and_not_retried(
    error: httpx.RequestError,
    exception_type: type[SemantixTransportError],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error

    with SemantixClient(
        base_url="https://example.com",
        token="secret-token",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(exception_type) as caught:
            client.query("question")
    assert calls == 1
    assert "secret" not in str(caught.value)


def test_server_failure_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503, json={"error": "service_unavailable", "detail": None}
        )

    with SemantixClient(
        base_url="https://example.com",
        _http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SemantixServerError):
            client.query("question")
    assert calls == 1


def test_context_manager_and_explicit_close_release_client(
    client_for: Callable[[httpx.MockTransport], SemantixClient],
) -> None:
    client = client_for(
        httpx.MockTransport(lambda request: httpx.Response(200, json=query_response()))
    )
    with client:
        client.query("question")
        assert not client._transport._client.is_closed
    assert client._transport._client.is_closed


def test_query_result_type_is_public() -> None:
    result = QueryResult(
        response="answer",
        cache_hit=False,
        similarity_score=None,
        similarity_threshold=0.92,
        matched_prompt=None,
        matched_cache_key=None,
        cache_entry_created_at=None,
        cache_entry_age_seconds=None,
        generation_skipped=False,
        provider_called=True,
        latency_ms=1,
    )
    assert result.response == "answer"
