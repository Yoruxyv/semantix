from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest

from semantix_client import AsyncSemantixClient, SemantixClient


def make_client(
    *,
    base_url: str,
    token: str | None = None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> SemantixClient:
    if transport is not None:
        return SemantixClient._for_test(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
    return SemantixClient(base_url=base_url, token=token, timeout=timeout)


def make_async_client(
    *,
    base_url: str,
    token: str | None = None,
    timeout: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncSemantixClient:
    if transport is not None:
        return AsyncSemantixClient._for_test(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
    return AsyncSemantixClient(base_url=base_url, token=token, timeout=timeout)


class TrackingByteStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.iterated = False

    def __iter__(self) -> Iterator[bytes]:
        self.iterated = True
        yield self.content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        yield self.content


def query_response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "response": "answer",
        "cache_hit": False,
        "similarity_score": None,
        "similarity_threshold": 0.92,
        "matched_prompt": None,
        "matched_cache_key": None,
        "cache_entry_created_at": None,
        "cache_entry_age_seconds": None,
        "generation_skipped": False,
        "provider_called": True,
        "latency_ms": 12.5,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client_for() -> Callable[[httpx.MockTransport], SemantixClient]:
    def factory(transport: httpx.MockTransport) -> SemantixClient:
        return SemantixClient._for_test(
            base_url="https://semantix.example",
            token="test-token",
            transport=transport,
        )

    return factory
