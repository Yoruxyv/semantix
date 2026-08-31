import os

import pytest

from semantix_client import (
    AsyncSemantixClient,
    CachePolicy,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixClient,
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
        assert not miss.cache_hit and miss.provider_called
        assert hit.cache_hit and hit.generation_skipped and not hit.provider_called
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
        assert not read_only_first.cache_hit and read_only_first.provider_called
        assert not read_only_second.cache_hit and read_only_second.provider_called

        client.query("sdk refresh prompt", namespace="refresh")
        refreshed = client.query(
            "sdk refresh prompt",
            namespace="refresh",
            policy=CachePolicy.REFRESH,
            cache_ttl_seconds=60,
        )
        assert not refreshed.cache_hit and refreshed.provider_called

        client.query("sdk bypass prompt", namespace="bypass")
        bypassed = client.query(
            "sdk bypass prompt",
            namespace="bypass",
            policy=CachePolicy.BYPASS,
        )
        assert not bypassed.cache_hit and bypassed.provider_called

        client.query("sdk private prompt", namespace="private")
        private = client.query(
            "sdk private prompt",
            namespace="private",
            policy=CachePolicy.PRIVATE,
        )
        assert not private.cache_hit and private.provider_called

        with pytest.raises(SemantixAuthorizationError):
            client.query("unauthorized", namespace="other")

    with SemantixClient(base_url=base_url, token="invalid-token") as invalid:
        with pytest.raises(SemantixAuthenticationError):
            invalid.query("invalid token", namespace="normal")


@pytest.mark.asyncio
async def test_async_client_crosses_real_http_query_boundary() -> None:
    base_url, token = integration_settings()
    async with AsyncSemantixClient(base_url=base_url, token=token) as client:
        result = await client.query(
            "sdk async prompt",
            namespace="async",
            cache_ttl_seconds=60,
        )
        assert result.response == "[mock provider] sdk async prompt"
        assert not result.cache_hit and result.provider_called
