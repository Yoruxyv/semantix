"""SQLite schema, codecs, exact numerics, TTL and durable authority regressions."""

import asyncio
import ctypes
import sqlite3
import sys
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import FixedEmbedding, entry
from semantix_cache import (
    AsyncSemanticCache,
    CacheConfigurationError,
    CacheStoreError,
    EmbeddingSpace,
)
from semantix_cache._semantics import nearest_index, normalized_vector
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores._backends.sqlite.format import (
    HEADER,
    MAX_INT,
    MAX_US,
    decode_vector,
    micros,
    timestamp,
)
from semantix_cache.stores.sqlite import SQLiteStore

from . import sqlite_helpers
from .sqlite_helpers import connection, state

sqlite_store = sqlite_helpers.sqlite_store


@pytest.mark.parametrize(
    ("version", "threads"),
    [
        ((3, 50, 4), 3),
        ((3, 51, 2), 3),
        ((3, 52, 0), 3),
        ((3, 53, 1), 0),
        ((3, 44, 6), 3),
        ((3, 50, 7), 3),
    ],
)
async def test_runtime_gate_before_file_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int, int],
    threads: int,
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", version)
    monkeypatch.setattr(sqlite3, "threadsafety", threads)
    path = tmp_path / "absent.db"
    with pytest.raises(CacheConfigurationError, match="thread-capable"):
        await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    assert not path.exists()


async def test_missing_sqlite_does_not_break_memory() -> None:
    code = """
import sys
sys.modules['sqlite3']=None
from semantix_cache import MemoryStore
try:
    from semantix_cache.stores.sqlite import SQLiteStore
except ImportError as error:
    assert 'standard-library sqlite3' in str(error)
else:
    raise AssertionError('SQLite import accepted missing runtime')
assert 'redis' not in sys.modules and 'asyncpg' not in sys.modules
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, errors = await asyncio.wait_for(process.communicate(), 20)
        assert process.returncode == 0, errors.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


@pytest.mark.parametrize(
    "options",
    [
        {"max_size": 0},
        {"max_size": True},
        {"max_size": 5001},
        {"operation_timeout_seconds": 0},
        {"close_timeout_seconds": float("inf")},
        {"default_ttl_seconds": float("nan")},
        {"embedding_space": EmbeddingSpace(identity="wide", dimensions=16001)},
        {
            "max_size": 5000,
            "embedding_space": EmbeddingSpace(identity="wide", dimensions=16000),
        },
    ],
)
async def test_configuration_bounds(tmp_path: Path, options: dict[str, Any]) -> None:
    with pytest.raises(CacheConfigurationError):
        await SQLiteStore.connect(
            tmp_path / "absent.db", **{"embedding_space": SPACE, **options}
        )
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


@pytest.mark.parametrize(
    "name", [":memory:", "file:db?mode=rwc", "//server/cache.db", "", "bad\x00path"]
)
async def test_reject_non_owned_path(name: str) -> None:
    with pytest.raises(CacheConfigurationError):
        await SQLiteStore.connect(name, embedding_space=SPACE)


async def test_missing_foreign_empty_partial_and_policy_files(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    with pytest.raises(CacheStoreError):
        await SQLiteStore.connect(path, embedding_space=SPACE)
    assert not path.exists()
    for contents in (b"", b"foreign application data"):
        path.write_bytes(contents)
        with pytest.raises(CacheStoreError):
            await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
        assert path.read_bytes() == contents
        path.unlink()
    with connection(path) as db:
        db.execute("CREATE TABLE foreign_data(secret TEXT)")
        db.execute("INSERT INTO foreign_data VALUES('preserve me')")
    before = path.read_bytes()
    with pytest.raises(CacheStoreError):
        await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    assert path.read_bytes() == before
    path.unlink()
    await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    policy_options: tuple[dict[str, Any], ...] = (
        {"max_size": 501},
        {"default_ttl_seconds": None},
        {"embedding_space": EmbeddingSpace(identity="unregistered", dimensions=2)},
    )
    for options in policy_options:
        with pytest.raises(CacheConfigurationError):
            await SQLiteStore.connect(path, **{"embedding_space": SPACE, **options})
    with connection(path) as db:
        assert db.execute("SELECT count(*) FROM binding_state").fetchone() == (1,)


@pytest.mark.parametrize(
    "mutation",
    [
        "PRAGMA application_id=0",
        "PRAGMA user_version=2",
        "UPDATE schema_migrations SET checksum='wrong'",
        "DROP INDEX lru_idx",
        "CREATE VIEW foreign_view AS SELECT 1",
        "CREATE TRIGGER foreign_trigger AFTER DELETE ON cache_entries BEGIN SELECT 1; END",
        "ALTER TABLE binding_state ADD COLUMN unexpected TEXT",
    ],
)
async def test_schema_corruption_rejected(
    sqlite_store: SQLiteStore, mutation: str
) -> None:
    with connection(sqlite_store._config.path) as db:
        db.execute(mutation)
    with pytest.raises(CacheStoreError):
        await sqlite_store.clear(namespace="default")
    with pytest.raises(CacheStoreError):
        await SQLiteStore.connect(
            sqlite_store._config.path, embedding_space=SPACE, default_ttl_seconds=None
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE cache_entries SET vector_blob=zeroblob(28)",
        "DELETE FROM cache_payloads",
        "UPDATE cache_payloads SET payload_blob=x'7b7d'",
        'UPDATE cache_payloads SET payload_blob=CAST(\'{"cache_key":"a","cache_key":"b"}\' AS BLOB)',
        "UPDATE binding_state SET last_revision_us=NULL",
        "UPDATE binding_state SET access_counter=0",
        "UPDATE cache_entries SET namespace='*'",
        "UPDATE cache_entries SET hit_count=-1",
        "UPDATE cache_entries SET revision_us=253402300800000000",
    ],
)
async def test_corrupt_data_errors_never_misses(
    sqlite_store: SQLiteStore, mutation: str
) -> None:
    await sqlite_store.put(entry("secret prompt", response="secret response"))
    with connection(sqlite_store._config.path) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(mutation)
    with pytest.raises(CacheStoreError) as caught:
        await sqlite_store.find_nearest((1, 0), namespace="default")
    formatted = "".join(traceback.format_exception(caught.value))
    assert "secret response" not in formatted
    assert str(sqlite_store._config.path) not in formatted
    assert caught.value.__context__ is None


@pytest.mark.parametrize("dimensions", [2, 384, 1536, 16000])
async def test_exact_full_matrix_float64_and_threshold_neighbors(
    tmp_path: Path, dimensions: int
) -> None:
    space = EmbeddingSpace(identity="numeric", dimensions=dimensions)
    path = tmp_path / "numeric.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=space, default_ttl_seconds=None, max_size=7
    )
    rng = np.random.default_rng(92)
    vectors = [
        normalized_vector(tuple(rng.normal(size=dimensions)), dimensions=dimensions)
        for _ in range(7)
    ]
    query = normalized_vector(tuple(rng.normal(size=dimensions)), dimensions=dimensions)
    async with await SQLiteStore.connect(
        path, embedding_space=space, default_ttl_seconds=None, max_size=7
    ) as store:
        for index, vector in enumerate(vectors):
            # Account for the same normalization performed by the store at write.
            await store.put(entry(str(index), vector=tuple(vector)))
        with connection(path) as db:
            rows = db.execute(
                "SELECT cache_key,vector_blob FROM cache_entries ORDER BY revision_us,cache_key"
            ).fetchall()
        matrix = np.asarray([decode_vector(blob, dimensions) for _, blob in rows])
        index, _ = nearest_index(query, cast(Sequence[Sequence[float]], matrix))
        match = await store.find_nearest(tuple(query), namespace="default")
        assert match is not None
        assert match.entry.cache_key == rows[index][0]
        actual_query = normalized_vector(tuple(query), dimensions=dimensions)
        assert (
            match.similarity_score
            == nearest_index(actual_query, cast(Sequence[Sequence[float]], matrix))[1]
        )
        assert all(
            blob[12:]
            == normalized_vector(tuple(vector), dimensions=dimensions)
            .astype("<f8")
            .tobytes()
            for (_, blob), vector in zip(rows, vectors, strict=True)
        )
        # Facade normalizes once more; use its actual candidate score for equality.
        embedder = FixedEmbedding(space, tuple(query))
        candidate = await store.find_nearest(tuple(actual_query), namespace="default")
        assert candidate is not None
        if candidate.similarity_score >= 0:
            for threshold, expected in (
                (candidate.similarity_score, True),
                (float(np.nextafter(candidate.similarity_score, 1.0)), False),
                (max(0.0, float(np.nextafter(candidate.similarity_score, 0.0))), True),
            ):
                async with AsyncSemanticCache(
                    embedder=embedder, store=store, similarity_threshold=threshold
                ) as cache:
                    assert (await cache.get("query") is not None) == expected


async def test_negative_ties_and_all_candidates_checked(
    sqlite_store: SQLiteStore,
) -> None:
    await sqlite_store.put(entry("old", vector=(-1, 0)))
    await sqlite_store.put(entry("new", vector=(-1, 0)))
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.entry.prompt == "old"
    assert match.similarity_score == -1
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET revision_us=(SELECT min(revision_us) FROM cache_entries)"
        )
        key = db.execute("SELECT min(cache_key) FROM cache_entries").fetchone()[0]
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.entry.cache_key == key
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET vector_blob=? WHERE cache_key<>?",
            (
                HEADER.pack(b"SMXV", 1, 1, 0, 2)
                + np.asarray([float("nan"), 0], dtype="<f8").tobytes(),
                key,
            ),
        )
    with pytest.raises(CacheStoreError):
        await sqlite_store.find_nearest((1, 0), namespace="default")


async def test_ttl_clock_boundary_fresh_confirmation_and_submicrosecond(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1700000000000000]
    calls = []

    def now() -> int:
        calls.append(clock[0])
        return clock[0]

    monkeypatch.setattr(database, "now_us", now)
    # Existing connection's UDF captures original function; register the controlled clock on its owner.
    await sqlite_store._worker.run(
        lambda job: job.connection.create_function("semantix_now_us", 0, now)
    )
    value = entry("ttl", created_at=datetime.max.replace(tzinfo=UTC))
    await sqlite_store.put(value, ttl_seconds=0.000002)
    candidate = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert candidate
    assert candidate.expires_at
    expiry = micros(candidate.expires_at)
    clock[0] = expiry - 1
    calls.clear()
    assert await sqlite_store.record_hit(
        value.cache_key,
        namespace="default",
        expected_created_at=candidate.entry.created_at,
    )
    assert calls == [expiry - 1]
    before = state(sqlite_store._config.path)
    clock[0] = expiry
    calls.clear()
    assert not await sqlite_store.record_hit(
        value.cache_key,
        namespace="default",
        expected_created_at=candidate.entry.created_at,
    )
    assert calls == [expiry]
    assert state(sqlite_store._config.path) == before
    assert await sqlite_store.find_nearest((1, 0), namespace="default") is None
    clock[0] = expiry - 1
    assert (
        await sqlite_store.find_nearest((1, 0), namespace="default") is not None
    )  # declared wall-clock rollback
    # Use another binding because the first consumed datetime.max.
    space = EmbeddingSpace(identity="submicro", dimensions=2)
    await SQLiteStore.initialize_schema(
        sqlite_store._config.path, embedding_space=space, default_ttl_seconds=None
    )
    async with await SQLiteStore.connect(
        sqlite_store._config.path, embedding_space=space, default_ttl_seconds=None
    ) as other:
        await other.put(entry("immediate"), ttl_seconds=1e-10)
        assert await other.find_nearest((1, 0), namespace="default") is None
        with connection(sqlite_store._config.path) as db:
            assert (
                db.execute(
                    "SELECT last_revision_us FROM binding_state WHERE identity=?",
                    (space.identity,),
                ).fetchone()[0]
                is not None
            )


async def test_revision_lru_and_ttl_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "durable.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    )
    value = entry("one", created_at=datetime(1900, 1, 1, tzinfo=UTC))
    async with await SQLiteStore.connect(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    ) as store:
        await store.put(value)
        await store.put(entry("two", namespace="other"))
        old = await store.find_nearest((1, 0), namespace="default")
        assert old
        assert await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
    async with await SQLiteStore.connect(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    ) as store:
        await store.put(entry("three", namespace="other"))
        with connection(path) as db:
            assert db.execute(
                "SELECT cache_key FROM cache_entries WHERE namespace=?", ("other",)
            ).fetchall() == [(entry("three", namespace="other").cache_key,)]
        assert await store.delete_entry(value.cache_key, namespace="default")
        await store.put(value)
        new = await store.find_nearest((1, 0), namespace="default")
        assert new
        assert new.entry.created_at > old.entry.created_at
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
        assert await store.clear(namespace="default") == 1
        await store.put(value)
        latest = await store.find_nearest((1, 0), namespace="default")
        assert latest
        assert latest.entry.created_at > new.entry.created_at


@pytest.mark.parametrize(
    ("column", "value"), [("last_revision_us", MAX_US), ("access_counter", MAX_INT)]
)
async def test_ledger_exhaustion_is_atomic(
    sqlite_store: SQLiteStore, column: str, value: int
) -> None:
    await sqlite_store.put(entry("before"))
    with connection(sqlite_store._config.path) as db:
        db.execute("UPDATE binding_state SET " + column + "=?", (value,))  # noqa: S608 -- parametrized fixed test columns
    before = state(sqlite_store._config.path)
    with pytest.raises(CacheStoreError):
        await sqlite_store.put(entry("after"))
    assert state(sqlite_store._config.path) == before


async def test_max_unicode_payload_and_deep_json(sqlite_store: SQLiteStore) -> None:
    value = entry("😀" * 2000, response="😀" * 100000)
    await sqlite_store.put(value)
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match
    assert match.entry.response == value.response
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_payloads SET payload_blob=?", (b"[" * 10000 + b"]" * 10000,)
        )
    with pytest.raises(CacheStoreError):
        await sqlite_store.find_nearest((1, 0), namespace="default")


def test_integer_timestamp_round_trips() -> None:
    for value in (
        datetime.min.replace(tzinfo=UTC),
        datetime(1900, 1, 1, tzinfo=UTC),
        datetime.max.replace(tzinfo=UTC),
    ):
        assert timestamp(micros(value)) == value


@pytest.mark.parametrize("hits", [MAX_INT])
async def test_live_hit_counter_exhaustion_and_expired_false(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, hits: int
) -> None:
    clock = [1700000000000000]
    monkeypatch.setattr(database, "now_us", lambda: clock[0])
    await sqlite_store._worker.run(
        lambda job: job.connection.create_function(
            "semantix_now_us", 0, lambda: clock[0]
        )
    )
    value = entry("hit exhaustion")
    await sqlite_store.put(value, ttl_seconds=1)
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    with connection(sqlite_store._config.path) as db:
        db.execute(
            "UPDATE cache_entries SET hit_count=?,last_accessed_at_us=?",
            (hits, clock[0]),
        )
    before = state(sqlite_store._config.path)
    with pytest.raises(CacheStoreError):
        await sqlite_store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
    assert state(sqlite_store._config.path) == before
    clock[0] += 1000000
    assert not await sqlite_store.record_hit(
        value.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    assert state(sqlite_store._config.path) == before


@pytest.mark.parametrize(
    ("header", "values"),
    [
        ((b"NOPE", 1, 1, 0, 2), (1.0, 0.0)),
        ((b"SMXV", 2, 1, 0, 2), (1.0, 0.0)),
        ((b"SMXV", 1, 2, 0, 2), (1.0, 0.0)),
        ((b"SMXV", 1, 1, 1, 2), (1.0, 0.0)),
        ((b"SMXV", 1, 1, 0, 3), (1.0, 0.0)),
        ((b"SMXV", 1, 1, 0, 2), (0.0, 0.0)),
        ((b"SMXV", 1, 1, 0, 2), (float("inf"), 0.0)),
    ],
)
def test_vector_codec_rejects_invalid_header_and_norm(
    header: tuple[bytes, int, int, int, int], values: tuple[float, float]
) -> None:
    with pytest.raises(ValueError, match="Invalid stored vector"):
        decode_vector(
            HEADER.pack(*header) + np.asarray(values, dtype="<f8").tobytes(), 2
        )


async def test_same_identity_different_dimensions_isolated(tmp_path: Path) -> None:
    path = tmp_path / "dimensions.db"
    spaces = [
        EmbeddingSpace(identity="same-id", dimensions=2),
        EmbeddingSpace(identity="same-id", dimensions=3),
    ]
    for space in spaces:
        await SQLiteStore.initialize_schema(path, embedding_space=space)
        async with await SQLiteStore.connect(path, embedding_space=space) as store:
            await store.put(
                entry(
                    "same key",
                    response=str(space.dimensions),
                    vector=(1.0,) + (0.0,) * (space.dimensions - 1),
                )
            )
    for space in spaces:
        async with await SQLiteStore.connect(path, embedding_space=space) as store:
            match = await store.find_nearest(
                (1.0,) + (0.0,) * (space.dimensions - 1), namespace="default"
            )
            assert match is not None
            assert match.entry.response == str(space.dimensions)
            assert await store.clear(namespace="default") == 1


async def test_owned_path_canonicalization_handles_relative_and_short_aliases(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "ordinary directory"
    nested.mkdir()
    path = nested / ".." / "canonical.db"
    await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    async with await SQLiteStore.connect(path, embedding_space=SPACE) as store:
        assert (
            store._config.path
            == await asyncio.to_thread(tmp_path.resolve) / "canonical.db"
        )
        await store.put(entry("canonical path"))

    if sys.platform == "win32":
        buffer = ctypes.create_unicode_buffer(32768)
        assert (
            ctypes.windll.kernel32.GetShortPathNameW(str(tmp_path), buffer, len(buffer))
            > 0
        )
        alias = Path(buffer.value) / "short.db"
        await SQLiteStore.initialize_schema(alias, embedding_space=SPACE)
        async with await SQLiteStore.connect(alias, embedding_space=SPACE) as store:
            assert (
                store._config.path
                == await asyncio.to_thread(tmp_path.resolve) / "short.db"
            )
    else:
        link = tmp_path / "linked-directory"
        link.symlink_to(nested, target_is_directory=True)
        with pytest.raises(CacheConfigurationError):
            await SQLiteStore.initialize_schema(
                link / "rejected.db", embedding_space=SPACE
            )
        assert not (nested / "rejected.db").exists()
