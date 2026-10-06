"""Standalone third-party-style consumer: no repository test helpers needed."""

from collections.abc import AsyncIterator

import pytest

from examples import custom_store
from examples.custom_store import CompanyCacheStore
from examples.store_conformance import SPACE, StoreCase, StoreConformance, StoreFactory
from semantix_cache import EmbeddingSpace


class TestCompanyStore(StoreConformance):
    """The existing independently written dictionary adapter; no built-in base."""

    @pytest.fixture
    async def store_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> AsyncIterator[StoreFactory]:
        stores: list[CompanyCacheStore] = []
        now = [0.0]
        monkeypatch.setattr(custom_store, "monotonic", lambda: now[0])

        async def factory(
            capacity: int = 32,
            ttl: float | None = None,
            *,
            space: EmbeddingSpace = SPACE,
        ) -> StoreCase:
            store = CompanyCacheStore(
                embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
            )
            stores.append(store)

            async def expire() -> None:
                now[0] += 31536001

            # This nonblocking example has no persisted counters or pending I/O.
            return StoreCase(store, expire)

        try:
            yield factory
        finally:
            for store in stores:
                await store.aclose()
