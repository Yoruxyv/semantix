# MemoryStore Phase 02: reader scheduling

**Decision: retain PR #234 as draft. Neither follow-up prototype qualifies for adoption.** The production candidate remains the source measured in the original five-pair comparison; no follow-up runtime change was committed. It reduces concurrent-reader queueing, with an unresolved single-reader trade-off. Do not merge this PR.

## Main versus the PR implementation

Baseline: merged PR #233, main `4fdc884e876ef370b5c16c19a705138575a6226f`. Runtime implementation: PR commit `2bc156df975d8e0685e1c887967e80e0a6e66bc9`; MemoryStore SHA256 `3c733129296bf0afa89a11192dd7a9d35539d1aef1020b1ce627e396a9b13e73`.

The implementation submits numerical work immediately to the existing executor, preserving request context. One numerical worker remains admitted at a time. A private caller future forwards completion after worker ownership and admission are released. Caller cancellation does not cancel the worker, and an already-finished worker cannot return before cleanup. No public defaults, numerical arithmetic, snapshot policy, threshold, namespace, TTL, revision or LRU behavior changed.

The following is the preserved **original five-pair, final-source matrix**: 4,000 entries; 1/4/16 readers; four native workloads; 30 fresh processes; 24,000 requests. Every pair uses identical jobs, labels, namespaces, seeds, queue observation and BLAS limits. There were zero wrong results, errors, pending tasks or unexpected stderr messages. Values are medians of process measurements, main → PR. Percentages are medians of paired effects, which can differ from ratios of column medians.

| Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | exact | 5.276 → 5.635 | 6.134 → 6.237 | 6.479 → 6.514 | 186.166 → 177.664 | +6.8% |
| 1 | miss | 5.000 → 5.206 | 5.731 → 5.757 | 6.047 → 5.993 | 196.784 → 192.168 | +3.7% |
| 1 | mixed | 4.994 → 5.209 | 5.891 → 6.010 | 6.271 → 6.239 | 197.739 → 190.840 | +2.4% |
| 1 | semantic | 5.223 → 5.711 | 6.109 → 6.203 | 6.410 → 6.372 | 187.108 → 178.420 | +8.4% |
| 4 | exact | 22.131 → 17.577 | 23.521 → 20.034 | 25.377 → 21.230 | 181.206 → 223.743 | -21.1% |
| 4 | miss | 21.483 → 17.213 | 24.548 → 20.610 | 25.579 → 24.075 | 183.791 → 226.734 | -17.1% |
| 4 | mixed | 22.041 → 20.842 | 30.252 → 26.697 | 34.581 → 28.248 | 176.106 → 189.720 | -7.2% |
| 4 | semantic | 23.070 → 18.298 | 25.350 → 23.941 | 26.975 → 29.431 | 172.417 → 211.038 | -17.8% |
| 16 | exact | 90.853 → 69.873 | 107.091 → 76.286 | 111.621 → 78.439 | 172.638 → 225.614 | -24.7% |
| 16 | miss | 84.459 → 66.007 | 98.658 → 74.384 | 102.043 → 75.034 | 184.246 → 234.049 | -20.2% |
| 16 | mixed | 87.166 → 82.724 | 96.798 → 105.452 | 104.526 → 115.492 | 178.643 → 186.598 | -6.7% |
| 16 | semantic | 88.717 → 69.674 | 99.832 → 73.840 | 101.021 → 74.154 | 176.899 → 226.036 | -21.3% |

Exact-hit concurrent P50 improves 21.1% / 24.7% at 4/16 readers; paired throughput improves 25.1% / 32.2%. Admission P50 falls 12.765→8.987 ms and 81.376→61.560 ms. This addresses scheduling and queueing, beyond PR #233's normalization change.

Single-reader exact/semantic P50 costs of 6.8% / 8.4% exceed the predefined gate, adverse in all five pairs. Four-reader semantic P99 and sixteen-reader mixed P99 also worsen; paired effects are +5.1% / +4.5%. They do not meet the repeated material tail criterion and remain disclosed.

| Readers | Path | CPU s / 200 requests | End RSS MiB | Peak RSS MiB | Admission P50 ms |
|---:|---|---:|---:|---:|---:|
| 1 | exact | 1.078 → 1.141 | 355.715 → 355.801 | 401.781 → 401.859 | 0.003 → 0.003 |
| 1 | miss | 1.000 → 1.047 | 358.734 → 358.773 | 401.781 → 401.859 | 0.003 → 0.003 |
| 1 | mixed | 1.016 → 1.047 | 359.797 → 359.738 | 401.781 → 401.859 | 0.002 → 0.003 |
| 1 | semantic | 1.062 → 1.141 | 359.004 → 359.043 | 401.781 → 401.859 | 0.003 → 0.003 |
| 4 | exact | 1.109 → 1.250 | 355.965 → 356.059 | 401.793 → 401.980 | 12.765 → 8.987 |
| 4 | miss | 1.047 → 1.203 | 359.004 → 359.137 | 401.793 → 401.980 | 12.445 → 8.927 |
| 4 | mixed | 1.156 → 1.234 | 360.207 → 360.086 | 401.793 → 401.980 | 13.390 → 12.006 |
| 4 | semantic | 1.156 → 1.297 | 359.363 → 359.332 | 401.793 → 401.980 | 13.263 → 9.465 |
| 16 | exact | 1.172 → 1.141 | 356.344 → 356.574 | 401.809 → 401.996 | 81.376 → 61.560 |
| 16 | miss | 1.078 → 1.125 | 359.406 → 359.699 | 401.809 → 401.996 | 75.707 → 58.282 |
| 16 | mixed | 1.109 → 1.188 | 360.980 → 361.145 | 401.809 → 401.996 | 79.025 → 74.506 |
| 16 | semantic | 1.141 → 1.188 | 359.730 → 359.965 | 401.809 → 401.996 | 79.353 → 61.256 |

CPU/request increased by up to 12.2%, below the 15% criterion. RSS stayed approximately flat. These are phase process CPU measurements: Windows thread-CPU ticks were too coarse to isolate short numerical kernels.

## Bounded follow-up on the single-reader cost

The follow-up plan was written before timing. It allowed exactly two prototypes and a three-pair, one-reader scout at 4,000 entries using the unchanged four-path harness. Promotion required at least 3% and 0.1 ms paired P50 improvement versus the published implementation on **both exact and semantic hits**, with at least two of three pairs improving and no obvious material tail harm. A conditional five-pair 1/4/16 comparison was permitted for one qualifying candidate. Neither qualified, so that conditional experiment was not run. No further campaign was started.

Both prototypes retain the same completion future, cleanup callback, cancellation isolation and one-worker admission:

- **Yield:** yield one loop turn before submission when the existing lifecycle active count is one. The active count is only a scheduling hint; it does not bypass ownership or validation.
- **Deferred task:** use a `to_thread` task when that count is one, retaining direct executor submission under contention.

Both passed all 77 existing MemoryStore tests on Python 3.11 and 3.14 with verified source imports. The 12 fresh scout processes completed 9,600 requests with zero wrong results, errors, pending tasks or unexpected stderr. The table compares the unchanged published implementation → each prototype; each row has three paired repetitions.

| Prototype | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 | Adverse P50 pairs |
|---|---|---:|---:|---:|---:|---:|---:|
| Yield | exact | 6.070 → 6.426 | 6.755 → 8.810 | 7.459 → 10.607 | 165.075 → 144.725 | +5.9% | 3/3 |
| Yield | miss | 5.675 → 5.773 | 6.324 → 7.225 | 6.888 → 9.072 | 175.059 → 167.540 | +5.3% | 3/3 |
| Yield | mixed | 6.019 → 5.956 | 6.736 → 6.717 | 6.965 → 7.318 | 170.195 → 171.680 | -2.2% | 1/3 |
| Yield | semantic | 6.124 → 6.161 | 7.289 → 7.224 | 8.151 → 8.202 | 161.655 → 159.675 | -1.5% | 1/3 |
| Deferred task | exact | 6.070 → 5.854 | 6.755 → 6.624 | 7.459 → 7.088 | 165.075 → 169.945 | +3.6% | 2/3 |
| Deferred task | miss | 5.675 → 5.520 | 6.324 → 6.347 | 6.888 → 8.245 | 175.059 → 175.853 | -1.8% | 1/3 |
| Deferred task | mixed | 6.019 → 5.826 | 6.736 → 7.140 | 6.965 → 8.166 | 170.195 → 170.212 | -4.3% | 1/3 |
| Deferred task | semantic | 6.124 → 5.912 | 7.289 → 6.843 | 8.151 → 8.545 | 161.655 → 167.305 | -5.5% | 1/3 |

The yield prototype fails exact P50 and worsens exact P95/P99 in all three pairs (+36.1% / +57.2% paired), as well as miss tails (+14.2% / +31.7%, all three adverse). The deferred-task prototype improves semantic P50 by 5.5% but worsens exact P50 by 3.6%, with two adverse pairs. Its exact P50 pair effects are −6.24%, +5.21%, +3.56%; a lower unpaired column median is not a reproducible paired improvement. Deferred-task mixed P95/P99 also worsen by 13.2% / 12.8% in two of three pairs, and semantic P99 by 11.2% in two pairs. These three-pair tail observations are not relabeled as a five-pair release-gate verdict.

Host CPU busy ranged 7.5%–33.5% across scout phases; peak child RSS was 402.9 MiB. CPU, RSS, queue measurements, per-pair effects and adverse observations remain in the external assessment and raw traces. Processes were run sequentially in rotated source order; no measurements were excluded for host load.

The unchanged published implementation versus main in this scout had paired exact/semantic P50 effects of −1.5% / −3.7%. It **did not reproduce** the earlier +6.8% / +8.4% cost. This adds uncertainty about stability across measurement conditions, not a code fix: three new pairs neither erase the preserved five-pair evidence nor qualify an unmeasured production change. The draft remains blocked until the trade-off is resolved or explicitly accepted with adequate evidence.

## What the diagnostic traces establish

A separate two-pair, single-reader diagnostic used spans around the same native exact/semantic paths. It was not used for acceptance timing. Spans include instrumentation overhead and may overlap; they are not an additive latency breakdown. For the published implementation, all instrumented future creation measured roughly 4.6–4.8 microseconds per request, context copying about 1 microsecond, partial construction about 2.8 microseconds, executor submission about 32 microseconds, and the completion callback about 9 microseconds. Comparable main callback time was about 7 microseconds. Submission-to-worker-entry measured about 64 microseconds versus main's 82 microseconds.

These component observations do not explain a 350–445 microsecond original P50 cost by themselves. Removing completion handling is unjustified. Numerical wall time includes GIL reacquisition and scheduling; the diagnostics cannot isolate a causal GIL penalty. No definitive single cause was established. At this size, unchanged expiry scans account for about 1.0–1.15 ms in aggregate, and facade embedding/candidate validation about 2.5–2.6 ms. Those remain work, alongside serialized numerical admission; this task does not adopt the preserved P1 expiry candidate.

At 1,000 entries under concurrent readers, earlier matched profiles showed scheduling-to-worker-entry around 2.9 ms on main versus 1.7–1.8 ms with immediate submission, with state-lock wait and warm snapshot preparation much smaller. That supports the concurrent scheduling attribution. It does not make the single-reader cause certain.

## Limits fixed before the original final timing

- Material tails: median paired P95/P99 increase >10% **and** >0.5 ms, with at least 4/5 adverse pairs.
- Single-reader P50: >5% **and** >0.2 ms, with at least 4/5 adverse pairs.
- Repeated CPU/request increase >15%; peak RSS increase >max(20%, 64 MiB); any correctness, lifecycle or resource violation blocks release.
- Concurrent benefit: at least 10% lower P50 and 10% higher throughput on warm exact/semantic hits at both 4 and 16 readers, with at least 4/5 pairs improving.

The original single-reader gate remains unresolved; no threshold or criterion was relaxed after inspecting labels or timings.

## Workloads, environment and rejected alternatives

Saved V2 `text-embedding-3-small` vectors are 1,536D float64. The 4,000-entry stress case repeats 1,000 real vectors four times under explicit compatible-answer aliases; it is not 4,000 independently embedded strings. No new model calls were made.

The four native paths are exact hit, read-only populated-scope miss, 13 frozen development semantic queries at threshold 0.8, and qualified 70/30 mixed resolution. Strict threshold is 0.9691803520567825; capacity 5,000; TTL disabled for timing; seed 20261024; 10 exact warmups; 200 measured requests per path per process. Mixed misses use unique namespaces, zero-delay generation and native admission. This differs from unsafe unpartitioned ID-heavy V2 mixing. Zero wrong fixture results is not a general semantic-safety guarantee.

Windows x64, CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4; 8 physical/16 logical CPUs, normal priority, full affinity. OMP/OPENBLAS/MKL limits are one before NumPy import; the loaded OpenBLAS getter read back one. No affinity, power policy, GC or production BLAS setting changed. P99 estimates use 200 observations per process. Linux/eager-task-factory performance was not measured.

The earlier direct-submission prototype ran 100/1,000/4,000 entries × 1/2/4/8/16 readers, five pairs (150 processes, 120,000 requests). It had a different completion transport; those timings do not validate the corrected transport over the full matrix. Its 1,000-entry concurrent exact P50 gain was about 5%. One longer earlier-source confirmation used 2,000 semantic requests after the same 200 exact/200 miss history and confirmed a 5.8% single-reader cost in all five pairs. Those source-specific records remain preserved.

Admission caps 1/2/4 and a four-request batching alternative were implemented. Caps 2/4 and batching repeatedly worsened mixed tails and were rejected. Cap 8 was not justified; numerical work was not moved onto the event loop. The two new follow-up prototypes are also preserved outside the repository rather than adopted without evidence.

No fresh GPTCache head-to-head was run. Saved 1,000-entry GPTCache P50 targets of 6.001/10.759 ms at 4/16 readers remain historical, qualified references. This phase does not claim the competitive gate passed; the campaign remains open.

## Correctness and CI

The current implementation preserves all 77 MemoryStore checks on Python 3.11/3.14, including float64 bit oracles, deterministic ties, cold readers, waiting/running cancellation, abandoned worker errors, already-finished success/error/cancellation, live revision and expiry confirmation, namespaces, context and shutdown. The original offline package suite passed 1,564 tests (80 skipped, 401 deselected); server parity passed 24 tests. Configured Ruff/format, strict mypy and pinned Pyright passed, as did reuse-quality validation, examples, wheel/sdist build and archive checks. Numerical/scoring/snapshot ASTs exactly match merged main.

The resource proof used 5,000 entries, 32 cancelled callers, 128 replacement writes and 100 new-store cycles: one active numerical worker, 480.3 MiB peak, threads returned to their starting count after executor shutdown.

Local full-service coverage was 67.19%, below the required 90%; local skips were not passing integration evidence. Actual [GitHub Quality run 40159585505](https://github.com/Yoruxyv/semantix/actions/runs/40159585505) on runtime commit `2bc156d` completed embedded Python 3.11–3.14, MySQL 3.11–3.14, PostgreSQL/Redis and other compatibility checks successfully. Python 3.14's embedded job reports **1,794 passed, 4 skipped, 247 deselected and 94.75% combined coverage**. Its additional owned-service certification steps passed. The run still failed the separate frontend image scan and aggregate quality gate. Later documentation-only commits require their own CI result; this receipt is explicitly tied to `2bc156d`.

The same frontend failure is present on [main after PR #233](https://github.com/Yoruxyv/semantix/actions/runs/40152041542/job/121067600032): Grype reports critical `brotli-libs` CVE-2026-111497, installed 1.2.0-r1, fixed 1.2.1-r0. This is an observed CI finding, not an embedded-cache failure. Frontend/dependency changes are outside the user's latest scope; no suppression, gate weakening or unrelated dependency change was added.

## Artifacts and reproduction

Only this narrative and [the JSON manifest](manifest.json) are tracked. The narrowly scoped root ignore rule is `/packages/cache/benchmarks/memory_scheduling/*.csv`. `final-summary.csv` and `prototype-summary.csv` were removed from Git tracking with `git rm --cached`; their on-disk bytes and preserved external evidence remain unchanged. Their hashes remain in the manifest as **untracked local** artifacts, without broken download links.

The maintainer-owned `Semantix_Memory_P2_20261025_b3836049` workspace preserves raw per-request CSVs, fresh-process JSONs, source variants, plans, logs, rejected prototypes and harnesses. It requires the unchanged saved V2 vectors. This PR alone is not independently reproducible without access to that external evidence. No historical raw results were overwritten.

Original corrected-source replay uses `corrected_bench.launch(variant, 4000, readers, rep, queue_only=True, phases=['exact','miss','semantic','mixed'])`, baseline/candidate in alternating order, readers 1/4/16 and five repetitions. The candidate must match the manifest's source hash; write new receipt IDs and never overwrite preserved manifests. The follow-up plan, source hashes, 12 IDs and diagnostic traces are recorded separately as `pr234-followup-plan.json`, `pr234-scout-manifest.json`, `pr234-scout-assessment.json`, and `pr234-diagnostic-summary.json`.

Stop after this bounded Phase 02 decision. No merge, SQLite work, adaptive-threshold work, PR #212 change, package publication or external AI-provider call is part of this change.
