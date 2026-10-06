# Embedded coalescing evidence

Applications own general request/generation counters, provider and store timings,
histograms, tracing and logging. Use existing CacheResult/CacheHit decision evidence
and application wrappers for those concerns. Those models contain payloads: select
safe fields explicitly rather than exporting their entire serialization.

The cache offers one opt-in numeric snapshot because flight admission, follower
participation and gate waits cannot be reconstructed reliably outside the engine.
It installs no exporter, remote telemetry, callbacks, background task or queue.

```python
from semantix_cache import AsyncSemanticCache
from semantix_cache.observability import CoalescingSnapshot

cache = AsyncSemanticCache(
    embedder=embedder,
    store=store,
    collect_coalescing_metrics=True,
)
evidence: CoalescingSnapshot | None = cache.coalescing_snapshot()
```

Use application-owned embedder/store instances as in the
[package quick start](../packages/cache/README.md#use-your-own-embedding-and-generation).
The constructor flag is keyword-only, strictly bool and defaults to False.
Disabled collection allocates no statistics ledger and returns None. An enabled,
unused cache returns a zero-valued frozen slots dataclass. Import the model from
semantix_cache.observability; it is not added to the root export set.

## Fields and reconciliation

Counters accumulate over one cache instance's lifetime, without reset or a runtime
collection toggle. Gauges describe the current coalescer. Snapshot copies are
coherent under its existing guard; the immutable dataclass is built after that
mutex is released. No provider, store, exporter or user code runs under the guard.

| Field | Meaning |
| --- | --- |
| leaders_admitted | Eligible initial misses for which admission creates a new leader; a later race recheck may hit without generation. |
| followers_joined | Eligible initial misses admitted to an existing active flight. |
| admissions_declined | Eligible admissions refused by the record, participant or charged identity-byte bound; independent behavior continues. |
| follower_hits | Joined followers served without generation, successfully returning a confirmed cache hit. |
| follower_generated | Joined followers successfully returning provider_called=True after their own generation and any required write. |
| follower_errors | Joined followers ending with an exception other than cancellation or CacheTimeoutError. |
| follower_cancelled | Joined followers ending with CancelledError, including propagated leader cancellation. |
| follower_timeouts | Joined followers ending with CacheTimeoutError from their own deadline or the leader. A callback's raw TimeoutError counts as follower_errors. |
| follower_generations_started | Actual follower generator invocations, including attempts that later fail output validation, persistence or result construction. This is phase evidence, not another terminal outcome. |
| followers_pending | Joined followers that have not yet recorded a terminal outcome. |
| wait_count | Completed or aborted follower gate-wait intervals, including success, error, cancellation and timeout. |
| wait_seconds | Sum of monotonic gate-wait seconds, excluding post-gate store rechecks; no individual samples or percentiles are retained. |
| active_flights | Flights in the existing active map. |
| retained_flights | Charged flight records, including terminal records whose participants are still draining. |
| participants | Attached leaders and followers, including terminal participants before cleanup detaches them. |

```text
followers_joined = follower_hits + follower_generated + follower_errors
                 + follower_cancelled + follower_timeouts + followers_pending
```

Terminal accounting occurs once in existing request cleanup, together with detach.
Generation-start evidence can overlap a later error, cancellation or timeout.
Gauges can therefore be nonzero after a gate opens while followers recheck or
finish. A close attempted during active/draining work retains existing busy-close
behavior. After a successful close, the final snapshot remains readable; a new
cache instance starts a new lifetime.

Warm hits, missing coalescing keys, non-NORMAL policies and requests rejected before
admission do not increment admission counters. A declined request does not become
a follower. See [coalescing safety](../packages/cache/README.md#optional-cold-miss-coalescing)
for eligibility, bounds and application equivalence attestation.

**follower_hits means joined followers served without generation.** It is not a
causal count of generations/provider calls saved: another writer or replacement
may supply that hit. It does not measure tokens or dollar savings. A follower
whose confirmation is rejected can invoke its own generator. These observations
do not change persisted reuse, thresholds, normalization, TTL or retry behavior.

## Privacy, failures and integrations

There are exactly 15 fixed numeric fields and an 11-field slots ledger per enabled
instance. There are no user-controlled labels or maps, samples, payloads, prompts,
responses, namespaces, cache keys/hashes, vectors, identities, tasks, callables,
provider/model metadata or raw exceptions in the snapshot or ledger. Counter
values grow with lifetime activity; storage cardinality stays fixed. Existing
bounded flight records continue serving coalescing and are not exported.

If optional bookkeeping, its clock, its copy or snapshot construction fails, only
collection is discarded and subsequent snapshots return None. The original cache
result, error or cancellation propagates without retries. Raw provider/store
errors are not stringified or logged for metrics. None can mean disabled collection
or unavailable evidence after a bookkeeping failure. Absence is not a zero snapshot.

Prometheus: **DOCUMENTED THROUGH GENERIC SURFACE**. In an application-owned scrape,
map lifetime counters to counters, current/pending fields to gauges, and wait_count
plus wait_seconds to count/sum evidence. Do not manufacture histogram buckets or
percentiles from aggregates. Account for instance replacement/resets and avoid
counting the same lifetime value again on every scrape. Labels and scrape/exporter
lifecycle, if used, belong to the application; Semantix supplies none.

OpenTelemetry metrics: **DOCUMENTED THROUGH GENERIC SURFACE**. An application may
observe cumulative counters and current gauges, or compute monotonic deltas per
instance for its own instruments. Treat an unavailable snapshot as absent evidence.
Own aggregation temporality, replacement handling and exporters in the application.

OpenTelemetry tracing: **NOT NEEDED as a Semantix-owned adapter**. Wrap application
request, embedding, generation and storage boundaries for spans. The aggregate
snapshot has no task identity and cannot reconstruct individual flight traces.

Application logging/metrics: **DOCUMENTED THROUGH GENERIC SURFACE**. Explicitly
allowlist numeric snapshot fields and non-payload result flags. Nothing in Semantix
enables network telemetry or installs Prometheus/OpenTelemetry dependencies or extras.

## Performance and verification

Confirmed hits skip flight admission and metrics bookkeeping whether collection is
enabled or disabled. Opt-in cold followers pay for bounded numeric updates and two
monotonic clock reads; snapshot readers pay for coherent copying and construction.
No samples, worker, exporter or per-request metrics object is allocated.

Measure with the [existing runtime methodology](../packages/cache/benchmarks/README.md)
and the [observability driver](../packages/cache/benchmarks/observability.py).
Use complete archived accepted source for controls, fresh processes, identical
cases and at least three alternating pairs. Cover fixture and MemoryStore hits,
keys omitted/supplied, collection disabled/enabled, cold bursts and concurrent
snapshot readers. Retain all failures/outliers. Investigate P95 movement relative
to matched noise; reject repeatable median regressions above 3% isolated or 5%
MemoryStore hot latency/throughput. Results describe that host/workload, not a
universal production promise. No automatic performance CI threshold is installed.

From packages/cache, run focused checks and the full suite:

```text
uv run --no-sync --offline pytest tests/test_observability.py tests/test_coalescing.py
uv run --no-sync --offline pytest --cov=semantix_cache
```

Persistence tests need a disposable pgvector database. Runtime changes make reviewed
reuse-quality evidence stale until an explicitly authorized clean-source refresh;
this snapshot feature does not refresh corpus labels or public evidence automatically.
