# MemoryStore Phase 02: reader scheduling and expiry bookkeeping

**Publication decision: update existing PR #234 as draft. The implementation is useful for review; it is not merge-ready.** The selected follow-up preserves safe immediate dispatch and skips redundant expiry scans using one conservative deadline. It removes the original 4,000-entry single-reader P50 penalty: paired exact/semantic gains are 23.7%/23.9% versus the normalization baseline. All eight primary warm-hit concurrent benefit targets pass.

The remaining concern is the 100-entry/four-reader exact-hit tail: primary P99 +17.8% (+4.53 ms), 4/5 adverse; longer confirmation +26.2% (+4.55 ms), 3/5 adverse. The longer study does not satisfy the four-of-five material-regression repetition rule, but it does not establish that the substantial residual cost is harmless. Host-load differences confound attribution. Both studies remain visible; no claim of a resolved small-cache trade-off or merge readiness is made. Semantic P99 in the longer check was nearly flat (+0.21%, +0.03 ms).

CPU/RSS and correctness/resource gates pass locally. Finite-TTL sixteen-reader semantic benefit is less consistent (3/5 improving), despite favorable medians. This bounded phase ends with an updated draft and a specific remaining performance concern, not another open-ended campaign. Current main has advanced to `5044c050b7f7a5ce57fa86158071b2fddac9e013`; its cache package is unchanged from the measured baseline. Rebase remains deferred as requested.

## Change and bottleneck attribution

Baseline is merged PR #233, main `4fdc884e876ef370b5c16c19a705138575a6226f`, MemoryStore SHA256 `c6c13c8ba3d2e394f0a8fa5f83e1065533abaa4ae9c296fb6e3872abfb5cf4a7`. Final MemoryStore SHA256 is `38df02ddecc985f2bddae568f0ea2acbf52cea33a1ae72a10c2ac6b358d65201`. All final measurements below import and verify that exact source. Main has PR #233's normalization optimization already.

The PR submits numerical work immediately to the existing executor, preserving each caller's context. One worker remains admitted at a time. A private completion future wakes the caller only after the worker's ownership and admission are released. Cancellation detaches the caller while the worker retains admission until it finishes; abandoned exceptions are consumed. No completion bypass or contention-sensitive ownership shortcut was adopted.

Separate profiles attributed material delay to scheduling and GIL-held expiry bookkeeping. At 1,000 entries the earlier matched profile measured submission-to-worker-entry around 2.9 ms on main versus 1.7–1.8 ms with immediate dispatch, while state-lock wait and warm snapshot preparation were small. At 4,000 entries, repeated global expiry scans consumed roughly 1.0–1.15 ms per request in aggregate. All instrumented future creation was about 4.6–4.8 microseconds, context copying about 1 microsecond, executor submission about 32 microseconds, and completion callbacks about 9 microseconds. These diagnostic spans overlap, include instrumentation, and are not additive. They do not establish that completion handling caused the historical 350–445 microsecond single-reader penalty.

The selected follow-up removes that measured redundant metadata work. One conservative monotonic deadline lets `_purge` return before any expiry is due. A due scan removes all expired entries, increments their counters and rebuilds the next bound in the same pass. Writes lower the bound as needed. Removal/replacement can leave an early bound and cause one extra scan, but cannot postpone expiration. Clear-all and close reset the bound. No heap, expiry-index abstraction, additional worker, dependency, scoring change or public API change was introduced. This uses the preserved P1 expiry work as a read-only algorithm reference and evaluates it afresh with the current scheduling transport; old P1 timings are not evidence for this implementation.

Numerical scoring, `_query_vector`, `_Snapshot` and `_Item` ASTs match merged main exactly. Float64 reduction, tie ordering, snapshot retention and namespace/revision confirmation remain unchanged. Numerical search stays off the event loop. Search admission is still serialized, so queueing and facade embedding/candidate validation remain important limits.

## Final acceptance experiment

The plan and criteria were written before timing. Primary matrix: 100/1,000/4,000 entries × 1/4/16 readers × five paired fresh-process repetitions × two sources, **90 processes and 72,000 end-to-end requests**. Every process measures 200 requests on each of four native paths. Sources alternate order; every pair has identical vectors, labels, namespaces, seeds, thresholds, cache policies and observation wrappers. No samples were excluded for host load.

A separate default-TTL sensitivity uses 3,600 seconds, 1,000 entries and 1/4/16 readers, five pairs: **30 processes and 24,000 requests**. TTL policy is identical within each pair. This measures finite deadlines before they become due; it is not an expiry-storm performance claim. Exact expiry behavior, including equality at the deadline, is covered by clock-controlled tests and the original-scan differential oracle.

Material criteria, unchanged after timing:

- One-reader P50: median paired increase >5% **and** >0.2 ms, with at least 4/5 adverse pairs.
- P95/P99: median paired increase >10% **and** >0.5 ms, with at least 4/5 adverse pairs.
- CPU per request: median paired increase >15%, with at least 4/5 adverse pairs.
- Peak RSS: median paired increase >max(20% of baseline, 64 MiB), with at least 4/5 adverse pairs.
- Any incorrect result, error, stale confirmation, TTL/counter violation, leaked work or unbounded resource use blocks publication as a ready implementation.
- Benefit target: at least 10% lower P50 and 10% higher throughput on warm exact/semantic hits at 1,000/4,000 entries and both 4/16 readers, with at least 4/5 pairs improving. Target misses are reported separately from harmful-regression gates.

Values below are medians of process measurements, main → final PR source. Percentages are medians of paired effects, which can differ from ratios of column medians. CPU seconds cover exactly 200 requests per phase. Queue is numerical admission wait; it does not include all executor or event-loop scheduling. Peak RSS is process high-water memory and includes setup.

### Primary latency and throughput

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

### Primary CPU, memory and queue wait

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

### Every adverse primary latency median

All positive paired latency medians are retained, including small or inconsistent ones. An isolated unfavorable pair is uncertainty, not automatically a demonstrated regression. Repeated material effects use the criteria above.

| Entries | Readers | Path | Metric | Paired change | Absolute change ms | Adverse pairs | Material blocker |
|---:|---:|---|---|---:|---:|---:|---|
| 100 | 1 | exact | P50 | +3.25% | +0.138 | 3/5 | No |
| 100 | 1 | exact | P99 | +6.22% | +0.318 | 3/5 | No |
| 100 | 4 | exact | P50 | +6.96% | +1.534 | 3/5 | No |
| 100 | 4 | exact | P95 | +13.12% | +3.167 | 5/5 | YES |
| 100 | 4 | exact | P99 | +17.80% | +4.530 | 4/5 | YES |
| 100 | 4 | miss | P50 | +11.88% | +1.740 | 4/5 | No |
| 100 | 4 | miss | P95 | +8.09% | +1.619 | 4/5 | No |
| 100 | 4 | miss | P99 | +7.40% | +1.292 | 4/5 | No |
| 100 | 4 | mixed | P95 | +3.19% | +0.767 | 3/5 | No |
| 100 | 4 | mixed | P99 | +20.94% | +5.279 | 3/5 | No |
| 100 | 4 | semantic | P50 | +2.62% | +0.438 | 5/5 | No |
| 100 | 4 | semantic | P95 | +19.42% | +4.194 | 5/5 | YES |
| 100 | 4 | semantic | P99 | +11.77% | +2.863 | 4/5 | YES |
| 100 | 16 | mixed | P99 | +3.47% | +3.011 | 3/5 | No |
| 100 | 16 | semantic | P95 | +0.70% | +0.515 | 3/5 | No |
| 100 | 16 | semantic | P99 | +1.12% | +0.845 | 3/5 | No |
| 1000 | 1 | mixed | P99 | +16.17% | +1.385 | 3/5 | No |
| 1000 | 1 | semantic | P99 | +3.56% | +0.250 | 3/5 | No |

### One targeted longer confirmation: 100 entries, four readers

The primary 100-entry/four-reader exact and semantic tails crossed the predefined material threshold. Candidate phases also had higher host CPU load: exact medians 40.7% → 55.1%, and semantic paired differences +2.7 to +21.0 percentage points. That is a measured confound, not grounds to discard those samples. Before further timing, the permitted single longer check was fixed: the same 100-entry/four-reader cell, five paired fresh processes per source, 2,000 requests each on exact and semantic hits, 10 processes and 40,000 requests. Criteria and resource limits stayed unchanged. Both paths run in order on the same store, and no samples are excluded. This isolates the affected hit paths rather than rerunning the full matrix.

**The exact-hit tail risk remains unresolved; keep the PR draft.** Longer exact P95/P99 effects are +11.5%/+26.2% (+1.78/+4.55 ms), adverse in 3/5 pairs. This does not satisfy the predeclared >=4/5 rule in the confirmation, but the P99 direction was adverse in 7/10 process pairs across the two separately reported studies. It is not an isolated unfavorable sample. Exact throughput fell a median 4.8%; CPU/request rose 6.6%, below its material threshold. Longer semantic P95/P99 were +0.61%/+0.21%, neither material. Exact host CPU medians were 16.2% → 23.3%, so a causal implementation regression is not established. No host adjustment, sample exclusion or pooling of the two studies is used. The evidence is insufficient to recommend merging this small-cache trade-off; no second confirmation or new campaign was run.

| Entries | Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 | Adverse P50 pairs |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | 4 | exact | 13.914 → 14.406 | 15.490 → 17.275 | 17.395 → 21.946 | 283.840 → 270.272 | +3.5% | 3/5 |
| 100 | 4 | semantic | 14.194 → 13.641 | 17.004 → 15.761 | 19.658 → 18.177 | 273.924 → 287.483 | +0.5% | 3/5 |

The following CPU totals cover **2,000 requests** per phase, unlike the 200-request primary table.

| Entries | Readers | Path | CPU s / 2,000 | End RSS MiB | Peak RSS MiB | Queue P50 ms | Queue P95 ms | Queue P99 ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 100 | 4 | exact | 7.156 → 7.625 | 60.738 → 60.668 | 60.738 → 60.668 | 7.305 → 7.300 | 8.284 → 8.823 | 9.895 → 11.568 |
| 100 | 4 | semantic | 7.312 → 7.203 | 62.824 → 62.754 | 62.824 → 62.859 | 7.433 → 6.912 | 8.993 → 8.061 | 10.596 → 9.949 |

| Entries | Readers | Path | Metric | Paired change | Absolute change ms | Adverse pairs | Material blocker |
|---:|---:|---|---|---:|---:|---:|---|
| 100 | 4 | exact | P50 | +3.54% | +0.492 | 3/5 | No |
| 100 | 4 | exact | P95 | +11.52% | +1.785 | 3/5 | No |
| 100 | 4 | exact | P99 | +26.17% | +4.552 | 3/5 | No |
| 100 | 4 | semantic | P50 | +0.54% | +0.068 | 3/5 | No |
| 100 | 4 | semantic | P95 | +0.61% | +0.082 | 3/5 | No |
| 100 | 4 | semantic | P99 | +0.21% | +0.030 | 3/5 | No |

### Finite-TTL sensitivity: latency and throughput

| Entries | Readers | Path | P50 ms | P95 ms | P99 ms | Requests/s | Paired P50 | Adverse P50 pairs |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1000 | 1 | exact | 6.222 → 5.574 | 7.127 → 6.597 | 7.584 → 7.405 | 158.411 → 176.528 | -9.5% | 0/5 |
| 1000 | 1 | miss | 5.942 → 5.492 | 7.071 → 6.600 | 7.753 → 7.365 | 166.856 → 178.955 | -9.9% | 0/5 |
| 1000 | 1 | mixed | 6.237 → 5.609 | 7.239 → 6.889 | 7.707 → 7.392 | 158.143 → 173.853 | -11.4% | 0/5 |
| 1000 | 1 | semantic | 6.169 → 5.472 | 7.460 → 6.643 | 7.807 → 7.515 | 159.186 → 178.775 | -11.5% | 0/5 |
| 1000 | 4 | exact | 24.660 → 20.362 | 28.197 → 22.882 | 32.595 → 24.788 | 160.295 → 194.447 | -18.4% | 0/5 |
| 1000 | 4 | miss | 24.567 → 20.091 | 27.002 → 22.216 | 28.528 → 24.923 | 161.464 → 196.604 | -15.3% | 0/5 |
| 1000 | 4 | mixed | 25.160 → 22.603 | 32.629 → 30.899 | 34.262 → 32.575 | 154.944 → 171.561 | -10.2% | 0/5 |
| 1000 | 4 | semantic | 26.843 → 20.569 | 32.481 → 22.623 | 33.593 → 24.197 | 144.426 → 193.605 | -20.6% | 0/5 |
| 1000 | 16 | exact | 109.010 → 93.677 | 120.895 → 109.958 | 126.321 → 114.846 | 146.147 → 166.550 | -20.0% | 1/5 |
| 1000 | 16 | miss | 102.523 → 92.681 | 119.439 → 102.300 | 121.765 → 103.407 | 151.918 → 169.134 | -19.6% | 1/5 |
| 1000 | 16 | mixed | 112.758 → 95.080 | 133.466 → 132.424 | 137.793 → 137.696 | 138.567 → 165.172 | -24.4% | 1/5 |
| 1000 | 16 | semantic | 110.989 → 104.539 | 138.989 → 133.441 | 142.117 → 139.095 | 141.116 → 146.519 | -22.8% | 2/5 |

### Finite-TTL sensitivity: CPU, memory and queue wait

| Entries | Readers | Path | CPU s / 200 | End RSS MiB | Peak RSS MiB | Queue P50 ms | Queue P95 ms | Queue P99 ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1000 | 1 | exact | 1.266 → 1.141 | 136.059 → 136.145 | 146.922 → 146.910 | 0.005 → 0.005 | 0.007 → 0.007 | 0.009 → 0.009 |
| 1000 | 1 | miss | 1.188 → 1.125 | 139.227 → 139.285 | 146.922 → 146.910 | 0.005 → 0.005 | 0.007 → 0.007 | 0.009 → 0.009 |
| 1000 | 1 | mixed | 1.266 → 1.156 | 141.805 → 141.836 | 146.922 → 146.910 | 0.005 → 0.005 | 0.007 → 0.007 | 0.009 → 0.009 |
| 1000 | 1 | semantic | 1.266 → 1.141 | 139.531 → 139.598 | 146.922 → 146.910 | 0.005 → 0.005 | 0.007 → 0.007 | 0.009 → 0.009 |
| 1000 | 4 | exact | 1.266 → 1.172 | 136.285 → 136.398 | 146.973 → 146.938 | 13.585 → 10.505 | 15.709 → 12.150 | 17.564 → 13.275 |
| 1000 | 4 | miss | 1.203 → 1.109 | 139.469 → 139.566 | 146.973 → 146.938 | 13.526 → 10.333 | 15.382 → 11.613 | 16.152 → 13.382 |
| 1000 | 4 | mixed | 1.312 → 1.188 | 142.199 → 142.141 | 146.973 → 146.938 | 14.502 → 12.752 | 20.650 → 18.915 | 21.878 → 20.041 |
| 1000 | 4 | semantic | 1.328 → 1.188 | 139.895 → 139.887 | 146.973 → 146.938 | 14.772 → 10.551 | 17.452 → 12.304 | 19.231 → 12.889 |
| 1000 | 16 | exact | 1.391 → 1.297 | 136.820 → 137.004 | 146.812 → 146.984 | 96.515 → 82.653 | 106.444 → 97.569 | 114.993 → 101.549 |
| 1000 | 16 | miss | 1.328 → 1.344 | 140.148 → 140.219 | 146.812 → 146.984 | 90.897 → 81.630 | 105.714 → 90.794 | 108.796 → 91.467 |
| 1000 | 16 | mixed | 1.453 → 1.281 | 143.156 → 143.051 | 146.812 → 146.984 | 101.104 → 85.777 | 120.511 → 120.142 | 128.695 → 123.407 |
| 1000 | 16 | semantic | 1.438 → 1.406 | 140.699 → 140.488 | 146.812 → 146.984 | 98.808 → 92.357 | 123.437 → 118.899 | 126.204 → 123.908 |

### Every adverse finite-TTL latency median

No positive median paired P50/P95/P99 effects in this comparison.

All eight primary warm-hit benefit targets passed. The finite-TTL sixteen-reader semantic cell missed the four-of-five repetition target: median paired P50 −22.8% and throughput +23.5%, but two of five pairs were adverse (P50 +12.4%/+23.5%, P99 +21.8%/+39.4%). Its median tails and CPU improved and it did not meet the repeated material-regression rule. This is a disclosed consistency limit, not a fully qualified finite-TTL benefit claim.

The external assessments additionally retain every per-pair ratio and absolute difference, CPU/RSS effects, host CPU busy and thread counts, and explicit material blockers and benefit-target misses. Full raw per-request evidence is preserved outside Git.

## Implemented and rejected candidates

The current candidate first passed a three-pair scout against both merged main and the previously published PR source at 4,000 entries and 1/4/16 readers: 27 fresh processes, 21,600 requests. Compared with the published implementation, one-reader exact/semantic P50 improved 18.3%/17.4%; four-reader exact improved 31.5%, sixteen-reader exact 20.2%. Four-reader mixed P95/P99 worsened 5.5%/4.3% in two of three pairs; those observations remain in the scout assessment and did not meet the predefined obvious-harm rule. These are scouting results, not substitutes for the five-pair final matrix above.

Previously implemented alternatives remain preserved externally: admission caps 2/4 and four-request batching worsened mixed tails; a one-turn yield and deferred `to_thread` task did not pass their paired scout. They were not repeated or adopted. No extra executor, cap 8, event-loop numerical fast path, mandatory dependency, Rust or FAISS was added.

The original private-future source `3c733129296bf0afa89a11192dd7a9d35539d1aef1020b1ce627e396a9b13e73` had one-reader exact/semantic P50 regressions of 6.8%/8.4%, adverse in all five original pairs. Its concurrent exact gains were 21.1%/24.7% at 4/16 readers. Those source-specific results remain unchanged externally; they do not describe the new source. A later unchanged-source three-pair scout did not reproduce that single-reader cost, which adds uncertainty rather than erasing the original evidence. An earlier 150-process matrix and longer confirmation used source `3bcc138c02013ef02c812d83bc79abc40f1637a60208f04835153b689e63ce85`, a different completion transport; they are explicitly historical, not final-source qualification. Original reports are archived in the maintainer workspace.

## Correctness, failure paths and CI

The new deadline tests cover reads without scans, finite/non-expiring entries, exact monotonic equality, foreign-namespace cleanup, revision confirmation, replacement/deletion with conservative early bounds, counters, clear-all and close. Three seeded 240-operation histories compare against main's original full-scan algorithm, including TTL writes, eviction, namespace clear, deletion, nearest lookup and hit confirmation. Keys, LRU ordering, revisions, entries, expiry deadlines and counters must match exactly. No production assertions or existing regression tests were removed.

The inspection fixture formerly rewrote private entry expiry directly. It now writes a genuine finite TTL and advances the monotonic clock to the stored deadline, leaving UTC metadata independent. The existing assertions are retained, the read-only state snapshot also includes the deadline bound, and all 23 memory inspection tests pass against original main with this fixture.

Local final-source evidence:

- 85 numerical/snapshot/scheduling/expiry tests pass on Python 3.11 and 3.14 with source-import assertions, including existing cancellation, already-finished success/error/cancellation, executor failure, context, stale revisions, namespace isolation and shutdown checks.
- Full offline package suite: **1,572 passed, 80 skipped, 401 deselected**. MySQL/PostgreSQL/Redis live-service coverage is not represented as passing locally.
- Server embedded parity: 24 passed with source-import assertions. Reuse-quality validation and both custom integration/store examples pass.
- Configured Ruff/format, strict mypy and pinned Pyright pass. Wheel/sdist build, Twine and archive validation pass.
- Near-capacity resource proof: 5,000 entries, 32 cancelled callers, 128 replacement writes and 100 new-store cycles. Maximum active numerical workers remains one; peak RSS 480.3 MiB; thread count returns to the starting count after executor and monitor shutdown. Drained workers and snapshots are empty after cancellation/mutation; resource ownership stays bounded.

Initial offline validation exposed the inspection fixture issue above, which was corrected without weakening assertions. A subsequent full run hit the untouched mocked provider test `test_swallowed_deadline_still_fails_safely`. In ten bounded isolation processes, unchanged main failed 2/5 and this candidate failed 0/5; the provider implementation is byte-identical. The final full run passed. This remains a disclosed Windows timer-dependent provider uncertainty, not a passing live-provider test or a reason to alter provider code in this PR. Earlier failed logs/XML remain preserved.

The current-source CI status and exact run/head are recorded in the PR description and GitHub checks; the manifest records required CI gates separately from local evidence. Earlier runtime commit `2bc156d` passed embedded Python 3.11–3.14, MySQL/PostgreSQL/Redis compatibility and certification checks; the 3.14 embedded job had 94.75% combined coverage. That receipt does not validate this new source. Actual GitHub full-service CI and the unchanged 90% coverage gate must qualify the current head. The frontend security/base updates are handled separately by the maintainer; no scan threshold, ignore list or CI assertion is weakened here. Rebase is deferred until those main updates are ready, as requested. No merge is authorized.

## Workload and interpretation limits

Saved V2 `text-embedding-3-small` vectors: 1,325 × 1,536D float64; zero new model calls. The 4,000-entry stress case repeats 1,000 real vectors four times under explicit compatible-answer aliases; it is not 4,000 independently embedded prompts. The semantic path uses 13 frozen development queries at threshold 0.8, strict threshold is 0.9691803520567825. Capacity 5,000; seed 20261024; ten exact warmups; 200 measured requests per path per process. Primary TTL is disabled; the finite-TTL sensitivity is separate.

Four native paths: exact hit; read-only populated-scope miss; semantic hit; qualified 70/30 mixed resolution with default-namespace exact hits, unique miss namespaces, zero-delay generation and native admission. This differs from unsafe unpartitioned ID-heavy V2 mixing. Fixture correctness is checked for every result and generation count; it is not proof of general semantic-reuse safety or a cached answer's correctness.

Windows x64, CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4, 8 physical/16 logical CPUs, normal priority and full affinity. OMP/OPENBLAS/MKL limits are one before NumPy import; the loaded OpenBLAS getter reads back one. No affinity, power policy, GC or production BLAS default was changed. Host load is retained per phase; process order alternates and effect sizes use matched pairs. Historical and current-session absolute times are not spliced together. P99 uses 200 observations per process; platform and expiry-storm performance were not independently established. Windows per-thread CPU ticks were too coarse to attribute short numerical kernels; CPU figures are process measurements.

No fresh comparable GPTCache head-to-head was run. Historical 1,000-entry GPTCache P50 targets of 6.001/10.759 ms at 4/16 readers remain reference points, not a current victory claim. Serialized numerical admission, facade validation and embedding conversion remain limits. No Phase 03, SQLite, adaptive threshold or PR #212 changes are included.

## Artifacts and reproduction

Only this narrative and [the provenance manifest](manifest.json) are tracked in this benchmark folder. The root rule is narrowly scoped: `/packages/cache/benchmarks/memory_scheduling/*.csv`. The original `final-summary.csv` and `prototype-summary.csv` remain on disk with their recorded hashes and are untracked. No generated CSV or broken CSV download link is added.

Full raw per-request CSVs, fresh-process JSONs, source variants, frozen plans, assessments, logs and rejected candidates remain in the maintainer-owned `Semantix_Memory_P2_20261025_b3836049` workspace, outside the product repository. Saved V2 vectors and P1 research remain preserved. This PR alone is not independently reproducible without that external evidence; the manifest records source/input/harness/assessment hashes and this access limitation.

Replay with the preserved `corrected_bench.launch(variant, size, readers, rep, queue_only=True, phases=['exact','miss','semantic','mixed'])`, sizes 100/1,000/4,000, readers 1/4/16, five repetitions, alternating baseline/frozen `p2expiry1` source order. The sensitivity adds `ttl_seconds=3600.0` at 1,000 entries. Verify source and vector hashes first, use the preserved environment and network guard, and generate fresh IDs/manifests rather than overwriting any existing evidence. `completion_final.py` records the exact controller and `completion_assess.py` verifies all job/namespace/label signatures, generation counts, source hashes, task drainage and stderr before applying the frozen criteria.
