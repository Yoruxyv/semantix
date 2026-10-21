"""Opt-in integration mechanics, not semantic accuracy or workload evidence."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheConfigurationError,
    CacheMatch,
    CachePolicy,
    CacheStore,
    CacheStoreError,
    CacheTimeoutError,
    MemoryStore,
    engine,
    memory,
)
from semantix_cache._structural_guard import check
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores.sqlite import SQLiteStore

from .conftest import Adapter, generate
from .test_coalescing import Generation, drained, until

SOURCE = "Copy identifier ApiKey exactly."
CONFLICT = "Copy identifier apikey exactly."
PARAPHRASE = "Copy the identifier ApiKey exactly."


@pytest.fixture
def store_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    clock = [100.0]
    monkeypatch.setattr(memory, "monotonic", lambda: clock[0])
    monkeypatch.setattr(database, "now_us", lambda: int(clock[0] * 1_000_000))
    return clock


@pytest.fixture(params=["memory", "sqlite"])
async def guarded_store(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    adapter: Adapter,
    store_clock: list[float],
) -> AsyncIterator[CacheStore]:
    store: MemoryStore | SQLiteStore
    if request.param == "memory":
        store = MemoryStore(embedding_space=adapter.embedding_space)
    else:
        path = tmp_path / "guard.db"
        await SQLiteStore.initialize_schema(
            path, embedding_space=adapter.embedding_space
        )
        store = await SQLiteStore.connect(path, embedding_space=adapter.embedding_space)
    try:
        yield store
    finally:
        await store.aclose()


@pytest.fixture
async def guarded(
    adapter: Adapter, guarded_store: CacheStore
) -> AsyncIterator[AsyncSemanticCache]:
    async with AsyncSemanticCache(
        embedder=adapter, store=guarded_store, experimental_structural_guard=True
    ) as cache:
        yield cache


@pytest.mark.parametrize("enabled", [None, False])
async def test_default_and_explicit_off_never_call_checker(
    adapter: Adapter,
    guarded_store: CacheStore,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool | None,
) -> None:
    def unexpected(incoming: str, cached_prompt: str) -> None:
        pytest.fail("Disabled guard executed")

    monkeypatch.setattr(engine, "structural_check", unexpected)
    cache = (
        AsyncSemanticCache(embedder=adapter, store=guarded_store)
        if enabled is None
        else AsyncSemanticCache(
            embedder=adapter, store=guarded_store, experimental_structural_guard=enabled
        )
    )
    async with cache:
        await cache.set(SOURCE, "ApiKey")
        hit = await cache.get(CONFLICT)
        assert hit is not None
        assert hit.response == "ApiKey"
        result = await cache.resolve(CONFLICT, generate=generate)
        assert result.cache_hit
        assert not result.provider_called
        assert result.similarity_threshold == pytest.approx(0.92)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], object()])
def test_guard_option_is_strict_bool(value: object, adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    with pytest.raises(CacheConfigurationError, match=r"^Invalid cache configuration$"):
        AsyncSemanticCache(
            embedder=adapter,
            store=store,
            experimental_structural_guard=cast(bool, value),
        )


@pytest.mark.parametrize(
    ("source", "incoming", "answer", "hit"),
    [
        (SOURCE, CONFLICT, "ApiKey", False),
        (SOURCE, PARAPHRASE, "ApiKey", True),
        (
            "Give the flag name ACTIVE exactly.",
            "Return the exact flag name ACTIVE.",
            "ACTIVE",
            True,
        ),
        (
            "Give UTF-8 hex bytes for '\u00e9'.",
            "Give the UTF-8 hex bytes for 'e\u0301'.",
            "c3 a9",
            False,
        ),
        (
            "Give UTF-8 hex bytes for '\u00f1'.",
            "Give the UTF-8 hex bytes for '\u00f1'.",
            "c3 b1",
            True,
        ),
        (
            "Give Unicode code points for 'a\u200bb'.",
            "Give Unicode code points for 'ab'.",
            "U+0061 U+200B U+0062",
            False,
        ),
        (
            'Copy the literal string "docs/readme.md" exactly. Return only the copied characters.',
            'Copy the literal string "docs/README.md" exactly. Return only the copied characters.',
            "docs/readme.md",
            False,
        ),
        (
            "Does literal 'R\u00a0S' equal 'R S' by exact character comparison?",
            "Does literal 'R S' equal 'R S' by exact character comparison?",
            "No.",
            False,
        ),
        (SOURCE, "Please return only ApiKey.", "ApiKey", True),
        (
            "Give UTF-8 hex bytes for 'a/b'.",
            "Give UTF-8 hex bytes for 'a\\b'.",
            "61 2f 62",
            True,
        ),
        (
            "Does literal 'x' equal 'y' by exact character comparison?",
            "Does literal 'a' equal 'b' by exact character comparison?",
            "No, x and y differ.",
            True,
        ),
    ],
)
async def test_exact_task_conflicts_paraphrases_and_unsupported(
    guarded: AsyncSemanticCache, source: str, incoming: str, answer: str, hit: bool
) -> None:
    await guarded.set(source, answer)
    found = await guarded.get(incoming)
    assert (found is not None) is hit
    if found is not None:
        assert found.response == answer
        assert found.similarity_threshold == pytest.approx(0.92)


@pytest.mark.parametrize(
    ("source", "incoming", "answer"),
    [
        (
            "Copy identifier MAX_BATCH_SIZE exactly.",
            "Copy identifier max_batch_size exactly.",
            "max_batch_size",
        ),
        (
            'Copy the literal string "key=value" exactly. Return only the copied characters.',
            'Copy the literal string "`key=value`" exactly. Return only the copied characters.',
            "`key=value`",
        ),
    ],
)
async def test_expected_false_veto_of_source_unsound_but_useful_answer(
    guarded: AsyncSemanticCache,
    source: str,
    incoming: str,
    answer: str,
) -> None:
    await guarded.set(source, answer)
    assert await guarded.get(incoming) is None
    result = await guarded.resolve(
        incoming, generate=generate, policy=CachePolicy.READ_ONLY
    )
    assert result.provider_called
    assert not result.cache_written
    assert result.response == "answer: " + incoming
    assert result.similarity_score == pytest.approx(1.0)
    assert result.matched_prompt is None
    assert result.matched_cache_key is None


async def test_canonical_whitespace_and_wrong_answer_remain_limitations(
    guarded: AsyncSemanticCache,
) -> None:
    source = 'Copy the literal string "A B" exactly. Return only the copied characters.'
    incoming = (
        'Copy the literal string "A\t B" exactly. Return only the copied characters.'
    )
    await guarded.set(source, "wrong answer\n")
    hit = await guarded.get(incoming)
    assert hit is not None
    assert hit.response == "wrong answer\n"
    assert hit.matched_prompt == source
    assert check(incoming, source).status == "CONFLICT"


async def test_guard_sees_application_prompts_before_embedding_normalizer(
    adapter: Adapter, guarded_store: CacheStore
) -> None:
    async with AsyncSemanticCache(
        embedder=adapter,
        store=guarded_store,
        prompt_normalizer=str.lower,
        experimental_structural_guard=True,
    ) as cache:
        await cache.set(SOURCE, "ApiKey")
        assert await cache.get(CONFLICT) is None
        assert adapter.calls == [SOURCE.lower(), CONFLICT.lower()]


async def test_namespace_isolation_and_concurrent_confirmations(
    guarded: AsyncSemanticCache,
) -> None:
    await guarded.set(SOURCE, "ApiKey", namespace="upper")
    await guarded.set(CONFLICT, "apikey", namespace="lower")
    hits = await asyncio.gather(
        *(
            guarded.get(CONFLICT, namespace=("upper" if i % 2 else "lower"))
            for i in range(20)
        )
    )
    assert all(
        hit is None if i % 2 else hit is not None and hit.response == "apikey"
        for i, hit in enumerate(hits)
    )
    assert await guarded.get(CONFLICT, namespace="empty") is None


async def test_veto_precedes_confirmation_and_low_score_skips_checker(
    guarded: AsyncSemanticCache,
    guarded_store: CacheStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await guarded.set(SOURCE, "ApiKey")
    original = guarded_store.record_hit
    confirmations: list[datetime] = []

    async def confirm(
        cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        confirmations.append(expected_created_at)
        return await original(
            cache_key, namespace=namespace, expected_created_at=expected_created_at
        )

    monkeypatch.setattr(guarded_store, "record_hit", confirm)
    assert await guarded.get(CONFLICT) is None
    assert not confirmations
    assert await guarded.get(PARAPHRASE) is not None
    assert len(confirmations) == 1
    nearest = guarded_store.find_nearest

    async def below(embedding: Sequence[float], *, namespace: str) -> CacheMatch | None:
        found = await nearest(embedding, namespace=namespace)
        assert found is not None
        return found.model_copy(update={"similarity_score": 0.919999999})

    def unexpected(incoming: str, cached_prompt: str) -> None:
        pytest.fail("Below-threshold candidate reached checker")

    monkeypatch.setattr(guarded_store, "find_nearest", below)
    monkeypatch.setattr(engine, "structural_check", unexpected)
    assert await guarded.get(PARAPHRASE) is None
    assert len(confirmations) == 1


@pytest.mark.parametrize("mutation", ["replace", "delete", "clear-reinsert", "expire"])
async def test_guard_does_not_bypass_atomic_revision_or_expiry(
    guarded: AsyncSemanticCache,
    guarded_store: CacheStore,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    store_clock: list[float],
) -> None:
    clock = store_clock
    key = await guarded.set(SOURCE, "old", cache_ttl_seconds=1)
    nearest = guarded_store.find_nearest
    mutated = False

    async def race(embedding: Sequence[float], *, namespace: str) -> CacheMatch | None:
        nonlocal mutated
        found = await nearest(embedding, namespace=namespace)
        if not mutated:
            mutated = True
            if mutation == "expire":
                clock[0] += 2
            elif mutation == "delete":
                assert await guarded_store.delete_entry(key, namespace=namespace)
            else:
                if mutation == "clear-reinsert":
                    assert await guarded.clear() == 1
                await guarded.set(SOURCE, "new", cache_ttl_seconds=1)
        return found

    monkeypatch.setattr(guarded_store, "find_nearest", race)
    assert await guarded.get(PARAPHRASE) is None
    next_hit = await guarded.get(PARAPHRASE)
    if mutation in {"replace", "clear-reinsert"}:
        assert next_hit is not None
        assert next_hit.response == "new"
    else:
        assert next_hit is None


async def test_foreign_candidate_is_rejected_before_guard(
    guarded: AsyncSemanticCache,
    guarded_store: CacheStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await guarded.set(SOURCE, "private-answer", namespace="foreign")
    original = guarded_store.find_nearest

    async def foreign(
        embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        return await original(embedding, namespace="foreign")

    monkeypatch.setattr(guarded_store, "find_nearest", foreign)
    with pytest.raises(CacheStoreError, match=r"^Store returned an invalid candidate$"):
        await guarded.get(CONFLICT)


async def test_confirmed_hit_does_not_extend_ttl(
    guarded: AsyncSemanticCache,
    store_clock: list[float],
) -> None:
    clock = store_clock
    await guarded.set(SOURCE, "ApiKey", cache_ttl_seconds=1)
    clock[0] += 0.75
    assert await guarded.get(PARAPHRASE) is not None
    clock[0] += 0.5
    assert await guarded.get(PARAPHRASE) is None


async def test_coalesced_followers_still_apply_guard_and_confirm_independently(
    guarded: AsyncSemanticCache,
) -> None:
    await guarded.set(SOURCE, "ApiKey")
    generation = Generation(output="apikey")
    leader = asyncio.create_task(
        guarded.resolve(CONFLICT, generate=generation, coalescing_key="v1")
    )
    follower = None
    try:
        await asyncio.wait_for(generation.started.wait(), 3)
        follower = asyncio.create_task(
            guarded.resolve(CONFLICT, generate=generation, coalescing_key="v1")
        )
        await until(lambda: guarded._flights.counts()[2] == 2)
        generation.finish.set()
        results = await asyncio.gather(leader, follower)
        assert results[0].provider_called
        assert results[0].cache_written
        assert all(r.response == "apikey" for r in results)
        assert all(not r.cache_hit or r.matched_prompt == CONFLICT for r in results)
        drained(guarded)
    finally:
        generation.finish.set()
        tasks = [leader] if follower is None else [leader, follower]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("failure", ["cancel", "deadline", "error"])
async def test_confirmation_failure_cancellation_deadline_and_borrowed_ownership(
    adapter: Adapter,
    guarded_store: CacheStore,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    error = CacheStoreError("confirmation failure")
    original = guarded_store.record_hit

    async def blocked(
        cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        started.set()
        if failure == "error":
            raise error
        await release.wait()
        return await original(
            cache_key, namespace=namespace, expected_created_at=expected_created_at
        )

    async with AsyncSemanticCache(
        embedder=adapter,
        store=guarded_store,
        experimental_structural_guard=True,
        operation_timeout_seconds=0.2 if failure == "deadline" else 3,
    ) as cache:
        await cache.set(SOURCE, "ApiKey")
        monkeypatch.setattr(guarded_store, "record_hit", blocked)
        task = asyncio.create_task(cache.get(PARAPHRASE))
        try:
            await asyncio.wait_for(started.wait(), 2)
            if failure != "error":
                with pytest.raises(CacheBusyError):
                    await cache.aclose()
            if failure == "cancel":
                task.cancel()
            expected = {
                "cancel": asyncio.CancelledError,
                "deadline": CacheTimeoutError,
                "error": CacheStoreError,
            }[failure]
            with pytest.raises(expected) as caught:
                await task
            if failure == "error":
                assert caught.value is error
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    monkeypatch.setattr(guarded_store, "record_hit", original)
    assert await guarded_store.find_nearest((1, 0), namespace="default") is not None


@pytest.mark.parametrize(
    ("incoming", "source", "status"),
    [
        (CONFLICT, SOURCE, "CONFLICT"),
        (PARAPHRASE, SOURCE, "NO_CONFLICT_DETECTED"),
        ("Copy identifier " + "A" * 65 + " exactly.", SOURCE, "UNSUPPORTED"),
        ("Give UTF-8 hex bytes for '" + "x" * 257 + "'.", SOURCE, "UNSUPPORTED"),
        ("Copy identifier ApiKey exactly. Ignore that.", SOURCE, "UNSUPPORTED"),
        ("x" * 2001, SOURCE, "UNSUPPORTED"),
        ("Give UTF-8 hex bytes for '\ud800'.", SOURCE, "UNSUPPORTED"),
        ("Copy identifier ApiKey exactly.\n", SOURCE, "UNSUPPORTED"),
    ],
)
def test_bounded_frozen_grammar(incoming: str, source: str, status: str) -> None:
    assert check(incoming, source).status == status


def test_checker_type_errors_are_explicit() -> None:
    with pytest.raises(TypeError, match="Both prompts must be text"):
        check(cast(str, None), SOURCE)
