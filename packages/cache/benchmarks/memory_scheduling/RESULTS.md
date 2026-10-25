# MemoryStore Phase 02: reader scheduling (2026-10-25)

**Decision: publish a draft for review; release remains blocked.** Immediate executor submission overlaps numerical work with an earlier request's facade validation. The store keeps one numerical worker. A private caller future ensures cleanup precedes delivery and cancellation leaves numerical ownership intact.

At 4000 entries, five paired repetitions show useful concurrent gains, together with repeatable single-reader costs. Exact-hit P50 is 6.8% slower and semantic P50 8.4% slower at one reader, both adverse in all five pairs. These exceed the limits defined before final timing. No threshold, dtype, validation, TTL, LRU, revision, snapshot or BLAS production policy changed.

## Corrected final source

Timings below are medians of five independent process measurements per source; each arrow is main â†’ candidate. Percentages are medians of paired ratios, which need not equal the ratio of column medians.

| Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 change |
|---:|---|---:|---:|---:|---:|---:|
| 1 | exact | 5.276 â†’ 5.635 | 6.134 â†’ 6.237 | 6.479 â†’ 6.514 | 186.166 â†’ 177.664 | +6.8% |
| 1 | semantic | 5.223 â†’ 5.711 | 6.109 â†’ 6.203 | 6.410 â†’ 6.372 | 187.108 â†’ 178.420 | +8.4% |
| 4 | exact | 22.131 â†’ 17.577 | 23.521 â†’ 20.034 | 25.377 â†’ 21.230 | 181.206 â†’ 223.743 | -21.1% |
| 4 | semantic | 23.070 â†’ 18.298 | 25.350 â†’ 23.941 | 26.975 â†’ 29.431 | 172.417 â†’ 211.038 | -17.8% |
| 16 | exact | 90.853 â†’ 69.873 | 107.091 â†’ 76.286 | 111.621 â†’ 78.439 | 172.638 â†’ 225.614 | -24.7% |
| 16 | semantic | 88.717 â†’ 69.674 | 99.832 â†’ 73.840 | 101.021 â†’ 74.154 | 176.899 â†’ 226.036 | -21.3% |

The complete four-path data, including CPU, RSS, queue times, adverse-pair counts and every adverse median, is in [final-summary.csv](final-summary.csv). Source/input/harness hashes and limits are in [manifest.json](manifest.json).

| Readers | Path | CPU s /200 requests | End RSS MiB | Peak RSS MiB | Admission wait P50 ms |
|---:|---|---:|---:|---:|---:|
| 1 | exact | 1.078 â†’ 1.141 | 355.715 â†’ 355.801 | 401.781 â†’ 401.859 | 0.003 â†’ 0.003 |
| 1 | semantic | 1.062 â†’ 1.141 | 359.004 â†’ 359.043 | 401.781 â†’ 401.859 | 0.003 â†’ 0.003 |
| 4 | exact | 1.109 â†’ 1.250 | 355.965 â†’ 356.059 | 401.793 â†’ 401.980 | 12.765 â†’ 8.987 |
| 4 | semantic | 1.156 â†’ 1.297 | 359.363 â†’ 359.332 | 401.793 â†’ 401.980 | 13.263 â†’ 9.465 |
| 16 | exact | 1.172 â†’ 1.141 | 356.344 â†’ 356.574 | 401.809 â†’ 401.996 | 81.376 â†’ 61.560 |
| 16 | semantic | 1.141 â†’ 1.188 | 359.730 â†’ 359.965 | 401.809 â†’ 401.996 | 79.353 â†’ 61.256 |

CPU/request increased by up to 12.2% in the final matrix; it did not cross the 15% criterion. RSS stayed approximately flat. Selected tails also worsened: four-reader semantic P99 26.975â†’29.431ms, and sixteen-reader mixed P99 104.526â†’115.492ms. Their paired effects were +5.1% and +4.5%; neither met the repeated-material-tail criterion. These observations remain in the summaries and raw traces.

## Provenance and bounded experiments

Baseline is merged PR #233 on main `4fdc884e876ef370b5c16c19a705138575a6226f`. Final MemoryStore SHA256 is `3c733129296bf0afa89a11192dd7a9d35539d1aef1020b1ce627e396a9b13e73`.

The earlier direct-submission prototype ran the full 100/1000/4000 Ã—1/2/4/8/16 matrix, five pairs per cell (150 processes, 120000 requests). It had a different completion transport. [prototype-summary.csv](prototype-summary.csv) is explicitly evidence for that earlier source, not the final source. Its 1000-entry concurrent exact P50 gain was about5%; the historical GPTCache gap remains open.

Admission caps1/2/4 and a four-request batching alternative were implemented and tested. Caps2/4 repeatedly worsened mixed tails; batching also worsened mixed tails. They remain research artifacts. Cap8 was not justified. No numerical work was moved onto the event loop.

Python 3.14 barrier tests exposed a fast-completion cleanup race and abandoned-error diagnostics in the prototype. The corrected private caller future fixes both. Final-source verification was bounded to 4000 entries and 1/4/16 readers, five pairs each (30 processes, 24000 requests), and used the same lightweight admission observation on both sources. The other size/reader cells were not rerun for the corrected transport. No prototype timing was relabeled.

A single longer confirmation on the earlier source used 2000 semantic requests after the same 200 exact+200 read-only misses. It confirmed a+5.8% single-reader semantic P50 cost in all five pairs. That evidence is retained separately.

## Workload and interpretation

- Saved V2 `text-embedding-3-small` vectors, 1536D, float64; zero new model calls. The 4000-entry case repeats1000 real vectors four times under compatible-answer aliases. It tests matrix size and scheduling, not4000 independently embedded prompts.
- Native facade exact hit, read-only populated-scope miss, 13 fixed development semantic queries at threshold0.8, and qualified70/30 mixed resolution. Strict admission threshold0.9691803520567825, capacity5000, TTL disabled, seed20261024, 10 exact warmups, 200 measured requests per path per process. Mixed generation has zero delay and includes native admission; unique miss namespaces qualify answer correctness and differ from unsafe unpartitioned V2 mixing.
- Windows x64, CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4, 8 physical/16 logical CPUs, normal priority and full affinity. BLAS/OMP/MKL env caps were1 before NumPy import; the loaded OpenBLAS getter read back1. No CPU affinity, power policy, GC or production BLAS setting was changed.
- Source imports, expected answers, jobs, namespaces and generation counts were verified. Final24000 requests had0 wrong results, 0 errors, 0 pending tasks and no unexpected stderr. This is fixture correctness, not a general semantic-safety guarantee.
- Warm-snapshot preparation and state-lock wait were small. Matched scheduling-to-worker profiles on the earlier prototype at 1000 entries showed about2.9ms before worker entry on main versus1.7â€“1.8ms with immediate submission. The facade still spends about2.4â€“2.6ms in embedding/candidate validation. Numerical wall time includes GIL resumption; Windows per-thread CPU ticks were too coarse to isolate these short kernels. Final queue measurements above validate reduced admission delay; phase CPU is the usable CPU comparison.
- Tails at200 requests/process are estimates, host CPU varied, and Linux/eager-task-factory performance was not measured. No fresh GPTCache head-to-head was run. Saved1000-entry GPTCache P50 targets6.001/10.759ms at4/16 readers remain historical references; this phase does not claim the competitive gate passed.

## Correctness and CI boundary

77 focused MemoryStore checks passed on each of Python 3.11/3.14, including forced already-completed futures, cold readers, queued/running cancellation, worker failure, error consumption, live revision/expiry rechecks, contexts and shutdown. Strict mypy/Pyright and configured lint/format passed. The offline package suite passed 1564 tests (80 skipped, 401 deselected);24 server parity tests passed.

A fixed resource proof passed at 5000 entries with 32 cancelled callers, 128 replacement writes and 100 new-store cycles: one active numerical worker, peak480.3MiB, threads returned to their starting count after executor shutdown. Numerical/scoring/snapshot ASTs exactly match main.

Local full-service validation was unavailable: three Redis cases require a disposable Redis URL, and local total coverage was67.19%, below the required90%. The import-boundary test was updated narrowly for the two standard-library imports. GitHub CI must run its actual owned MySQL/PostgreSQL/Redis gates and combined90% package coverage; local skips are not passing integration evidence. See the PR's checks for the current CI result.

## Reproduction

The maintainer-owned Phase 02 workspace identified in the manifest preserves the frozen source variants, baseline archive, original150-process matrix, corrected30-process matrix, per-request CSVs and replay harnesses. It requires the unchanged saved V2 run; no replacement vectors should be generated. `corrected_final_matrix.py` records the fixed final plan and `corrected_bench.py` contains the matching native workload and queue observation. To replay into new receipt IDs from that workspace, use `corrected_bench.launch(variant, 4000, readers, rep, queue_only=True, phases=['exact', 'miss', 'semantic', 'mixed'])` for baseline/candidate in alternating order, readers 1/4/16, and five repetitions. The candidate file must match the manifest hash; never overwrite the preserved manifests.

No further timing experiments are part of this phase. Resolve or explicitly accept the quantified single-reader cost before changing this draft's release status. Human review and actual CI remain required; nothing was merged.
