from collections.abc import Callable

import httpx
import pytest

from semantix import SemantixClient


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
