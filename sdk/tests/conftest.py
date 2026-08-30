from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest

from semantix_client import SemantixClient


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
        return SemantixClient(
            base_url="https://semantix.example",
            token="test-token",
            _http_transport=transport,
        )

    return factory
