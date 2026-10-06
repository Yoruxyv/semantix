# CacheStore conformance for adapter authors

Use this development kit when implementing a structural `CacheStore` against
Semantix's existing 0.1.x contract. It tests observable semantics through public
`semantix_cache` types and `AsyncSemanticCache`; no subclass, registry, server or
private engine helper is required. Passing means compatibility with the scenarios
actually exercised, not certification of a production deployment.

## Location and contract version

The kit lives in
[`packages/cache/examples/store_conformance/`](../packages/cache/examples/store_conformance/__init__.py).
It is source-based pytest development tooling, outside the installed runtime
namespace. Consume it from a pinned Semantix checkout, with `packages/cache` on
your Python path. Existing source-archive rules include examples; the wheel
contains only the runtime package. No package metadata, optional extra or runtime
dependency was added for the kit. pytest/pytest-asyncio remain development tools.

`CONTRACT_VERSION = "0.1.x"` tracks the public CacheStore contract, rather than an
independent kit release series. Record the exact installed runtime version, kit
Git revision, backend/server version and test output when publishing adapter
evidence. For an uncommitted kit, record the diff too; a SHA alone is incomplete.

Run the following commands from `packages/cache`:

```text
git rev-parse HEAD
uv run --no-sync --offline python -c "from importlib.metadata import version; from examples.store_conformance import CONTRACT_VERSION; print(version('semantix-cache'), CONTRACT_VERSION)"
```

Future intentional store obligations must be documented with the corresponding
Semantix compatibility change and updated common cases. Re-run the kit and backend
tests before claiming compatibility with that release. A previously passing run
does not recertify an adapter for a changed runtime/contract.

## Minimal consumer

The [standalone consumer](../packages/cache/examples/test_custom_store_conformance.py)
runs the existing independent
[`CompanyCacheStore`](../packages/cache/examples/custom_store.py).
That small dictionary adapter uses public types and stdlib arithmetic; it neither
subclasses nor wraps a built-in store. It is deliberately process-local and
non-durable. Reusing it avoids introducing a second demonstration of the same
storage rules.

A third-party test needs one inherited class and a factory fixture:

```python
from collections.abc import AsyncIterator

import pytest

from examples.store_conformance import SPACE, StoreCase, StoreConformance, StoreFactory
from semantix_cache import EmbeddingSpace

# Import your adapter and your backend-owned fixture helpers here.

class TestMyStore(StoreConformance):
    @pytest.fixture
    async def store_factory(self) -> AsyncIterator[StoreFactory]:
        stores = []

        async def factory(
            capacity: int = 32, ttl: float | None = None, *, space: EmbeddingSpace = SPACE
        ) -> StoreCase:
            store = await make_test_store(space, capacity, ttl)
            stores.append(store)
            return StoreCase(store=store, expire=expire_finite_test_entries)

        try:
            yield factory
        finally:
            for store in stores:
                await store.aclose()
            await remove_owned_test_backend()
```

`make_test_store`, `expire_finite_test_entries` and `remove_owned_test_backend`
are adapter-specific placeholders, not Semantix APIs. Use the runnable consumer
for a complete factory with deterministic expiry and cleanup.

Every call creates a fresh binding with the requested space, capacity and default
TTL. When a backend shares tables, different spaces in the same test must use
those shared tables: isolated databases would conceal missing space predicates.
The fixture owns initialization, credentials, pools, stores and teardown, even if
a test fails. Use disposable resources only. The suite closes stores in lifecycle
cases but never closes a borrowed database pool.

`expire()` advances authoritative expiry of finite test entries without sleeping.
Do not change revisions, response content or immortal entries. Memory/example
fixtures control monotonic time; PostgreSQL sets finite expiry to its own
`clock_timestamp()`, exercising the inclusive expired boundary. The UTC retention
metadata check assumes a local test database with a clock aligned to the test host;
backend clock/durability guarantees require separate evidence.

Two optional probes describe real differences, not different core semantics:

- `read_hit_metadata(key, namespace)` returns `HitMetadata(count, last_accessed)`
  or `None` for an absent row. Supply it for backends with persisted counters.
  MemoryStore and the example maintain LRU order, not public hit counters.
- `block_lookup()` is an async context manager yielding an `asyncio.Event`. It
  blocks a real nonempty lookup, signals admission, then releases/drains work on
  exit, including cancellation and timeout. Supply it for asynchronous backends.
  The nonblocking dictionary example has no pending I/O boundary.

Missing probes produce explicit skips. Do not call a backend fully verified for
those capabilities on the basis of a skipped test. Counters and worker controls
are fixture-owned observations, never new CacheStore methods. The built-in
[factories](../packages/cache/tests/test_store_conformance.py) use known disposable
tables and worker/pool instrumentation; the reusable kit imports no private
Semantix module.

## Run it

From `packages/cache`, using the repository's existing development environment:

```text
uv sync --locked --extra dev
uv run --no-sync --offline pytest --no-cov examples/test_custom_store_conformance.py -o asyncio_mode=auto
uv run --no-sync --offline pytest --no-cov tests/test_store_conformance.py
uv run --no-sync --offline pytest --cov=semantix_cache
```

For an external project, add the pinned checkout's `packages/cache` directory to
its test Python path, install its compatible development tools, and run
`python -m pytest your_store_tests.py -o asyncio_mode=auto`. Consumers do not
import `packages/cache/tests`, its fixtures or built-in store internals.

The PostgreSQL tests require `PGVECTOR_TEST_DATABASE_URL` set through the
environment to a **fresh disposable** pgvector database. Fixtures install the
extension and remove only UUID-named schemas they own. No DSN means PostgreSQL
skips; that does not verify PostgreSQL compatibility. The existing quality
workflow runs all three consumers, full coverage and static checks with its pinned
pgvector service on Python 3.11-3.14. No new database job or Redis dependency exists.

## Evidence boundaries

| Obligation | Common evidence | Backend-specific evidence retained |
| --- | --- | --- |
| Namespace / space / dimensions | Lookup, confirmation, write, scoped delete/clear; equal dimensions with distinct identities and equal identity with distinct dimensions | PostgreSQL shared-table filtering and prefix isolation |
| Vectors | Finite, nonzero, exact dimensions, invalid-write rejection and safe error text | Float64 snapshots versus PostgreSQL float32 projection/corrupt rows |
| Thresholds | Actual nearest score; inclusive equality, below/above, valid 0/1 endpoints through the facade | Numeric oracle and near-threshold precision |
| Winner / ties | Exact/similar winner, equal-score oldest revision, hits do not reorder winners | Equal-revision key fallback requires kernel/persisted-row fixtures: public writes assign distinct monotonic revisions |
| TTL | Default/capped/shorter/immortal retention; non-sliding confirmation; expired candidate rejected | Exact monotonic boundary/wall-clock jumps; PostgreSQL authoritative clock |
| Replacement / revision | Content/vector/expiry reset; detached snapshots; monotonic revision survives delete/clear/reinsert; stale confirmation rejected | SQL rollback and durable binding revision |
| Confirmation / hit metadata | Current revision succeeds, stale/expired/foreign fails; counters only change on confirmed hits, reset on replacement when exposed | Persisted counters and access ordering are PostgreSQL-specific |
| Capacity / LRU | Capacity across namespaces; writes and successful confirmations update order; searches/rejected confirmations do not | Snapshot invalidation, bounded SQL cleanup and transactions |
| Ownership / close | Facade borrows store; close twice; all public operations reject closed state | Borrowed versus owned pools, failed/cancelled close termination |
| Cancellation / deadline | Real blocked lookup cancellation propagates, busy close rejected, facade deadline remains a typed error when probe supplied | Memory retained worker slot; PostgreSQL pool/transaction deadlines |
| Concurrent mutations | Distinct/same-key writes and confirmations; lookup with write/delete/clear, confirm/delete; event-ordered stale candidate after write/delete/clear/expiry | Worker snapshot races and SQL transactional rollback/locking |
| Failure / redaction | Invalid-input failures stay errors and omit synthetic payloads | Real backend/DSN failures, traceback redaction, migration/connect/close failure cleanup |

The generic suite uses events for ordered candidate/confirmation races. Unordered
concurrent operations allow legitimate winners and check authoritative final state;
they do not assume a scheduler order. Memory's retained numerical worker and
PostgreSQL's blocked acquisition are tested by backend probes, not simulated stores.
No cancellation is converted into a miss. Backend failures and vendor timeouts
still need fault-injection tests; the generic kit cannot create those portably.

Keep [MemoryStore tests](../packages/cache/tests/test_memory.py),
[snapshot tests](../packages/cache/tests/test_memory_snapshots.py),
[PgVectorStore tests](../packages/cache/tests/test_pgvector.py) and
[projection tests](../packages/cache/tests/test_pgvector_projection.py).
They supplement the one shared contract rather than redefine it. A new adapter
must add equivalent evidence for its I/O, persistence, failures and cleanup.

## What a passing run does not prove

Passing does not prove production durability, correct vendor/server configuration,
all vendor versions, HA/cluster failover, replica consistency, distributed consensus,
network partitions, disaster recovery, backup correctness, arbitrary retry-policy
safety, cloud-provider behavior, authorization, tenant authentication, production
security hardening, or performance/scalability. Test those claims against the
adapter's actual backend and topology. Namespace isolation is not authentication.
No RedisStore or QdrantStore is implemented or verified by this kit.
