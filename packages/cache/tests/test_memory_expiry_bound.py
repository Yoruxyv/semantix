from collections import OrderedDict
from collections.abc import Callable, ItemsView
from datetime import UTC, datetime

import numpy as np
import pytest

from semantix_cache import MemoryStore, memory

from .conftest import Adapter
from .test_memory import entry


class FullScanStore(MemoryStore):
    """Original main's expiry algorithm, without the new bound."""

    clock: Callable[[], float]

    def _purge(self) -> None:
        now = self.clock()
        expired = [
            key
            for key, item in self._items.items()
            if item.expires_monotonic is not None and now >= item.expires_monotonic
        ]
        for key in expired:
            self._discard(key)
            self._expirations += 1


class ObservedItems(OrderedDict[str, memory._Item]):
    scans = 0


@pytest.mark.parametrize("ttl", [None, 60.0])
async def test_reads_skip_global_scan_until_any_deadline_is_due(
    ttl: float | None, adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    async with MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=ttl
    ) as store:
        value = entry("seed")
        await store.put(value)
        items = ObservedItems(store._items)

        def observed_items() -> ItemsView[str, memory._Item]:
            items.scans += 1
            return OrderedDict.items(items)

        monkeypatch.setattr(items, "items", observed_items)
        store._items = items
        for _ in range(10):
            match = await store.find_nearest((1.0, 0.0), namespace="default")
            assert match is not None
            assert await store.record_hit(
                value.cache_key,
                namespace="default",
                expected_created_at=match.entry.created_at,
            )
        assert items.scans == 0
        now = 60.0 if ttl is not None else 1e9
        match = await store.find_nearest((1.0, 0.0), namespace="default")
        assert (match is None) == (ttl is not None)
        assert items.scans == (1 if ttl is not None else 0)
        assert store.inspection_events == (0, 1 if ttl is not None else 0)


async def test_due_read_purges_foreign_scope_and_preserves_live_revision(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    async with MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=None
    ) as store:
        foreign = entry("foreign", namespace="other")
        live = entry("live")
        await store.put(foreign, ttl_seconds=1.0)
        await store.put(live, ttl_seconds=2.0)
        match = await store.find_nearest((1.0, 0.0), namespace="default")
        assert match is not None
        now = 1.0
        assert await store.record_hit(
            live.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert foreign.cache_key not in store._items
        assert store.inspection_events == (0, 1)
        now = 2.0
        assert not await store.record_hit(
            live.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert store.inspection_events == (0, 2)
        assert store._next_expiry is None


async def test_replacement_and_removal_leave_only_a_conservative_early_bound(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    async with MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=None
    ) as store:
        first, second = entry("first"), entry("second", namespace="other")
        await store.put(first, ttl_seconds=10.0)
        await store.put(second, ttl_seconds=30.0)
        original = await store.find_nearest((1.0, 0.0), namespace="default")
        assert original is not None
        now = 5.0
        await store.put(first, ttl_seconds=40.0)
        assert store._next_expiry == 10
        now = 10.0
        current = await store.find_nearest((1.0, 0.0), namespace="default")
        assert current is not None
        assert current.entry.created_at > original.entry.created_at
        assert store._next_expiry == 30
        assert store.inspection_events == (0, 0)
        now = 20.0
        assert await store.delete_entry(second.cache_key, namespace="other")
        now = 30.0
        assert await store.record_hit(
            first.cache_key,
            namespace="default",
            expected_created_at=current.entry.created_at,
        )
        assert store._next_expiry == 45
        assert store.inspection_events == (0, 0)
        now = 45.0
        assert not await store.record_hit(
            first.cache_key,
            namespace="default",
            expected_created_at=current.entry.created_at,
        )
        assert store.inspection_events == (0, 1)


async def test_clear_and_close_reset_bound_without_resetting_counters(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("first"), ttl_seconds=1.0)
    now = 1.0
    assert await store.clear_all() == 0
    assert store._next_expiry is None
    assert store.inspection_events == (0, 1)
    await store.put(entry("second"), ttl_seconds=2.0)
    assert store._next_expiry == 3
    await store.aclose()
    assert store._next_expiry is None
    assert store.inspection_events == (0, 1)
    await store.aclose()


@pytest.mark.parametrize("seed", [17, 233, 234])
async def test_expiry_bound_matches_original_scan_through_mutations(
    seed: int, adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    rng = np.random.default_rng(seed)
    values = [
        entry(
            f"item-{i}",
            namespace=f"scope-{i % 3}",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for i in range(12)
    ]
    async with (
        MemoryStore(
            embedding_space=adapter.embedding_space,
            max_size=7,
            default_ttl_seconds=None,
        ) as store,
        FullScanStore(
            embedding_space=adapter.embedding_space,
            max_size=7,
            default_ttl_seconds=None,
        ) as oracle,
    ):
        oracle.clock = lambda: now
        for _ in range(240):
            now += float(rng.choice([0.0, 0.125, 0.5, 1.0, 3.0]))
            value = values[int(rng.integers(len(values)))]
            action = int(rng.integers(7))
            ttl = [None, 0.125, 1.0, 4.0, 60.0][int(rng.integers(5))]
            for target in (store, oracle):
                if action <= 2:
                    await target.put(value, ttl_seconds=ttl)
                elif action == 3:
                    await target.delete_entry(
                        value.cache_key, namespace=value.namespace
                    )
                elif action == 4:
                    await target.clear(namespace=value.namespace)
                elif action == 5:
                    await target.clear_all()
                else:
                    match = await target.find_nearest(
                        (1.0, 0.0), namespace=value.namespace
                    )
                    if match is not None:
                        assert await target.record_hit(
                            match.entry.cache_key,
                            namespace=value.namespace,
                            expected_created_at=match.entry.created_at,
                        )
            for target in (store, oracle):
                await target.inspect_entries(namespace="scope-0", limit=1)
            assert store.inspection_events == oracle.inspection_events
            assert list(store._items) == list(oracle._items)
            assert store._last_revision == oracle._last_revision
            for key, item in store._items.items():
                expected = oracle._items[key]
                assert item.entry.model_dump() == expected.entry.model_dump()
                assert item.expires_monotonic == expected.expires_monotonic
                assert item.hit_count == expected.hit_count
            deadlines = [
                i.expires_monotonic
                for i in store._items.values()
                if i.expires_monotonic is not None
            ]
            if deadlines:
                assert store._next_expiry is not None
                assert store._next_expiry <= min(deadlines)
