# SQLite mutation metadata validation — Phase 06

GO for the focused metadata-validation optimization, subject to exact-head GitHub CI and human review. Do not merge automatically. The performance campaign remains open.

## Selected implementation and provenance

Baseline main is 04cfd7597857ff952472850cbbd7bf351e24317e (PR #239). The Phase 04 one-namespace immutable search snapshot is present; Phase 05 concurrent workers are absent. The original checkout remains 3f5ec8b9927e4218c6b3454884adf4a46e15a107. GPTCache remains read-only at a74ac654473f7bf4109118e8576945161616e17a. Prior archives, research branches, unmerged expiry work, adaptive work and PR #212 are preserved.

Every put/delete/namespace-clear previously discarded the full binding metadata-validation token as well as the vector snapshot. The next operation repeated an O(N) metadata scan. The selected change advances metadata validation only after an acknowledged native commit with unchanged connection-local PRAGMA data_version and an exact total_changes receipt. Put has three direct writes plus two changes per removed entry including its cascaded payload; delete and namespace-clear have two changes per removed entry. RETURNING cache_key counts are capacity-bounded. Any extra local DML, external commit, failure or interrupted receipt falls back to full validation.

The vector matrix still invalidates before native mutations. SQL, schema/header checks, revision ledger, exact winner confirmation, atomic hit confirmation, WAL/FULL durability, float64 scoring/ties, TTL, ownership, deadlines and lifecycle stay authoritative. No new index, worker, retained namespace, dependency or schema is introduced. Global clear_all is exactly the baseline method: its binding is empty, so retaining populated metadata offers no benefit.

## Entry condition and measured bottleneck

Separate instrumented public-operation runs cover N=100/1000/4000 x callers=1/4/16. At N=1000 / W=4, baseline 70/30 traffic rebuilt 20 times per 100 operations; instrumented P50 was 75.43 ms versus 44.51 ms for read-only. Mutation receipt reuse reduces repeated binding validation; it does not remove vector rebuilds or numerical work. These inclusive spans are nested and must not be added:

| N=1000 / W=4 70/30 mean ms/request | Baseline | Receipt candidate |
|---|---:|---:|
| Authority total | 4.443 | 0.299 |
| Full metadata SQL/fetch | 3.334 | 0.000 |
| Snapshot total | 5.563 | 5.494 |
| Vector decoding inside rebuild | 2.417 | 2.443 |
| Admission wait | 53.147 | 40.521 |
| SQL owner total | 16.657 | 12.376 |

At this point authority cost fell 4.443 to 0.299 ms/request; rebuild time stayed 5.56/5.49 ms/request. Worker time fell 16.66 to 12.38 ms/request and admission wait 53.15 to 40.52 ms/request. The gain comes from metadata validation and queue occupancy, rather than a new numerical or reader architecture.

## Alternatives and bounded selection

| Strategy | Assessment |
|---|---|
| A: full rebuild | Baseline; correct, but repeated metadata scans after native writes add material mixed-traffic cost. |
| B: incremental matrix updates | Not implemented. Copy-on-write requires another 49,152,000-byte matrix at N=4000, ordering/replacement/deletion bookkeeping and per-row expiry handling. The simpler receipt change already earns material end-to-end gains. No incremental-index speed claim is made. |
| C: namespace-local matrix retention | Not selected. It helps other-namespace REFRESH writes, but same-namespace replacements still rebuild; correct retention must account for old scope, global expiry purges and LRU victims. No multi-namespace cache was added. |
| D: version-qualified metadata reuse | Selected; exact native local-DML receipt and unchanged external epoch, with matrices retired as before. Delete/clear do not need revision-ledger movement. |
| E: SQL/index changes | Existing scope_idx, expiry_idx, lru_idx and payload primary-key indexes serve the measured queries. EXPLAIN plans show index searches; no schema/index change is justified. |

The timed prototype also applied receipts to clear_all. Its single lifecycle observation was 18.411 ms baseline versus 21.341 ms prototype; this alone did not establish a repeatable regression. The operation removes the whole binding, making the receipt unnecessary. The selected source restores it exactly to main. AST comparison proves that this is the only runtime difference from the full-matrix source; all measured public resolve/put/find/hit paths are identical. Two final-source rotated paired repetitions at each of N=1000/4000, W=16, 70/30 confirm the gain. The old prototype, source hashes and adverse observation remain preserved.

## Correct workload attribution and method

Use saved V2 text-embedding-3-small vectors: 1325 x 1536 float64 file; vectors SHA256 c45c65575d0cc2ddcf5be16cdcd2bb69dc2fc13218314ede4e570113f852ed26. The performance subset has 1000 independent vectors. The 4000-entry stress case adds compatible-answer aliases, not independent vectors; earliest original revision wins equal-score ties. Read keys stay immutable and disjoint from write keys. Every public NORMAL resolve hit must match the approved answer, frozen expected key and exact expected native revision, with zero generation. Every REFRESH resolve must invoke its local approved-answer generator once and acknowledge a write. Native SQL receipts preserve actual updated key/namespace/revision and independent SQL checks confirm final revisions, payload ownership and integrity.

No historical unsafe V2 mixed hits are counted. Threshold 0.9691803520567825 is frozen, with no held-out-label tuning. Capacity 5000, default TTL none, one SQL worker, 32-job admission, one OpenBLAS thread verified from the loaded DLL, identical closed seed copies, fresh processes, fixed operations and rotated variant/cell order. Primary measurements include facade embedding/validation, lookup, authoritative hit writes or generation/write, and scheduling. Provider/network latency is absent. CPU/host variation is recorded; no trials were dropped or adjusted.

The final matrix has 54 fresh processes,55,296 requests and three matched repetitions per size/caller/mix. Each phase has 256 operations; actual write counts are preserved because nominal percentages describe a repeating shuffled 100-operation schedule. Tail blockers require>=10% and >=2 ms adverse P95/P99 in >=2/3 pairs; CPU blockers require >=15% in >=2/3 pairs. A qualifying gain requires >=10% paired throughput or P50 improvement, repeatable over at least two sizes. All 36 cells pass those gates.

Hardware: AMD Ryzen 9 5900HX, 8 physical / 16 logical CPUs, Windows x64. Timed runtime: CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4, SQLite 3.53.1. See the [manifest](manifest.json) for raw runtime/data/harness hashes, every pair, resources and exact commands.

## Final matrix

Numbers are marginal medians across three repetitions; percentage effect summaries use medians of within-pair ratios, which can differ from ratios of marginal medians. Latency is milliseconds; CPU is process milliseconds/request. Read-only code paths are unchanged and their fluctuations are controls.

| Entries | Callers | Mix read/write | P50 B→C | P95 B→C | P99 B→C | Requests/s B→C | CPU ms/request B→C | Paired RPS change |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | 1 | readonly | 5.86→5.87 | 6.46→6.67 | 8.10→8.10 | 167.11→166.60 | 5.37→5.31 | -0.7% |
| 100 | 1 | 90/10 | 5.77→5.95 | 8.95→8.61 | 9.60→9.40 | 164.29→160.80 | 5.49→5.55 | -1.9% |
| 100 | 1 | 70/30 | 5.77→5.77 | 9.10→8.34 | 10.93→9.36 | 158.34→165.96 | 5.43→5.68 | +4.1% |
| 100 | 1 | 30/70 | 5.36→4.83 | 8.94→8.47 | 9.54→8.94 | 164.81→177.39 | 5.43→4.94 | +8.2% |
| 100 | 4 | readonly | 23.59→23.74 | 26.85→25.65 | 28.78→28.87 | 167.46→166.69 | 5.43→5.37 | -0.9% |
| 100 | 4 | 90/10 | 24.08→24.32 | 30.29→29.60 | 32.84→33.34 | 164.72→163.78 | 5.37→5.37 | +1.0% |
| 100 | 4 | 70/30 | 27.08→26.85 | 34.61→32.91 | 41.13→38.76 | 156.57→160.19 | 5.68→5.80 | +2.1% |
| 100 | 4 | 30/70 | 20.42→18.92 | 38.10→35.49 | 40.02→37.18 | 166.39→177.97 | 5.49→5.07 | +6.7% |
| 100 | 16 | readonly | 94.10→93.46 | 99.48→100.97 | 101.48→101.79 | 168.06→169.61 | 5.49→5.13 | +0.0% |
| 100 | 16 | 90/10 | 99.71→101.19 | 114.56→113.62 | 117.46→116.66 | 164.12→162.57 | 5.43→5.62 | -1.2% |
| 100 | 16 | 70/30 | 115.14→112.92 | 126.40→122.35 | 127.57→125.25 | 157.85→161.34 | 5.55→5.98 | +2.0% |
| 100 | 16 | 30/70 | 80.40→73.95 | 157.03→141.07 | 166.56→146.08 | 162.12→176.20 | 5.74→5.37 | +7.5% |
| 1000 | 1 | readonly | 9.89→9.89 | 10.91→10.84 | 13.11→12.84 | 99.64→99.54 | 9.28→9.64 | -0.3% |
| 1000 | 1 | 90/10 | 9.88→9.87 | 47.86→33.98 | 48.79→34.76 | 74.65→83.64 | 12.63→11.17 | +11.3% |
| 1000 | 1 | 70/30 | 10.04→9.85 | 48.82→34.36 | 51.25→35.13 | 55.48→73.33 | 17.33→12.94 | +32.2% |
| 1000 | 1 | 30/70 | 18.85→5.16 | 48.93→34.88 | 50.29→35.82 | 46.73→85.91 | 20.69→10.74 | +84.0% |
| 1000 | 4 | readonly | 39.14→39.26 | 44.03→43.45 | 47.35→46.18 | 100.50→100.26 | 9.34→9.28 | -0.2% |
| 1000 | 4 | 90/10 | 44.48→40.68 | 89.54→67.23 | 116.16→87.26 | 74.59→83.61 | 13.18→11.17 | +13.6% |
| 1000 | 4 | 70/30 | 74.79→60.79 | 129.11→89.82 | 139.86→95.89 | 55.54→73.58 | 17.21→12.88 | +31.9% |
| 1000 | 4 | 30/70 | 75.36→44.80 | 159.80→90.26 | 175.43→107.97 | 46.64→86.86 | 20.75→11.11 | +85.0% |
| 1000 | 16 | readonly | 156.86→158.73 | 173.10→170.39 | 178.30→178.56 | 100.43→99.26 | 9.34→9.40 | +0.0% |
| 1000 | 16 | 90/10 | 215.21→196.00 | 326.93→262.77 | 357.23→289.69 | 74.50→83.78 | 12.63→11.29 | +12.1% |
| 1000 | 16 | 70/30 | 326.03→247.01 | 392.10→282.51 | 402.81→295.10 | 54.85→73.32 | 17.40→12.88 | +33.2% |
| 1000 | 16 | 30/70 | 286.20→156.34 | 558.90→307.94 | 601.85→326.30 | 46.57→86.47 | 20.94→10.93 | +85.8% |
| 4000 | 1 | readonly | 22.22→22.46 | 24.57→24.17 | 26.07→24.82 | 43.89→43.88 | 21.97→21.79 | +0.1% |
| 4000 | 1 | 90/10 | 22.28→22.25 | 175.35→118.14 | 179.30→122.31 | 27.32→32.46 | 35.52→29.85 | +19.1% |
| 4000 | 1 | 70/30 | 22.61→22.28 | 178.24→120.00 | 186.62→122.50 | 18.04→26.31 | 54.63→37.29 | +45.8% |
| 4000 | 1 | 30/70 | 62.10→6.47 | 178.13→121.05 | 182.42→123.54 | 14.27→32.51 | 69.46→29.85 | +127.8% |
| 4000 | 4 | readonly | 88.34→89.06 | 95.97→95.24 | 125.28→126.56 | 44.34→44.26 | 21.73→22.16 | -0.3% |
| 4000 | 4 | 90/10 | 95.18→89.82 | 287.51→190.27 | 399.79→273.40 | 27.19→32.99 | 36.13→29.66 | +21.7% |
| 4000 | 4 | 70/30 | 229.36→170.61 | 437.93→280.51 | 460.75→289.45 | 18.04→26.58 | 54.69→36.87 | +47.5% |
| 4000 | 4 | 30/70 | 251.42→129.32 | 557.58→276.12 | 610.75→325.62 | 13.90→33.13 | 71.11→29.48 | +135.3% |
| 4000 | 16 | readonly | 360.27→362.48 | 403.75→393.23 | 408.77→402.45 | 44.18→43.63 | 21.73→21.97 | -0.8% |
| 4000 | 16 | 90/10 | 581.72→464.24 | 1024.20→750.76 | 1136.68→841.40 | 26.58→32.62 | 37.17→29.79 | +22.6% |
| 4000 | 16 | 70/30 | 1008.85→685.72 | 1193.75→823.13 | 1227.69→837.66 | 17.90→26.26 | 54.75→37.48 | +46.7% |
| 4000 | 16 | 30/70 | 945.90→418.74 | 1895.68→867.30 | 2024.14→926.32 | 14.06→32.78 | 70.07→29.79 | +133.1% |

For 70/30, paired throughput improves 32–33% at 1000 and 46–48% at 4000. At four/16 callers, paired P50 falls 18.6/24.3% and 25.7/31.6% respectively. CPU/request falls 24–33%. At 100 entries,70/30 throughput gains are only 2–4%; small-cache90/10 RPS changes include−1.9% at one caller and−1.2% at16, while70/30 CPU changes include +5.6%/+3.2%. These small effects are disclosed and are not a substantial small-cache optimization claim.

One final adverse tail observation remains inconclusive: N=100 / W=1, 30/70, repetition 1 P99 rose 9.470 to 13.464 ms (+42.2%,+3.994ms). It did not repeat in the other two pairs; paired-median P99 for that cell improves 6.4%. No assertion, sample or diagnostic was suppressed.

## Longer verification, cold behavior and resources

Two matched 30 s read-only N=4000 / W=4 pairs checked the screening P99 concern (+13.5%/+23.3% in short screening pairs). Longer-pair P99 changed −3.3%/+1.8%; the full final matrix has no repeated tail regression in that cell. The screening observations remain in the manifest. Two matched 120 s N=4000 / W=16,70/30 pairs reproduce the intended gain:

| Repetition | P50 ms B→C | P95 ms B→C | P99 ms B→C | Requests/s B→C | CPU ms/request B→C |
|---:|---:|---:|---:|---:|---:|
| 0 | 1031.55→692.00 | 1237.62→826.07 | 1281.22→854.57 | 17.54→26.23 | 56.17→37.39 |
| 1 | 1030.90→693.08 | 1234.31→831.53 | 1320.58→858.16 | 17.55→26.22 | 56.05→37.34 |

Endurance peak RSS is 171.3–171.7MiB across both variants; WAL stays 4,148,872 bytes. Faster runs perform more committed writes and rebuilds in the same duration, so absolute rebuild counts are reported rather than mistaken for extra per-request cost. No new retained matrix or connection exists. Primary matrix/peak/warm-RSS values are preserved for every pair in the manifest; warm RSS depends on whether the last operation discarded the matrix.

Controlled 20-rebuild N=1000 loops end at 74.67/74.68 MiB warm RSS versus 73.07/73.25 MiB initially; close returns 52.55/53.32 MiB. All 20 retired snapshots are reclaimed per variant, no worker/task/admission leaks remain, and restart reconstructs from SQL. External replacement/hit commits conservatively rebuild and take 52.1/52.2 ms baseline versus 53.6/55.3 ms candidate in these single diagnostic observations. Restart first-hit costs 51.7/53.3 ms; no cold or external-commit speedup is claimed.

The original timing harness retained an unused snapshot reference only after measured phases, contaminating its after-close RSS field. That field and original executable are preserved; it is not used to conclude memory release. No timing, CPU, peak or warm-RSS sample was removed. The replay harness corrects only this teardown reference and verifies reclamation with a weak reference; final-source confirmation uses it. Separate controlled resource tests independently verify release.


Single-request cold startup and the next warm request, pooled over the nine fresh-process runs per variant/size (the later concurrency level is not active during this probe):

| Entries | Cold first ms B→C | Next single warm ms B→C |
|---:|---:|---:|
| 100 | 12.62→12.36 | 6.08→6.48 |
| 1000 | 52.17→52.89 | 10.61→10.42 |
| 4000 | 179.13→178.78 | 23.42→23.22 |

The primary 70/30 phase resource medians are:

| Entries | Callers | Peak RSS MiB B→C | End-phase RSS MiB B→C |
|---:|---:|---:|---:|
| 100 | 1 | 64.68→64.02 | 59.62→59.85 |
| 100 | 4 | 64.98→64.89 | 59.78→59.74 |
| 100 | 16 | 64.55→64.96 | 59.80→60.32 |
| 1000 | 1 | 93.50→93.24 | 81.78→81.26 |
| 1000 | 4 | 94.00→93.66 | 82.27→81.90 |
| 1000 | 16 | 95.16→94.98 | 81.46→83.04 |
| 4000 | 1 | 165.93→165.82 | 118.96→118.22 |
| 4000 | 4 | 166.35→165.45 | 119.20→118.57 |
| 4000 | 16 | 167.67→167.08 | 120.80→119.18 |

Across the full matrix, maximum database/WAL bytes per size and variant are retained in the manifest. There is no schema or durability change, and no unbounded disk growth was observed.

## Correctness and compatibility evidence

Selected source: 242 SQLite tests pass on Python 3.11.15 and 3.14.6; Ruff/format, configured strict mypy and Pyright pass; 47 server parity tests pass (10 unrelated marker deselections, 23 warnings); rebuilt wheel/sdist, twine/archive checks and isolated installed consumer pass. Earlier full offline package run passed 1623 tests (including 243 SQLite cases before removing the clear_all-only receipt test), with 80 skips and 401 service-marker deselections. The 1380 non-SQLite cases are unchanged. SQLite certification unit suite: 50 pass.

Existing Phase 04 regression gates remain selected in CI, including independent-process commits at capture fences, unchanged-ledger delete/clear, fresh candidate/hit confirmation, expired/rollback-clock snapshots, corruption/schema checks, cancellation/rollback, commit-ack uncertainty, crash/restart, ownership, close/reopen and memory release. New tests cover native receipt retention, unexpected local and external commits after native commit, cascade/eviction counts, post-commit cancellation and rolled-back writes; uncertain outcomes are checked with independent SQLite reads.

The configured 90% combined package coverage gate is unchanged. Local offline tests do not certify live MySQL/PostgreSQL/Redis coverage or older Linux SQLite libraries. Exact-head GitHub CI must pass those actual required gates before merge. Code-only graph refreshed outside the product; SQL graph parsing is unavailable without an optional parser, so SQL source/tests/EXPLAIN are authoritative.

## Reproduction, changed files and limitations

All raw CSV/JSON/SQL write-identity receipts, closed seed copies, original/final source variants, commands, stdout/stderr, plans, source maps and verification receipts are retained outside both products in the task-owned workspace Semantix_SQLite_P6_20261026_04cfd759. Exact replay needs that workspace, saved V2 data and runtime; these are not publicly bundled. Public source/summary hashes support auditing but do not imply independent replication. Benchmark CSVs remain untracked; the root ignore rule is scoped to packages/cache/benchmarks/sqlite_upkeep/*.csv. No historical evidence was edited or deleted.

The product diff contains the SQLite database module, focused tests in the existing snapshot suite, this report, its manifest and the narrow ignore rule. It adds no configuration/export/fixture/public API changes. No MemoryStore, shared numerical, Phase 05 worker, provider, dependency-pin, migration, other-store, adaptive or PR #212 changes.

These are short single-host replacement-heavy embedded workloads, not multi-hour stability, arbitrary new-prompt semantic-miss traffic, server HTTP throughput or live-model latency. Namespace switching and external commits still rebuild; full vector decoding/reconstruction, numerical row norms, serialized SQL admission and durable hit writes remain bottlenecks.

Phase 07 recommendations: use these bounded mutation receipts and resource controls when evaluating the authorized next subsystem, with explicit correct-answer accounting. Phase 08 should run a fresh fair competitor comparison with matching correctness/durability and source revisions. Neither phase was started; no GPTCache victory is claimed. Human review remains required.
