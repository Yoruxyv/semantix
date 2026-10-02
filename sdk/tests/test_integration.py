import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from semantix_client import (
    AsyncSemantixClient,
    CachePolicy,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixClient,
    SemantixRateLimitError,
    SemantixServerError,
    SemantixValidationError,
)

pytestmark = pytest.mark.integration


def integration_settings() -> tuple[str, str]:
    base_url = os.environ.get("SEMANTIX_INTEGRATION_URL")
    token = os.environ.get("SEMANTIX_INTEGRATION_TOKEN")
    if base_url is None or token is None:
        pytest.skip("live Semantix integration environment is not configured")
    return base_url, token


def test_sync_client_crosses_real_http_query_boundary() -> None:
    base_url, token = integration_settings()
    with SemantixClient(base_url=base_url, token=token) as client:
        assert client.health().status == "ok"
        assert client.ready().status == "ready"

        miss = client.query(
            "sdk normal prompt",
            namespace="normal",
            cache_ttl_seconds=60,
        )
        hit = client.query("sdk normal prompt", namespace="normal")
        assert not miss.cache_hit
        assert miss.provider_called
        assert hit.cache_hit
        assert hit.generation_skipped
        assert not hit.provider_called
        assert hit.matched_prompt == "sdk normal prompt"
        assert hit.matched_cache_key is not None

        read_only_first = client.query(
            "sdk read-only prompt",
            namespace="read-only",
            policy=CachePolicy.READ_ONLY,
        )
        read_only_second = client.query(
            "sdk read-only prompt",
            namespace="read-only",
            policy=CachePolicy.READ_ONLY,
        )
        assert not read_only_first.cache_hit
        assert read_only_first.provider_called
        assert not read_only_second.cache_hit
        assert read_only_second.provider_called

        client.query("sdk refresh prompt", namespace="refresh")
        refreshed = client.query(
            "sdk refresh prompt",
            namespace="refresh",
            policy=CachePolicy.REFRESH,
            cache_ttl_seconds=60,
        )
        assert not refreshed.cache_hit
        assert refreshed.provider_called

        client.query("sdk bypass prompt", namespace="bypass")
        bypassed = client.query(
            "sdk bypass prompt",
            namespace="bypass",
            policy=CachePolicy.BYPASS,
        )
        assert not bypassed.cache_hit
        assert bypassed.provider_called

        client.query("sdk private prompt", namespace="private")
        private = client.query(
            "sdk private prompt",
            namespace="private",
            policy=CachePolicy.PRIVATE,
        )
        assert not private.cache_hit
        assert private.provider_called

        with pytest.raises(SemantixAuthorizationError):
            client.query("unauthorized", namespace="other")
        with pytest.raises(SemantixValidationError):
            client.query(
                "invalid ttl",
                namespace="normal",
                policy=CachePolicy.READ_ONLY,
                cache_ttl_seconds=60,
            )
        with pytest.raises(SemantixValidationError):
            client.query("wildcard", namespace="*")

    with (
        SemantixClient(base_url=base_url, token="invalid-token") as invalid,
        pytest.raises(SemantixAuthenticationError),
    ):
        invalid.query("invalid token", namespace="normal")


@pytest.mark.asyncio
async def test_async_client_crosses_real_http_query_boundary() -> None:
    base_url, token = integration_settings()
    async with AsyncSemantixClient(base_url=base_url, token=token) as client:
        assert (await client.health()).status == "ok"
        assert (await client.ready()).status == "ready"
        first = await client.query(
            "sdk async normal", namespace="async", cache_ttl_seconds=60
        )
        second = await client.query("sdk async normal", namespace="async")
        assert first.response == "[mock provider] sdk async normal"
        assert not first.cache_hit
        assert first.provider_called
        assert second.cache_hit
        assert second.generation_skipped
        assert not second.provider_called
        for policy in (
            CachePolicy.READ_ONLY,
            CachePolicy.REFRESH,
            CachePolicy.BYPASS,
            CachePolicy.PRIVATE,
        ):
            result = await client.query(
                f"sdk async {policy.value}", namespace="async", policy=policy
            )
            assert not result.cache_hit
            assert result.provider_called
        with pytest.raises(SemantixAuthorizationError):
            await client.query("unauthorized", namespace="other")
        with pytest.raises(SemantixValidationError):
            await client.query(
                "bad ttl",
                namespace="async",
                policy=CachePolicy.BYPASS,
                cache_ttl_seconds=60,
            )

    async with AsyncSemantixClient(base_url=base_url, token="invalid-token") as invalid:
        with pytest.raises(SemantixAuthenticationError):
            await invalid.query("invalid token", namespace="async")


def test_real_http_rate_limit_without_retry_after() -> None:
    base_url, token = integration_settings()
    caught_error: SemantixRateLimitError | None = None

    with SemantixClient(base_url=base_url, token=token) as client:
        for _ in range(120):
            try:
                client.query("sdk rate probe", namespace="normal")
            except SemantixRateLimitError as error:
                caught_error = error
                break

    if caught_error is None:
        pytest.fail("The configured 100/minute query limit did not reject 120 calls")

    assert caught_error.status_code == 429
    assert caught_error.retry_after_seconds is None


@pytest.mark.asyncio
async def test_real_http_error_headers_and_server_failure() -> None:
    class ErrorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status = 503 if self.path.startswith("/server/") else 429
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if self.path.startswith("/retry/"):
                self.send_header("Retry-After", "7")
            self.end_headers()
            self.wfile.write(b'{"error":"test_error","detail":"Test failure."}')

        def log_message(
            self,
            format: str,  # noqa: A002 - matches BaseHTTPRequestHandler signature
            *args: object,
        ) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ErrorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for prefix, error_type, retry_after in (
            ("retry", SemantixRateLimitError, 7),
            ("no-retry", SemantixRateLimitError, None),
            ("server", SemantixServerError, None),
        ):
            base_url = f"http://127.0.0.1:{server.server_port}/{prefix}"
            with SemantixClient(base_url=base_url) as sync:
                with pytest.raises(error_type) as caught:
                    sync.ready()
                assert caught.value.retry_after_seconds == retry_after
            async with AsyncSemantixClient(base_url=base_url) as async_:
                with pytest.raises(error_type) as caught:
                    await async_.ready()
                assert caught.value.retry_after_seconds == retry_after
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
