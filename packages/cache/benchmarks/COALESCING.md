# Cold-miss coalescing experiments (driver version 1)

`coalescing.py` wraps the frozen `runtime.trial` harness. It does not change the
existing `Case`, datasets, request classification, burst batches, warmup,
`perf_counter_ns` clock, closed-loop worker scheduler, quantiles, result validation
or store implementations. The synthetic generator is immutable and the same
callable object is reused; the treatment explicitly attests to that snapshot.

Modes:

- `control`: current production facade with the keyword omitted (default None).
- `treatment`: same facade with the fixed synthetic coalescing key supplied.
- `legacy`: an explicitly supplied archived base engine, loaded as a private module,
  to compare the current default hit path with the optimized pre-feature facade.
  The checkout files and current optimized stores are never replaced. Record the
  archived source revision and hash; do not call this an old store/kernel control.

Each mode uses the same lightweight forwarding wrapper. Run each ordinary timing
trial in a fresh process. Alternate control/treatment order over at least three
pairs; interleave the archived hit-path controls rather than collecting them on a
separate day. Record exact commands, all source hashes, environment, dataset digest
and discarded/failed trials. Keep raw outputs in an ignored directory.

From `packages/cache`, a memory trial can be run with:

~~~shell
python -m benchmarks.coalescing --case-json '{"store":"memory","workload":"burst","dimensions":384,"cache_size":500,"capacity":5000,"concurrency":128,"requests":256,"generation_delay":0.2}' --mode treatment --output ../../.cache/coalescing/treatment.json
~~~

Change only `--mode control` for the paired control. Database trials require
`SEMANTIX_BENCHMARK_DATABASE_URL` for an owned disposable database and the explicit
`--disposable-database` acknowledgement. Never put credentials in command arguments
or result files. BLAS settings, fixture preparation and excluded setup costs must
match the baseline; do not change global BLAS settings in production.

Run instrumented diagnostics separately with `diagnostics=true`, and allocation
trials with `allocations=true`. These results contain real generation/embedding
counts, post-warmup store search/write/confirmation counts, admitted leaders/joins,
overflows, follower fallback generations, leader/follower end-to-end latency,
follower gate-wait and recheck latency, and peak/final coalescer accounting.
Warmup is excluded from store counters. Failure paths are validated by correctness
and dedicated fault diagnostics, not hidden inside successful latency samples.

The gate-wait estimate subtracts that request's measured recheck from the combined
wait/recheck duration; it includes wrapper scheduling overhead. Diagnostic roles
and clocks add overhead. Use ordinary trials for latency/throughput conclusions
and instrumented trials for accounting/causes. RSS includes the interpreter,
fixtures, store, allocator and native buffers; charged key bytes are a conservative
per-record estimate, not a claim about total application memory.

For 256 requests at concurrency 8/32/128 the frozen burst batches contain 32/8/2
new prompts. Compare C128/200 ms against the optimized 256-generation-call control,
report both generation and embedding work, and retain slower cold-path results.
Coalescing may reduce provider work while increasing caller latency because every
follower must confirm its own stored hit. Do not present call/output-length proxies
as hosted dollar savings, or short P99 as a stable production budget.
