# MemoryStore: selected combined implementation and shipping evidence

**Selection: ship the conservative expiry deadline and immediate scheduling together.** The bounded four-implementation comparison found no repeatable material small-cache tail regression. Keep the existing implementation and all regression tests; no size-dependent scheduling shortcut, extra executor or expiry index is justified. Code and performance requirements pass. Final merge readiness requires green checks for the exact PR head; the PR description records that head and run. This report does not authorize an automatic merge.

The selected runtime SHA256 is `38df02ddecc985f2bddae568f0ea2acbf52cea33a1ae72a10c2ac6b358d65201`. Main `5044c050b7f7a5ce57fa86158071b2fddac9e013` has the same cache package as the measured PR #233 normalization baseline `4fdc884e876ef370b5c16c19a705138575a6226f`, MemoryStore SHA256 `c6c13c8ba3d2e394f0a8fa5f83e1065533abaa4ae9c296fb6e3872abfb5cf4a7`. A normal merge synchronized current main without rewriting PR history. The cache runtime did not change during synchronization.

## Actual shipped behavior

Numerical work is submitted immediately to the existing executor with the caller's context. One numerical worker remains admitted. A private completion future wakes the caller after ownership and admission are released, including already-finished success/error/cancellation. Cancelling a caller leaves started work owned until it drains; abandoned exceptions are consumed. Numerical scoring stays off the event loop.

One conservative monotonic expiry bound avoids global scans until some deadline is due. A due scan removes every expired entry, increments its counter and rebuilds the bound. Writes lower it when needed; removal/replacement may leave an early bound and cause an extra scan, never postpone expiry. Clear-all and close reset it. No heap/index, dependency, threshold, public API, numerical arithmetic or snapshot policy changes are introduced. Float64/ties, namespaces, revision confirmation, LRU and lifecycle contracts remain protected.

Earlier diagnostics measured about 1.0–1.15 ms of aggregate expiry bookkeeping per request at 4,000 entries. Future/context/callback component spans were microseconds and did not explain the earlier single-reader penalty. Immediate submission reduced measured concurrent dispatch delay; the deadline bound removes redundant GIL-held metadata work. Instrumented spans overlap and are not additive latency estimates. Serialized admission and facade embedding/candidate validation remain bottlenecks.

## Bounded small-cache isolation

The plan was frozen before measurement. All four source variants use the same package, vectors, jobs, namespaces, thresholds and storage policy:

- **M:** current main after PR #233; original scheduling and full expiry scans.
- **E:** deadline bound only, with main's scheduling/ownership methods unchanged.
- **S:** immediate scheduling only, without the bound; preserved source `3c733129...`.
- **C:** selected combined PR runtime `38df02dd...`.

AST checks verify that M/E and S/C have matching scheduling methods, E/C and M/S have matching expiry methods, and all four share identical numerical/query/snapshot/item ASTs. E is an isolated comparison variant, not a shipped alternative or new public option.

Exactly 100 entries/four readers; exact and semantic native paths; 1,000 requests/path; eight matched blocks; four fresh processes per block: **32 processes / 64,000 requests**. Williams balanced orders and their reversals put every implementation in each trial position twice and balance predecessor order. Both four-block epochs and all per-block effects are retained. No host-load filtering, discarded timing sample, posthoc adjustment or threshold tuning was used. Local test/build activity was idle during timing.

Material small-cell criteria: paired median P95/P99 >10% **and** >0.5 ms, with at least 6/8 adverse pairs; CPU/request >15% with at least 6/8 adverse; RSS increase >max(20%,64 MiB) with at least 6/8 adverse; any wrong result, error, leak or invariant violation blocks. Six of eight is a slightly more conservative adverse-fraction rule than the earlier four of five. Remaining large inconsistent costs must be reported rather than automatically waived.

### Small-cache latency

Values are medians of process measurements. Percentages are medians of matched per-block effects, which can differ from ratios of column medians. P99 has 1,000 observations per process.

| Implementation | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P99 vs main | Adverse P99 pairs |
|---|---|---:|---:|---:|---:|---:|---:|
| Main | exact | 12.160 | 12.890 | 13.370 | 327.119 | — | — |
| Main | semantic | 12.268 | 13.100 | 14.270 | 324.670 | — | — |
| Expiry only | exact | 12.093 | 12.930 | 13.606 | 329.415 | +1.69% | 5/8 |
| Expiry only | semantic | 12.160 | 12.905 | 13.726 | 327.686 | -1.92% | 2/8 |
| Scheduling only | exact | 12.099 | 12.713 | 13.102 | 329.381 | -3.09% | 2/8 |
| Scheduling only | semantic | 12.111 | 12.902 | 13.437 | 327.644 | -4.13% | 2/8 |
| Combined (selected) | exact | 11.993 | 12.697 | 13.346 | 331.654 | -2.62% | 2/8 |
| Combined (selected) | semantic | 11.997 | 12.667 | 13.324 | 331.481 | -7.41% | 1/8 |

### Small-cache CPU, RSS and numerical admission wait

CPU totals cover **1,000 requests per path**. Queue is semaphore admission wait, not all executor/event-loop scheduling.

| Implementation | Path | CPU s / 1,000 | Paired CPU vs main | End RSS MiB | Queue P50/P95/P99 ms |
|---|---|---:|---:|---:|---|
| Main | exact | 3.070 | — | 59.861 | 6.329/6.905/7.174 |
| Main | semantic | 3.102 | — | 61.475 | 6.393/7.049/7.671 |
| Expiry only | exact | 3.039 | -0.51% | 59.920 | 6.295/6.894/7.282 |
| Expiry only | semantic | 3.055 | -0.76% | 61.479 | 6.333/6.894/7.409 |
| Scheduling only | exact | 3.148 | +3.06% | 59.918 | 6.110/6.615/6.835 |
| Scheduling only | semantic | 3.156 | +1.76% | 61.451 | 6.114/6.661/6.981 |
| Combined (selected) | exact | 3.125 | +2.27% | 59.885 | 6.058/6.581/6.957 |
| Combined (selected) | semantic | 3.141 | +0.00% | 61.404 | 6.049/6.583/6.882 |

### Factorial effects and attribution

E−M measures expiry with main scheduling; S−M measures scheduling without the bound; C−E measures scheduling with the bound; C−S measures expiry with immediate scheduling. These are source-factor comparisons, not claims about a particular callback or GIL mechanism.

| Contrast | Path | Paired P50 | Paired P95 | Paired P99 | P99 delta ms | Adverse P99 | Material flags |
|---|---|---:|---:|---:|---:|---:|---|
| E-M | exact | -0.57% | +0.51% | +1.69% | +0.222 | 5/8 | None |
| E-M | semantic | -1.01% | -1.44% | -1.92% | -0.271 | 2/8 | None |
| S-M | exact | -0.55% | -0.97% | -3.09% | -0.414 | 2/8 | None |
| S-M | semantic | -1.08% | -1.64% | -4.13% | -0.601 | 2/8 | None |
| C-M | exact | -1.22% | -0.85% | -2.62% | -0.354 | 2/8 | None |
| C-M | semantic | -2.06% | -3.66% | -7.41% | -1.075 | 1/8 | None |
| C-E | exact | -0.59% | -2.32% | -1.15% | -0.153 | 4/8 | None |
| C-E | semantic | -1.03% | -2.21% | -4.10% | -0.578 | 2/8 | None |
| C-S | exact | -0.89% | +0.22% | +2.47% | +0.320 | 6/8 | None |
| C-S | semantic | -1.10% | -1.62% | -1.42% | -0.185 | 3/8 | None |

Combined exact P50/P95 improved in all eight blocks; P99 improved in six. Exact P99 paired median was −2.62% (−0.354 ms), with both epoch medians negative; its two adverse pairs were +3.24% and +7.83%, neither individually above the relative material threshold. Semantic P99 median was −7.41% (−1.075 ms), improving in seven blocks and in both epochs. No contrast met a material regression rule. Combined versus expiry-only P99 medians were −1.15% exact and −4.10% semantic; expiry-only has no demonstrated tail advantage that warrants discarding scheduling.

**Small costs are retained:** combined exact CPU/request increased a median 2.27% in 8/8 blocks (about 0.070 s per 1,000 requests as a paired absolute effect), below the 15% gate. Scheduling-only exact CPU increased 3.06% in 8/8. Combined versus scheduling-only exact P99 increased 2.47% (+0.320 ms) in 6/8, below both material limits. This modest cost is justified by the verified latency/throughput gains and bounded resource use; it is not hidden or relabeled as an improvement.

Host CPU medians for M/C were 8.94%/8.62% on exact and 9.58%/8.83% on semantic; exact paired host differences ranged −3.73 to +2.77 percentage points. These conditions were quieter and more closely matched than earlier studies. The experiment supports no repeatable material implementation effect under its conditions. It does not prove host load alone caused earlier spikes or guarantee behavior at every host load/frequency/thermal state.

## Earlier adverse evidence and the engineering decision

The earlier five-pair 100-entry/four-reader comparison had exact P99 +17.8% (+4.53 ms), 4/5 adverse, and semantic P99 +11.8%, 4/5 adverse. Its longer exact confirmation retained +26.2% (+4.55 ms), 3/5 adverse; longer semantic P99 was nearly flat (+0.21%). The exact direction was adverse in 7/10 old process pairs. Those data, failed/positive observations and reports remain immutable outside the repository.

Those studies had substantial source-correlated host differences: exact host medians 40.7%→55.1% in the primary study and 16.2%→23.3% in the longer check. They established uncertainty and justified the draft; they did not establish a single implementation cause. The new source-isolating, position-balanced eight-block evidence does not reproduce their material latency effect in C−M, S−M or C−E. Removing scheduling would sacrifice large measured benefits without evidence of a remaining unacceptable small-cache cost. **Retain C and ship when exact-head CI passes**, with the small CPU cost and historical host-dependent uncertainty disclosed. No new broad audit, artificial workload tuning or further timing campaign was started.

## Final-source representative sanity checks

After selection and main synchronization, only 1,000/16 and 4,000/16 cells were measured again: three alternating fresh pairs, unchanged four native paths, 200 requests/path, **12 processes / 9,600 requests**. This is a supplement to the same-source five-pair full matrix below, not a replacement. Any wrong/error/leak blocks; repeated all-three tail/CPU/RSS effects beyond the unchanged numerical limits would prevent merge readiness. No alerts occurred; zero wrong results, errors, pending tasks or unexpected stderr. Maximum child peak RSS was 402.6 MiB.

| Entries | Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 | Adverse P50 pairs |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1000 | 16 | exact | 54.967 → 48.981 | 58.197 → 50.428 | 58.804 → 50.941 | 289.792 → 324.562 | -11.3% | 0/5 |
| 1000 | 16 | miss | 52.965 → 48.272 | 58.469 → 49.000 | 58.823 → 49.422 | 300.953 → 329.893 | -9.1% | 0/5 |
| 1000 | 16 | mixed | 57.837 → 54.338 | 62.919 → 59.605 | 65.850 → 61.093 | 273.928 → 292.373 | -6.0% | 0/5 |
| 1000 | 16 | semantic | 55.373 → 49.473 | 57.379 → 50.868 | 57.645 → 51.357 | 287.186 → 320.501 | -10.2% | 0/5 |
| 4000 | 16 | exact | 88.790 → 52.446 | 93.301 → 54.835 | 94.442 → 55.173 | 180.061 → 300.777 | -40.2% | 0/5 |
| 4000 | 16 | miss | 83.835 → 53.271 | 86.056 → 55.969 | 86.622 → 56.882 | 190.247 → 295.670 | -36.7% | 0/5 |
| 4000 | 16 | mixed | 85.196 → 65.222 | 93.868 → 71.282 | 96.361 → 73.739 | 184.517 → 243.538 | -21.4% | 0/5 |
| 4000 | 16 | semantic | 89.722 → 52.670 | 92.430 → 55.081 | 93.385 → 55.815 | 177.850 → 297.260 | -41.1% | 0/5 |

CPU totals below cover **200 requests per path**. The 1,000-entry miss CPU median increases 6.8%, below its material criterion; all metrics and individual effects remain in the external assessment.

| Entries | Readers | Path | CPU s / 200 | End RSS MiB | Peak RSS MiB | Queue P50 ms | Queue P95 ms | Queue P99 ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1000 | 16 | exact | 0.703 → 0.719 | 136.082 → 136.344 | 146.836 → 146.848 | 48.590 → 42.939 | 51.247 → 44.429 | 52.463 → 44.717 |
| 1000 | 16 | miss | 0.688 → 0.703 | 139.164 → 139.543 | 146.836 → 146.848 | 46.842 → 42.350 | 51.894 → 43.161 | 52.424 → 43.632 |
| 1000 | 16 | mixed | 0.734 → 0.703 | 142.957 → 142.918 | 146.836 → 146.848 | 51.619 → 48.805 | 56.319 → 53.523 | 58.396 → 54.433 |
| 1000 | 16 | semantic | 0.719 → 0.656 | 139.559 → 139.855 | 146.836 → 146.848 | 49.017 → 43.462 | 50.956 → 44.725 | 51.295 → 45.174 |
| 4000 | 16 | exact | 1.125 → 0.953 | 357.113 → 356.973 | 402.559 → 402.539 | 79.371 → 46.188 | 83.792 → 48.590 | 84.871 → 49.286 |
| 4000 | 16 | miss | 1.062 → 0.875 | 360.148 → 360.305 | 402.559 → 402.539 | 75.153 → 47.059 | 77.399 → 49.679 | 77.680 → 50.589 |
| 4000 | 16 | mixed | 1.125 → 0.969 | 361.918 → 361.781 | 402.559 → 402.539 | 77.341 → 58.648 | 83.382 → 64.426 | 86.567 → 66.082 |
| 4000 | 16 | semantic | 1.094 → 0.906 | 360.637 → 360.504 | 402.559 → 402.539 | 80.298 → 46.407 | 82.837 → 48.727 | 83.816 → 49.570 |

## Preserved same-source full matrix

The runtime hash is unchanged, so the previously verified 90-process/72,000-request five-pair matrix remains valid source-specific evidence: 100/1,000/4,000 entries, 1/4/16 readers, four paths, 200 requests/path. Main's cache package is unchanged. Do not splice its absolute timings with the newer session. All eight 1,000/4,000-entry warm exact/semantic concurrent benefit targets passed: ≥10% lower P50 and ≥10% higher throughput, at least 4/5 pairs improving.

The original gates remain: one-reader P50 >5% and >0.2 ms with ≥4/5 adverse; P95/P99 >10% and >0.5 ms with ≥4/5 adverse; CPU/request >15% with ≥4/5 adverse; peak RSS >max(20%,64 MiB) with ≥4/5 adverse; any correctness/resource violation blocks. The two historical small-cache tail flags are investigated above, not erased.

| Entries | Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 | Adverse P50 pairs |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | 1 | exact | 4.258 → 4.396 | 5.268 → 5.257 | 5.855 → 5.738 | 227.787 → 222.673 | +3.2% | 3/5 |
| 100 | 1 | miss | 4.493 → 4.234 | 5.510 → 5.241 | 6.004 → 6.181 | 218.688 → 228.720 | -5.8% | 0/5 |
| 100 | 1 | mixed | 4.447 → 4.419 | 5.335 → 5.368 | 5.735 → 5.804 | 219.116 → 220.181 | -3.1% | 1/5 |
| 100 | 1 | semantic | 4.273 → 4.288 | 5.147 → 4.901 | 6.351 → 5.349 | 230.477 → 230.026 | -1.8% | 1/5 |
| 100 | 4 | exact | 18.940 → 20.469 | 20.629 → 27.686 | 21.272 → 29.889 | 209.921 → 189.497 | +7.0% | 3/5 |
| 100 | 4 | miss | 18.141 → 19.650 | 21.849 → 23.744 | 23.696 → 25.288 | 213.266 → 193.029 | +11.9% | 4/5 |
| 100 | 4 | mixed | 20.010 → 17.126 | 26.397 → 24.781 | 28.897 → 30.493 | 194.756 → 223.075 | -7.7% | 2/5 |
| 100 | 4 | semantic | 18.238 → 19.256 | 21.599 → 25.794 | 23.023 → 27.195 | 215.659 → 191.656 | +2.6% | 5/5 |
| 100 | 16 | exact | 74.094 → 71.437 | 81.586 → 83.447 | 82.776 → 86.332 | 216.521 → 215.655 | -4.8% | 2/5 |
| 100 | 16 | miss | 73.281 → 74.075 | 91.766 → 84.365 | 93.933 → 87.277 | 213.861 → 213.169 | -5.5% | 1/5 |
| 100 | 16 | mixed | 77.206 → 80.761 | 92.094 → 92.196 | 99.658 → 95.778 | 200.956 → 191.625 | -2.0% | 1/5 |
| 100 | 16 | semantic | 76.563 → 72.670 | 90.506 → 89.993 | 93.394 → 91.555 | 205.131 → 207.146 | -8.5% | 2/5 |
| 1000 | 1 | exact | 5.876 → 5.188 | 7.238 → 6.175 | 7.709 → 7.265 | 166.551 → 189.920 | -12.8% | 1/5 |
| 1000 | 1 | miss | 5.485 → 5.214 | 6.921 → 6.195 | 7.832 → 6.740 | 179.569 → 189.065 | -7.3% | 2/5 |
| 1000 | 1 | mixed | 5.634 → 5.376 | 6.779 → 6.980 | 7.165 → 8.106 | 173.894 → 178.448 | -6.4% | 2/5 |
| 1000 | 1 | semantic | 5.618 → 5.255 | 6.477 → 6.423 | 7.032 → 7.282 | 175.870 → 187.187 | -4.8% | 1/5 |
| 1000 | 4 | exact | 20.183 → 18.206 | 22.022 → 20.522 | 22.862 → 21.464 | 198.016 → 215.610 | -17.8% | 0/5 |
| 1000 | 4 | miss | 19.852 → 17.534 | 21.826 → 20.240 | 23.717 → 21.864 | 201.412 → 223.834 | -13.8% | 0/5 |
| 1000 | 4 | mixed | 21.448 → 18.903 | 28.202 → 26.182 | 30.497 → 27.295 | 182.317 → 206.314 | -11.2% | 0/5 |
| 1000 | 4 | semantic | 21.386 → 18.098 | 23.739 → 20.601 | 24.567 → 21.425 | 186.614 → 218.587 | -15.8% | 0/5 |
| 1000 | 16 | exact | 86.174 → 72.626 | 98.143 → 79.580 | 99.936 → 82.685 | 178.938 → 216.007 | -15.2% | 0/5 |
| 1000 | 16 | miss | 85.172 → 65.551 | 93.953 → 73.707 | 95.291 → 76.057 | 183.936 → 242.109 | -23.2% | 0/5 |
| 1000 | 16 | mixed | 91.067 → 74.731 | 98.562 → 80.804 | 102.768 → 82.690 | 172.481 → 214.361 | -16.5% | 1/5 |
| 1000 | 16 | semantic | 88.319 → 66.784 | 91.898 → 71.874 | 93.730 → 72.910 | 179.425 → 237.018 | -17.1% | 0/5 |
| 4000 | 1 | exact | 9.659 → 7.517 | 11.129 → 8.768 | 11.931 → 9.518 | 103.267 → 130.943 | -23.7% | 0/5 |
| 4000 | 1 | miss | 8.810 → 7.426 | 10.466 → 9.066 | 11.119 → 9.829 | 110.932 → 132.854 | -15.7% | 1/5 |
| 4000 | 1 | mixed | 8.912 → 7.025 | 10.477 → 8.707 | 11.097 → 10.037 | 111.783 → 138.371 | -22.7% | 0/5 |
| 4000 | 1 | semantic | 9.633 → 7.685 | 11.052 → 9.070 | 12.028 → 9.880 | 102.713 → 128.342 | -23.9% | 1/5 |
| 4000 | 4 | exact | 36.618 → 23.373 | 41.058 → 27.377 | 44.836 → 28.449 | 107.842 → 168.200 | -36.2% | 0/5 |
| 4000 | 4 | miss | 34.169 → 23.039 | 36.984 → 27.094 | 38.364 → 28.654 | 116.470 → 170.820 | -32.2% | 0/5 |
| 4000 | 4 | mixed | 36.215 → 25.746 | 46.937 → 34.954 | 49.458 → 37.463 | 108.744 → 152.039 | -28.0% | 0/5 |
| 4000 | 4 | semantic | 38.746 → 24.776 | 41.683 → 28.756 | 42.903 → 30.036 | 102.653 → 158.775 | -36.1% | 0/5 |
| 4000 | 16 | exact | 148.253 → 92.014 | 171.091 → 99.233 | 176.289 → 100.433 | 105.639 → 169.419 | -37.8% | 0/5 |
| 4000 | 16 | miss | 134.039 → 91.473 | 149.350 → 101.607 | 151.907 → 103.643 | 117.074 → 167.989 | -32.3% | 0/5 |
| 4000 | 16 | mixed | 143.438 → 103.529 | 160.012 → 118.965 | 164.700 → 123.042 | 110.043 → 152.763 | -27.0% | 0/5 |
| 4000 | 16 | semantic | 147.160 → 94.253 | 161.925 → 107.783 | 163.928 → 110.697 | 107.552 → 166.689 | -35.7% | 0/5 |

| Entries | Readers | Path | CPU s / 200 | End RSS MiB | Peak RSS MiB | Queue P50 ms | Queue P95 ms | Queue P99 ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | 1 | exact | 0.875 → 0.875 | 58.992 → 59.027 | 59.027 → 59.027 | 0.004 → 0.004 | 0.006 → 0.006 | 0.008 → 0.008 |
| 100 | 1 | miss | 0.875 → 0.875 | 62.184 → 62.211 | 62.184 → 62.211 | 0.004 → 0.004 | 0.006 → 0.007 | 0.008 → 0.010 |
| 100 | 1 | mixed | 0.922 → 0.906 | 65.777 → 65.555 | 65.777 → 65.555 | 0.004 → 0.004 | 0.006 → 0.006 | 0.007 → 0.008 |
| 100 | 1 | semantic | 0.875 → 0.891 | 62.602 → 62.449 | 62.602 → 62.449 | 0.004 → 0.004 | 0.006 → 0.006 | 0.008 → 0.008 |
| 100 | 4 | exact | 0.938 → 1.125 | 59.160 → 59.309 | 59.160 → 59.309 | 10.059 → 10.363 | 11.356 → 14.450 | 11.893 → 15.893 |
| 100 | 4 | miss | 0.953 → 1.109 | 62.344 → 62.348 | 62.344 → 62.348 | 9.631 → 9.911 | 12.043 → 12.391 | 12.704 → 13.789 |
| 100 | 4 | mixed | 1.062 → 0.922 | 66.320 → 65.988 | 66.320 → 65.988 | 11.266 → 9.325 | 16.724 → 15.352 | 18.106 → 17.225 |
| 100 | 4 | semantic | 0.938 → 1.047 | 62.715 → 62.652 | 62.715 → 62.680 | 9.653 → 9.785 | 11.395 → 13.444 | 12.558 → 14.504 |
| 100 | 16 | exact | 0.891 → 0.938 | 60.066 → 59.957 | 60.066 → 59.957 | 65.535 → 62.597 | 72.575 → 73.298 | 73.303 → 74.935 |
| 100 | 16 | miss | 0.906 → 0.953 | 63.305 → 63.215 | 63.305 → 63.273 | 64.544 → 64.975 | 81.163 → 74.038 | 83.783 → 77.379 |
| 100 | 16 | mixed | 1.000 → 0.984 | 66.992 → 67.035 | 66.992 → 67.035 | 69.186 → 71.400 | 83.452 → 82.022 | 90.852 → 85.311 |
| 100 | 16 | semantic | 0.969 → 1.000 | 63.836 → 63.688 | 63.836 → 63.688 | 67.606 → 63.625 | 80.785 → 78.793 | 83.471 → 80.210 |
| 1000 | 1 | exact | 1.188 → 1.047 | 135.930 → 136.000 | 146.840 → 146.902 | 0.004 → 0.004 | 0.007 → 0.007 | 0.008 → 0.009 |
| 1000 | 1 | miss | 1.125 → 1.016 | 138.992 → 139.078 | 146.840 → 146.902 | 0.004 → 0.005 | 0.007 → 0.007 | 0.009 → 0.009 |
| 1000 | 1 | mixed | 1.141 → 1.094 | 141.898 → 142.023 | 146.840 → 146.902 | 0.004 → 0.004 | 0.007 → 0.008 | 0.008 → 0.011 |
| 1000 | 1 | semantic | 1.125 → 1.062 | 139.277 → 139.266 | 146.840 → 146.902 | 0.004 → 0.004 | 0.006 → 0.007 | 0.008 → 0.010 |
| 1000 | 4 | exact | 1.016 → 1.062 | 135.977 → 136.082 | 146.879 → 146.961 | 11.119 → 9.355 | 12.417 → 10.741 | 13.119 → 11.532 |
| 1000 | 4 | miss | 1.016 → 1.016 | 139.031 → 139.152 | 146.879 → 146.961 | 10.989 → 8.981 | 12.301 → 10.867 | 13.817 → 11.654 |
| 1000 | 4 | mixed | 1.078 → 1.031 | 142.238 → 142.156 | 146.879 → 146.961 | 12.367 → 10.437 | 16.882 → 16.269 | 18.137 → 17.596 |
| 1000 | 4 | semantic | 1.078 → 1.125 | 139.316 → 139.379 | 146.879 → 146.961 | 11.744 → 9.297 | 13.305 → 10.821 | 14.373 → 11.634 |
| 1000 | 16 | exact | 1.094 → 1.094 | 136.238 → 136.449 | 146.973 → 146.852 | 76.463 → 63.513 | 86.897 → 70.625 | 89.651 → 73.610 |
| 1000 | 16 | miss | 1.062 → 0.984 | 139.332 → 139.523 | 146.973 → 146.852 | 75.525 → 57.677 | 83.720 → 64.828 | 85.783 → 67.047 |
| 1000 | 16 | mixed | 1.172 → 1.000 | 143.027 → 143.141 | 146.973 → 146.852 | 82.427 → 66.838 | 88.729 → 73.002 | 91.708 → 73.851 |
| 1000 | 16 | semantic | 1.109 → 0.953 | 139.887 → 139.898 | 146.973 → 146.852 | 78.504 → 58.649 | 82.065 → 63.501 | 83.527 → 64.472 |
| 4000 | 1 | exact | 1.891 → 1.484 | 356.430 → 356.598 | 402.449 → 402.535 | 0.005 → 0.005 | 0.008 → 0.007 | 0.010 → 0.009 |
| 4000 | 1 | miss | 1.781 → 1.484 | 359.516 → 359.668 | 402.449 → 402.535 | 0.005 → 0.005 | 0.008 → 0.008 | 0.010 → 0.010 |
| 4000 | 1 | mixed | 1.734 → 1.375 | 360.727 → 360.598 | 402.449 → 402.535 | 0.004 → 0.004 | 0.007 → 0.007 | 0.008 → 0.010 |
| 4000 | 1 | semantic | 1.938 → 1.500 | 359.836 → 359.855 | 402.449 → 402.535 | 0.005 → 0.005 | 0.008 → 0.007 | 0.011 → 0.009 |
| 4000 | 4 | exact | 1.828 → 1.594 | 356.613 → 356.594 | 402.387 → 402.574 | 21.312 → 12.258 | 23.986 → 15.166 | 25.319 → 16.722 |
| 4000 | 4 | miss | 1.688 → 1.578 | 359.703 → 359.641 | 402.387 → 402.574 | 20.095 → 12.098 | 22.122 → 14.887 | 23.386 → 16.598 |
| 4000 | 4 | mixed | 1.812 → 1.547 | 360.914 → 360.871 | 402.387 → 402.574 | 22.078 → 15.399 | 27.668 → 21.337 | 30.148 → 23.135 |
| 4000 | 4 | semantic | 1.891 → 1.688 | 359.891 → 359.918 | 402.387 → 402.574 | 22.525 → 13.021 | 24.416 → 15.756 | 25.579 → 16.677 |
| 4000 | 16 | exact | 1.906 → 1.609 | 356.965 → 357.953 | 402.516 → 403.438 | 132.587 → 81.408 | 154.689 → 88.604 | 156.197 → 90.020 |
| 4000 | 16 | miss | 1.734 → 1.578 | 360.176 → 361.023 | 402.516 → 403.438 | 120.294 → 80.659 | 135.361 → 90.131 | 136.969 → 92.709 |
| 4000 | 16 | mixed | 1.812 → 1.562 | 361.805 → 361.871 | 402.516 → 403.438 | 129.389 → 93.452 | 143.227 → 106.045 | 148.591 → 108.734 |
| 4000 | 16 | semantic | 1.844 → 1.625 | 360.578 → 361.477 | 402.516 → 403.438 | 131.815 → 83.324 | 144.755 → 96.307 | 149.125 → 98.657 |

The same-source finite-TTL sensitivity has 30 processes/24,000 requests at 1,000 entries, 1/4/16 readers and 3,600s TTL. No material regression rule was met. Sixteen-reader semantic benefit was less consistent: median P50 −22.8% and throughput +23.5%, but only 3/5 improving, short of the 4/5 benefit target. Its two adverse P50 effects were +12.4%/+23.5%, P99 +21.8%/+39.4%. These are a documented consistency limit, not a fully qualified finite-TTL benefit claim. No expiry-storm performance claim is made.

## Correctness, compatibility and CI

The selected synchronized source passed configured Ruff/format, strict mypy and pinned Pyright; the full offline suite passed **1,572 tests, with 80 skipped and 401 service-dependent cases deselected**. Source-checked Python 3.14 memory/inspection validation passed **108 tests, 66 deselected**; server embedded parity passed **24**; reuse-quality validation and both custom examples passed. Four-factor preflight passed all 77 existing memory tests on M/S and all 85 including expiry on E/C. Existing assertions remain unchanged.

The deadline tests cover exact monotonic equality, finite/no expiry, global cleanup across namespaces, counters, replacement/removal with early bounds, clear-all/close, and three seeded 240-operation histories against main's original full-scan oracle. Scheduling barriers protect waiting/running cancellation, already-finished results/errors/cancellation, submission failures, abandoned errors, cold snapshot ownership, context, stale revisions and shutdown. Numerical/query/snapshot/item ASTs are identical across variants and current main.

The existing exact-source resource proof remains applicable: 5,000 entries, 32 cancelled callers, 128 replacement writes, 100 store cycles, maximum one active numerical worker, 480.3 MiB peak, no owned work after drainage and threads returning after executor shutdown. Source/dependencies/ownership are unchanged, so it was not needlessly repeated.

Actual current-runtime CI on `f2dee6d` previously passed all 39 Quality jobs, including embedded Python 3.11–3.14, live-store coverage, wheel/certification checks and 94.74% combined coverage on Python 3.14. Synchronization adopted only main's already-approved frontend/security changes; **fresh required checks for the final PR head must also pass**. The PR description records the exact new run/head and outcome; historical CI is not presented as a current-head pass. Local service skips are not passing integration evidence. The unchanged 90% coverage and security gates remain in force.

An earlier untouched Windows mocked-provider timer test failed on main 2/5 in bounded isolation versus candidate 0/5; subsequent full suites, including this final run, passed. Provider code is unchanged; that separate uncertainty remains recorded, without broadening this task.

## Reproduction and limits

Saved V2 `text-embedding-3-small` vectors are 1,325×1,536D float64; zero new provider calls. Strict threshold 0.9691803520567825; 13 frozen development semantic queries at threshold 0.8; capacity 5,000; seed 20261024; ten exact warmups. Primary timing TTL is disabled; finite-TTL evidence is separate. The 4,000-entry stress repeats 1,000 real vectors using compatible-answer aliases, not 4,000 independently embedded prompts. Four paths are exact hit, populated-scope read-only miss, semantic hit and qualified 70/30 native mixed resolution with unique miss namespaces and zero-delay generation. Fixture correctness is not proof of general semantic-reuse safety.

Windows x64, CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4, 8 physical/16 logical CPUs. BLAS limits are one before import and the loaded getter reads back one. No affinity, priority, power, GC or production BLAS changes were made. Host busy is measured, not CPU frequency/thermals; Linux performance and behavior under every host state are not established. Historical 1,000-entry GPTCache P50 6.001/10.759 ms at 4/16 readers is a reference only; no fresh head-to-head or competitive victory is claimed.

The narrow rule `/packages/cache/benchmarks/memory_scheduling/*.csv` remains. Only this narrative and [the provenance manifest](manifest.json) are tracked here. Original CSVs remain untracked with their recorded hashes and local copies intact. Full raw CSVs, process JSONs, source variants, frozen plans, assessments, harnesses, failed/positive records and old reports remain in maintainer workspace `Semantix_Memory_P2_20261025_b3836049`. Saved V2 vectors and P1 research are preserved. This PR alone is not independently reproducible without that external evidence; the manifest records the access limitation and hashes.

`ship_small.py` replays the fixed 32-process Williams comparison using preserved `corrected_bench.launch`; `ship_assess.py` verifies source hashes, all labels/jobs/namespaces/generation counts, task drainage and stderr before calculating factorial/epoch effects. `ship_sanity.py` records the two selected-source larger cells. Replays must use fresh IDs/manifests and the frozen environment/config/network guard, never overwrite historical evidence.

The pre-sync head is retained as `perf/memory-reader-scheduling-research` and in an incremental verified Git bundle. No branch/history was discarded, no protected branch pushed, and no PR was automatically merged. No Phase 03, SQLite, adaptive thresholds, PR #212, mandatory dependency, Rust/FAISS or unrelated implementation work is included.
