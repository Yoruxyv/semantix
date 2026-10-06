# Embedded runtime measurements

This harness measures the async `semantix-cache` runtime directly, without the
FastAPI server, HTTP client, web app, hosted providers or billable API calls. It
collects baselines and diagnostic experiments; it does not certify performance or
change the package's implementation. Use the [cache contract](../README.md#contract)
and [storage guide](../../../docs/embedded-storage.md) for supported semantics.

## Run

From `packages/cache`, use the project's existing locked development environment:

```text
uv sync --locked --extra dev
uv run --no-sync python -m benchmarks.run_matrix --group matrix --store memory --blas-threads 1 --output-dir ../../.cache/embedded-benchmarks/memory
uv run --no-sync python -m benchmarks.run_matrix --group numerics --blas-threads 1 --output-dir ../../.cache/embedded-benchmarks/numerics
uv run --no-sync python -m benchmarks.analyze ../../.cache/embedded-benchmarks --output ../../.cache/embedded-benchmarks/summary.json
```

For PostgreSQL, set `SEMANTIX_BENCHMARK_DATABASE_URL` **only to an explicitly disposable
database**. Supply the existing `[pgvector]` extra (included in `[dev]`). Start a
pinned pgvector database using operator-owned tooling. Pass `--disposable-database`:

```text
uv run --no-sync python -m benchmarks.run_matrix --group matrix --store pgvector --blas-threads 1 --disposable-database --output-dir ../../.cache/embedded-benchmarks/postgres
```

The harness installs the vector extension in that disposable database, initializes
a new `semantix_bench_<UUID>` schema, and drops only that schema on teardown. It never
uses the server's `semantix` schema, changes deployed indexes or calls Docker cleanup.
Pool construction, DDL, prefill and warmup are outside measurement. The pool is
preopened, but one facade warmup does not prepare statements on every connection;
first waves can include per-holder preparation. Record database
container/image digest, CPU/memory limits and host/VM topology alongside the results.
Do not put a DSN/password in an argument, result JSON, log, checked-in file or report.

Each child process runs one trial. Repeat comparable trials sequentially to avoid
competing benchmark processes. `--resume` skips successful existing trial files;
failed/incomplete evidence is preserved and requires a new output directory.
`--blas-threads 1` sets OpenBLAS/OMP/MKL thread environment variables **before** the
child imports NumPy. `--blas-threads default` removes those overrides; it is a
separate experiment, not a runtime configuration change. Do not mix its numbers
with the controlled single-thread baseline. No affinity or GC tuning is applied.

## Workloads and evidence

[`workloads.json`](workloads.json) defines bounded groups. The main matrix uses
384 dimensions (the current server mock/default Hugging Face dimension), 1536
as a common larger provider configuration, 500 initial candidates, concurrency
1/8/32/64/128 and 256 requests per independent trial, repeated three times.
`scale` includes 3072 dimensions and 32/5000 candidates. The embedded package does
not prescribe a universal embedding dimension. These are synthetic unit-vector
workloads, not provider-quality or natural-language hit-rate benchmarks.

The seeded NumPy corpus is built and tuple-materialized outside measurement.
Its seed, dimension, digest and NumPy version identify it. Responses identify each
prompt; unexpected hits, incorrect response reuse and resource leaks fail a trial.
Cache policy, namespace and threshold handling still run through the real facade.
Ordinary trials retain the 0.92 inclusive threshold and 3600-second non-sliding TTL.

| Group/path | Interpretation |
| --- | --- |
| `matrix` hits | Real resolve hits including embedding, search, validation and atomic hit confirmation |
| `matrix` mixed90/mixed50 | READ_ONLY, controlled seeded/unseeded requests; misses generate but do not grow or evict seeded candidates |
| `matrix` cold | NORMAL unique misses starting with the stated candidate size; each successful miss writes and increases candidate count up to capacity |
| `matrix` burst | Concurrent batches of one cold prompt, 20ms synthetic async generation delay; reuse of earlier writes and duplicate generation are observed, never forced/coalesced |
| `burst-latency` | Additional zero/200ms synthetic generation-delay sweeps at concurrency 8/32/128; observes stampede sensitivity without hosted-provider calls |
| `components` | Public get, direct store search/write, empty-namespace facade, deterministic embedding/generation and growing NORMAL 90/10 mix |
| `fixture` | Fixed validated hit/confirmation test double: engine overhead without real search/persistence; not a replacement store or end-to-end performance claim |
| `policies` | READ_ONLY, REFRESH, BYPASS and PRIVATE without changing their behavior |
| `pool` | Pool sizes 1/8/16 at concurrency 32; long-lived borrowed pools, no connection per request |
| `postgresql-components` | Captured reference SQL, distance-only and vector text-conversion controls with verbose plans, timed on one held connection; omits facade/pool/reset/confirmation |
| `pool-diagnostics` | Separate acquisition/active-connection/SQL logging across those pool sizes, without cProfile or tracemalloc; instrumented, not baseline latency |
| `diagnostics` | Separately instrumented cProfile/tracemalloc, queue/lock acquisition, event-loop lag, driver SQL counts/acquire duration and EXPLAIN ANALYZE/BUFFERS |
| `worker-profiles` | Separate first-three real numerical-worker profiles; no simultaneous main-thread cProfile (Python monitoring resources can conflict) |
| `cleanup` | Generation cancellation with no partial writes; real search/queue cancellation and shielded-worker/pool drain |
| `saturation` | Hold all pool slots: bounded store timeout, cancelled waiter, then successful connection reuse |
| `failures` | Expected embedding/generation exceptions, no partial writes, unavailable reserved loopback endpoint and no surviving tasks |
| `stability` | 120 seconds of rotating bounded-corpus refresh/lookups, 0.5-second TTL, 500-entry limit and sampled RSS/tasks/latency windows |
| `numerics` | Current tuple/matrix/norm kernels, ndarray conversion, dtype promotion, scalar/vectorized and normalization experiments |
| `blas-comparison` | Smaller controlled-versus-default BLAS experiment using the same cases with separate output directories |

Latency starts immediately before an admitted worker's operation and includes awaits,
semaphore/pool queueing and required semantic work. Closed-loop workers request the
next operation after completing one; this is not an open-loop arrival-rate model and
must not be advertised as supporting a number of users. Dispatch and response checks
contribute to elapsed throughput. Pure immediate async mocks may finish without yielding;
they establish local callable overhead, not external concurrency or provider latency.
Burst throughput sums batch durations; no setup or reset is included between batches.

Quantiles use linear interpolation of `perf_counter_ns` samples. Analysis reports the
median of independent-trial quantiles/rates and the rate range/CV, **not pooled P99**.
With fewer than 1000 samples, P99 is explicitly descriptive; repeat variation and
longer runs must precede a regression budget. Numerical iteration counts are grouped
separately. Analysis rejects changes in runtime source, relevant measurement code,
corpus or environment between comparable trials; edits to analysis/reporting code
do not alter the measurements. Keep outliers/failures and record host
background load/power state. There are no universal latency or throughput promises.

Diagnostic latency is instrumented and cannot replace the uninstrumented baseline.
cProfile on the event-loop thread does not profile numerical worker threads; separate
profiles of the first three real numerical workers and synchronous numerical
experiments expose that work. Acquisition duration includes setup
and scheduling, not exclusively queue wait. Driver query logs include pool-reset batches and first-use type-introspection
queries in the measured asyncpg version. They count logged calls/batches, not wire
packets or exclusively application SQL. EXPLAIN uses the captured real search statement and synthetic parameters,
after the measurement. Do not sum cumulative profile times or overlapping task spans.

RSS includes interpreter/native allocations and fixture data; post-close RSS can retain
allocator/BLAS caches and the still-live dataset. Python/NumPy-tracked tracemalloc peaks
exclude some native buffers and are measured separately from latency. Numerical
experiments inspect shape, dtype, array memory sharing, buffer sizes and single-call
allocation peaks. Prebuilt/cached-normalization kernels omit validation/TTL/revision/
tie ordering and are hypotheses, not retained optimizations. Float32 threshold probes
near 0.92 explicitly demonstrate why small score differences require semantic review.

Stability bookkeeping is bounded: only the latest batch's raw samples/quantiles and
at most 120 sampled windows are retained, with cumulative operation/provider counters.
Thus stability's top-level quantiles are **last-batch**, not whole-run quantiles. Read
its window series for drift. A two-minute pass can expose early growth but is not
proof of indefinite stability or a complete release certification.

## Review boundaries

[`results.schema.json`](results.schema.json) describes trial evidence.
Source files, tests, workloads, schema, analysis tools and this methodology may be
committed after review. Raw JSON, profiles, logs, credentials and checkpoint reports
belong under the already ignored `.cache/` tree; runners refuse nonignored outputs.
No new production/dev dependencies, API changes, ANN, Redis, provider redesign or
performance CI threshold are required for baseline collection.

Run the harness checks and unchanged runtime correctness suite before comparisons:

```text
uv run --no-sync pytest tests/test_benchmark_harness.py
uv run --no-sync mypy benchmarks tests/test_benchmark_harness.py
uv run --no-sync ruff check --config ../../ruff.toml benchmarks tests/test_benchmark_harness.py
uv run --no-sync pytest --cov=semantix_cache
```

Supply `PGVECTOR_TEST_DATABASE_URL` pointing at the same disposable database to run
existing persistence/conformance tests; they validate isolation, revisions, TTL,
thresholds, capacity, atomic writes, ownership, cancellation and failure cleanup.
After collecting baselines, report measured bottlenecks, numerical/allocation risks
and optimization proposals for maintainer review before changing the runtime.

## Reuse quality

See [Reuse quality evidence](reuse_quality/README.md) for the independently labelled,
secret-free quality harness and reviewed static dashboard receipt. Quality and
runtime performance answer different questions; their scores are not combined.

The top-level workloads.json remains a runtime/performance input; it is unrelated
to the maintained reuse-quality corpus under reuse_quality/data.

## Coalescing collection overhead

[`observability.py`](observability.py) runs one trial through the same runtime
fixtures, request timing, warmup and cleanup checks. `--collection baseline` omits
the new constructor argument; disabled/enabled pass False/True explicitly. Use a
complete archived semantix_cache package on PYTHONPATH for baseline processes,
not only an old engine imported with modified internal dependencies. The evidence
records the actually loaded runtime file hashes and source path.

From packages/cache (PowerShell example, accepted revision selected explicitly):

```powershell
$baseRevision = "<accepted-source-SHA>"
New-Item -ItemType Directory -Force .cache/observability | Out-Null
$archivePath = Join-Path (Get-Location) ".cache/observability/base.zip"
git -C ../.. archive --format=zip --output=$archivePath $baseRevision packages/cache/src
Expand-Archive -LiteralPath .cache/observability/base.zip -DestinationPath .cache/observability/base
$caseJson = '{"store":"fixture","workload":"hits","dimensions":384,"cache_size":1,"requests":10000,"concurrency":1}'
$env:PYTHONPATH = (Resolve-Path .cache/observability/base/packages/cache/src).Path
uv run --no-sync --offline python -B -m benchmarks.observability --case-json $caseJson --collection baseline --output .cache/observability/control.json
Remove-Item Env:PYTHONPATH
uv run --no-sync --offline python -B -m benchmarks.observability --case-json $caseJson --collection enabled --output .cache/observability/treatment.json
```

Run at least three pairs in alternating order with unique output names. Repeat with
collection disabled, with/without `--key`, and with MemoryStore (500 seeded entries).
Use memory/burst, an empty initial store, concurrency 32 and a fixed synthetic
provider delay for cold followers. `--snapshots` adds one application reader thread
at a 1 ms wait interval only during measurement; it is joined before resource checks.
Baseline readers perform the same scheduling without an observation API; disabled
readers receive None; enabled readers copy full snapshots. This optional reader is
benchmark tooling, not a runtime telemetry worker. It records read counts; no
individual snapshot samples are retained. Output is restricted to ignored paths;
failed runs are retained and exit nonzero. Keep controls/treatments' configurations,
dataset hashes, source hashes, raw latencies and failures together. Apply the review
gates in the [coalescing evidence guide](../../../docs/embedded-observability.md#performance-and-verification)
without discarding noisy or failing runs.
