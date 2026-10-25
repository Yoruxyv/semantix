# SQLite search: bounded reusable snapshots

**Selection: publish the immutable single-namespace snapshot and transaction-qualified validation cache.** The fixed matched comparison meets the predefined public-latency/throughput benefit gates, with no repeated material timing or CPU regression under the declared rules. All measured answers are correct. Required current-head GitHub checks remain a separate publication gate recorded in the PR description; this report does not authorize merging.

## Runtime and attribution

Baseline main is `d66973ea0958ac8ece0b364975d1ce357acc26f3`. Only the SQLite database helper and facade runtime change; the worker, float64 numerical kernel, migrations, dependency pins, exports and MemoryStore remain byte-identical to baseline.

Separate baseline diagnostics at 1,000 saved 1,536-dimensional vectors measured about 90.2 ms mean serial exact-hit latency. Inclusive authority checks took 48.2 ms, of which the binding metadata SQL took 38.7 ms; vector decoding took 12.8 ms, vector cursor fetches 11.4 ms, row norms 4.0 ms and cosine scoring 0.54 ms. These are nested spans, so they must not be added as independent costs. SQL elapsed time includes SQLite/page/cursor/Python work; it does not identify physical disk I/O. Four/sixteen-reader queueing amplified this service cost.

One worker-owned immutable C-contiguous float64 matrix and ordered key/revision tuple are retained for one populated namespace. The same connection compares `PRAGMA data_version` and `total_changes` inside the existing transaction. A changed token requires the full existing bounded metadata validation and discards the matrix. Schema markers/shape and the binding header still receive checks. Native content mutations explicitly invalidate. Only a successfully committed, exactly-two-row hit/LRU update with unchanged external data version may advance the cached token.

The snapshot expires at its earliest included TTL deadline or on a clock earlier than capture. Every selected winner is still read from SQLite by binding/namespace/key/revision/live TTL, decoded, and atomically confirmed by the facade. A reused snapshot does not prove answer correctness. The original full float64 kernel and tie ordering are unchanged.

The revision ledger alone was rejected as an invalidation design: native delete/clear leave it unchanged. A persistent index, schema migration, multiple namespace cache, alternative numerical kernel and worker-concurrency redesign were unnecessary for this measured improvement. There was one implemented coherent prototype, first screened in 12 fresh processes and then frozen for the final comparison.

Selected-source diagnostics confirm that warm requests perform no full binding metadata query, candidate vector decode or vector fetch. The instrumented serial exact mean was 11.71 ms: authority checks 0.30 ms, unchanged row norms 4.08 ms, scoring 0.51 ms, facade embedding 1.03 ms and hit recording 1.46 ms. Spans overlap and this instrumented mean is excluded from final timing comparisons.

## Fixed comparison

72 fresh sequential processes / 36 matched pairs / 36,000 measured requests, plus 216 separate cold reads. Native baseline-created closed seed databases are integrity-checked and copied identically before each trial. Each source performs three initial public hits, followed by 100 exact, semantic, miss, store-read-only and mixed requests. Cells rotate and sources alternate in the smaller cells. The interaction of cell rotation and source parity left each 4,000-entry primary cell in the same within-cell source order across its three pairs. One predeclared reverse-order block below qualifies that specific confound; the original observations remain unchanged. No final timing sample or adverse observation is excluded. Test/build/profile jobs were idle during timing. Both sources include the same lightweight semaphore-admission timing wrapper; detailed SQL/method instrumentation is disabled in final trials.

Primary dimensions are the saved real 1,536D float64 vectors. There are three matched repetitions for each of 100/1,000/4,000 entries × 1/4/16 readers. The 384D stress data are explicit slices and have one pair per cell, so they are exploratory. 4,000 entries are four compatible-answer aliases of 1,000 saved vectors, not 4,000 independently embedded strings. Mixed is native resolve with 70% exact hits and 30% unique miss namespaces, a zero-delay generator and real admissions; it is not the unsafe unpartitioned V2 ID-heavy workload.

Both sources use capacity 5,000, no TTL for timing, the same frozen seed/order/namespaces, strict threshold 0.9691803520567825, semantic threshold 0.8 and 13 frozen known-safe paraphrases. No threshold tuning, replacement embeddings, external providers or FAISS occur. Correct results in this workload are not independent semantic-safety validation.

Predefined benefit: >=30% lower paired-median public-hit P50 and >=30% higher throughput at 1,000/4,000 entries with 4/16 readers, improving in >=2/3 primary pairs; >=20 ms serial saving at 1,000 entries. Block repeated P95/P99 >10% and >0.5 ms, P50 >5% and >0.2 ms, or CPU/request >15%, in >=2/3 primary pairs. All such adverse observations remain in the manifest. A single 384D pair cannot establish repeatability.

Values below are medians of process measurements. Effects are medians of matched pair percentages, which can differ from ratios of column medians. Latency triplets are P50/P95/P99 milliseconds. P99 has only 100 observations per process and does not certify a long-running SLO.

## Primary public hits

| Entries | Readers | Path | Baseline P50/P95/P99 ms | Snapshot P50/P95/P99 ms | Requests/s baseline → snapshot | Paired P50 / P99 change |
|---:|---:|---|---|---|---|---|
| 100 | 1 | exact | 10.811/11.904/12.258 | 6.677/7.539/7.712 | 92.100 → 148.447 | -41.1% / -27.5% |
| 100 | 1 | semantic | 10.112/11.303/13.926 | 5.924/6.846/7.982 | 97.553 → 164.810 | -40.7% / -37.0% |
| 100 | 4 | exact | 40.659/45.416/57.118 | 24.292/26.623/28.056 | 98.149 → 162.960 | -40.7% / -49.4% |
| 100 | 4 | semantic | 41.203/44.557/49.618 | 23.913/28.757/34.718 | 96.551 → 157.994 | -42.3% / -33.6% |
| 100 | 16 | exact | 162.359/175.896/177.543 | 106.120/120.946/123.892 | 95.159 → 149.303 | -38.3% / -34.5% |
| 100 | 16 | semantic | 174.226/189.478/190.693 | 98.516/104.939/107.038 | 90.024 → 160.183 | -44.4% / -39.9% |
| 1000 | 1 | exact | 83.337/91.180/94.120 | 10.449/11.725/17.713 | 11.842 → 94.739 | -87.5% / -81.2% |
| 1000 | 1 | semantic | 83.906/88.491/90.778 | 10.377/12.477/14.634 | 11.837 → 91.987 | -87.7% / -84.0% |
| 1000 | 4 | exact | 331.573/339.069/349.128 | 41.223/43.483/44.843 | 12.036 → 96.530 | -87.5% / -87.0% |
| 1000 | 4 | semantic | 336.428/379.212/384.745 | 42.322/51.106/56.340 | 11.623 → 91.332 | -87.8% / -84.6% |
| 1000 | 16 | exact | 1,317.841/1,365.996/1,367.173 | 165.303/184.264/186.517 | 12.060 → 93.305 | -87.4% / -86.0% |
| 1000 | 16 | semantic | 1,338.987/1,402.475/1,402.832 | 159.520/174.122/175.807 | 11.917 → 98.620 | -87.9% / -87.0% |
| 4000 | 1 | exact | 316.528/324.833/347.130 | 23.753/26.925/28.601 | 3.153 → 41.105 | -92.4% / -92.0% |
| 4000 | 1 | semantic | 320.274/340.062/357.347 | 23.356/26.590/30.420 | 3.109 → 41.423 | -92.7% / -91.6% |
| 4000 | 4 | exact | 1,252.145/1,330.325/1,382.663 | 93.172/103.287/104.653 | 3.150 → 42.166 | -92.6% / -92.4% |
| 4000 | 4 | semantic | 1,268.687/1,345.065/1,364.447 | 93.016/104.262/137.171 | 3.121 → 40.602 | -92.7% / -89.6% |
| 4000 | 16 | exact | 5,049.047/5,215.784/5,224.411 | 373.434/395.861/396.184 | 3.162 → 41.893 | -92.7% / -92.7% |
| 4000 | 16 | semantic | 5,136.381/5,255.163/5,268.052 | 381.200/418.628/430.996 | 3.120 → 41.090 | -92.8% / -92.1% |

## CPU, resident memory and admission queue

CPU is process CPU milliseconds per request over a 100-request batch. Windows accounting granularity limits precision. RSS is end-of-path MiB, not a fixed process budget. Queue measures semaphore admission only, excluding executor/event-loop scheduling. The selected implementation still has one numerical/SQLite worker.

| Entries | Readers | Path | CPU ms/request baseline → snapshot | RSS MiB baseline → snapshot | Queue P50/P95/P99 ms baseline → snapshot |
|---:|---:|---|---|---|---|
| 100 | 1 | exact | 9.688 → 6.250 | 57.668 → 57.496 | 0.006/0.007/0.011 → 0.005/0.007/0.008 |
| 100 | 1 | semantic | 9.688 → 5.312 | 58.520 → 58.398 | 0.005/0.007/0.010 → 0.005/0.007/0.009 |
| 100 | 4 | exact | 10.156 → 5.469 | 56.633 → 57.727 | 27.145/29.719/42.635 → 14.918/16.903/18.841 |
| 100 | 4 | semantic | 9.844 → 6.094 | 59.059 → 58.996 | 27.367/31.140/34.866 → 14.632/16.889/23.037 |
| 100 | 16 | exact | 9.688 → 5.938 | 57.875 → 58.785 | 149.213/161.479/162.633 → 95.854/109.811/110.976 |
| 100 | 16 | semantic | 9.688 → 5.625 | 58.707 → 60.293 | 159.767/174.484/174.963 → 89.232/96.404/96.473 |
| 1000 | 1 | exact | 83.594 → 9.844 | 66.227 → 76.586 | 0.007/0.008/0.011 → 0.006/0.007/0.009 |
| 1000 | 1 | semantic | 82.812 → 9.844 | 67.672 → 77.496 | 0.007/0.008/0.011 → 0.006/0.008/0.009 |
| 1000 | 4 | exact | 82.656 → 10.000 | 65.508 → 76.941 | 244.801/252.424/259.005 → 27.405/29.090/30.909 |
| 1000 | 4 | semantic | 84.062 → 10.156 | 68.168 → 77.961 | 248.818/281.381/285.656 → 28.469/33.988/42.517 |
| 1000 | 16 | exact | 81.719 → 9.844 | 67.742 → 77.895 | 1,231.780/1,279.179/1,280.092 → 151.824/169.572/171.497 |
| 1000 | 16 | semantic | 82.344 → 9.844 | 69.426 → 79.312 | 1,250.785/1,311.714/1,315.924 → 146.273/160.616/162.330 |
| 4000 | 1 | exact | 314.844 → 23.906 | 67.961 → 113.922 | 0.007/0.009/0.010 → 0.006/0.008/0.010 |
| 4000 | 1 | semantic | 318.750 → 23.594 | 70.117 → 114.824 | 0.007/0.010/0.012 → 0.006/0.007/0.010 |
| 4000 | 4 | exact | 315.156 → 23.438 | 69.836 → 114.113 | 935.210/1,002.614/1,024.878 → 66.602/73.359/75.780 |
| 4000 | 4 | semantic | 317.500 → 22.969 | 70.988 → 115.145 | 947.419/1,008.109/1,021.302 → 66.513/74.864/108.294 |
| 4000 | 16 | exact | 313.594 → 23.594 | 70.633 → 115.324 | 4,730.795/4,872.573/4,903.293 → 346.853/367.725/368.438 |
| 4000 | 16 | semantic | 318.594 → 24.219 | 72.457 → 116.516 | 4,815.740/4,922.042/4,940.975 → 354.255/392.233/404.551 |

## Primary misses, read-only and mixed operations

Read-only calls the native store with a precomputed query and performs no hit write. Misses use the public cache and strict threshold. Mixed includes generation/miss admission costs. Each path has the same three paired repetitions. Full CPU/RSS/queue/host/file measurements for every row are retained in the JSON manifest.

| Entries | Readers | Path | Baseline P50/P95/P99 ms | Snapshot P50/P95/P99 ms | Requests/s baseline → snapshot |
|---:|---:|---|---|---|---|
| 100 | 1 | miss | 8.452/9.908/10.057 | 4.804/5.164/5.814 | 115.626 → 206.033 |
| 100 | 1 | readonly | 5.663/6.361/6.664 | 2.153/2.467/2.527 | 173.467 → 461.455 |
| 100 | 1 | mixed | 10.878/12.640/13.010 | 6.116/9.626/10.299 | 96.425 → 147.087 |
| 100 | 4 | miss | 34.840/38.204/39.199 | 19.467/20.547/21.189 | 114.292 → 203.251 |
| 100 | 4 | readonly | 23.310/24.700/24.885 | 8.345/9.278/9.829 | 169.609 → 474.529 |
| 100 | 4 | mixed | 39.384/44.638/46.345 | 27.609/32.549/33.483 | 102.782 → 145.365 |
| 100 | 16 | miss | 140.155/144.581/146.694 | 76.344/80.726/80.931 | 113.176 → 206.468 |
| 100 | 16 | readonly | 93.043/98.100/98.260 | 34.308/35.758/36.459 | 169.712 → 461.412 |
| 100 | 16 | mixed | 163.963/180.935/181.954 | 103.941/115.610/124.927 | 98.626 → 150.365 |
| 1000 | 1 | miss | 66.026/71.255/76.066 | 8.784/9.242/9.782 | 14.732 → 113.474 |
| 1000 | 1 | readonly | 64.260/66.738/68.889 | 6.248/7.172/7.372 | 15.508 → 157.153 |
| 1000 | 1 | mixed | 84.836/92.251/94.387 | 10.698/53.490/55.992 | 13.905 → 49.539 |
| 1000 | 4 | miss | 266.030/277.132/286.575 | 37.387/41.556/42.294 | 14.903 → 105.851 |
| 1000 | 4 | readonly | 259.552/271.064/284.366 | 26.356/27.595/29.286 | 15.318 → 153.033 |
| 1000 | 4 | mixed | 290.484/352.373/356.139 | 79.181/103.406/113.657 | 13.945 → 53.597 |
| 1000 | 16 | miss | 1,048.972/1,130.495/1,135.330 | 141.472/144.962/145.893 | 14.983 → 112.981 |
| 1000 | 16 | readonly | 1,014.434/1,038.622/1,047.006 | 98.004/100.008/100.102 | 15.645 → 162.283 |
| 1000 | 16 | mixed | 1,146.743/1,267.446/1,268.229 | 243.494/330.201/346.306 | 14.077 → 63.996 |
| 4000 | 1 | miss | 255.876/275.135/294.190 | 22.092/22.858/23.235 | 3.893 → 45.149 |
| 4000 | 1 | readonly | 251.920/270.769/281.607 | 19.489/20.887/21.360 | 3.955 → 51.210 |
| 4000 | 1 | mixed | 320.979/337.293/343.093 | 23.593/192.591/204.086 | 3.742 → 16.641 |
| 4000 | 4 | miss | 1,014.375/1,075.248/1,104.586 | 90.856/102.233/105.929 | 3.916 → 43.382 |
| 4000 | 4 | readonly | 1,005.534/1,156.277/1,186.553 | 77.044/78.492/79.077 | 3.900 → 51.881 |
| 4000 | 4 | mixed | 1,122.071/1,346.142/1,415.398 | 242.826/336.688/367.612 | 3.607 → 17.769 |
| 4000 | 16 | miss | 4,114.936/4,542.724/4,569.055 | 369.540/412.727/415.660 | 3.769 → 42.614 |
| 4000 | 16 | readonly | 4,231.903/4,401.695/4,415.995 | 314.889/332.560/334.232 | 3.770 → 50.096 |
| 4000 | 16 | mixed | 4,322.930/4,940.691/4,946.134 | 717.333/1,090.141/1,164.516 | 3.667 → 21.459 |

## Reverse-order confirmation

A harness ordering flaw was identified while the unchanged fixed run was in progress. Before this extra measurement, the plan fixed exactly three reversed pairs at 4,000 real 1,536D entries, readers 1/4/16, exact/semantic only: six fresh processes, 1,200 requests and 18 separate cold reads. Each reversed cell/path must retain >=30%P50 reduction and >=30%throughput improvement, with no >10% and >0.5ms adverse P95/P99, CPU/request >15%, error or resource failure. All six path comparisons pass. These observations are reported separately and are not selectively pooled into primary medians. Total final/confirmation evidence is 78 processes / 37,200 requests plus 234 cold reads.

| Readers | Path | Reverse baseline P50/P95/P99 ms | Reverse snapshot P50/P95/P99 ms | Requests/s baseline → snapshot |
|---:|---|---|---|---|
| 1 | exact | 315.029/323.816/329.973 | 23.729/24.443/25.053 | 3.175 → 42.094 |
| 1 | semantic | 322.174/346.851/365.345 | 23.658/25.699/30.790 | 3.066 → 41.212 |
| 4 | exact | 1,283.397/1,334.341/1,364.295 | 93.959/97.539/99.436 | 3.098 → 42.454 |
| 4 | semantic | 1,297.357/1,330.222/1,422.721 | 93.059/97.897/137.940 | 3.067 → 42.116 |
| 16 | exact | 5,001.454/5,093.248/5,095.022 | 373.551/382.144/386.776 | 3.172 → 42.662 |
| 16 | semantic | 5,386.715/5,483.082/5,505.562 | 379.039/421.080/432.435 | 2.979 → 41.547 |

## Cold, rebuild and writer costs

Cold means a fresh connection/process-local snapshot; the host OS file cache was not flushed. Imports, saved-fixture loading and the identical seed copy are outside connect/lookup timing. Native seed population is reported below; full interpreter startup is not separately benchmarked. These costs are excluded from warm percentiles and disclosed separately. Each primary entry-size row aggregates nine fresh processes/source.

| Entries | Connect ms baseline → snapshot | First public hit ms baseline → snapshot | Second hit ms baseline → snapshot | Baseline native seed population s | Closed seed MiB |
|---:|---|---|---|---:|---:|
| 100 | 56.775 → 56.824 | 13.306 → 12.830 | 10.876 → 6.277 | 0.58 | 1.33 |
| 1000 | 76.972 → 73.951 | 86.188 → 56.466 | 83.212 → 10.949 | 11.11 | 12.89 |
| 4000 | 124.648 → 123.638 | 318.988 → 190.750 | 310.500 → 24.445 | 145.44 | 51.36 |

A separate 1,000-entry/one-reader diagnostic uses 20 native same-key replacements, each followed by a public rebuild hit, then baseline-source independent-process replacement/hit commits, populated namespace switches, and a clean close/reopen. This quantifies invalidation costs rather than hiding them in warm setup. Diagnostic repetitions are bounded and do not establish workload-wide writer tail guarantees.

| Diagnostic | Baseline ms | Snapshot ms |
|---|---:|---:|
| Native replacement P50/P95/P99 | 20.542/20.903/20.952 | 5.749/5.988/6.035 |
| First public hit after replacement P50/P95/P99 | 82.658/84.351/84.667 | 51.291/52.330/52.441 |
| Clean reconnect | 23.454 | 23.013 |
| First hit after clean restart | 85.438 | 53.090 |
| First hit after external baseline replacement | 86.748 | 55.901 |
| First hit after external baseline hit-only metadata commit | 87.657 | 57.295 |

Every diagnostic retained exactly 1,001 independently verified persisted rows after the extra namespace insertion. All retired snapshot weakrefs were released; one retained matrix was 11.719 MiB. Across 20 reloads, RSS moved from 73.652 to 75.094 MiB; post-close RSS was 53.059 MiB. Native allocators may retain freed pages, so RSS release is not identical to object release. Handles before/warm/after were (165, 174, 172).

All final trial workers/connections/tasks drain; their closed trial databases alone are removed after integrity/count receipts. Maximum observed process peak was 173.012 MiB, below the 1.5 GiB child bound. The static retained vector limit remains 64 MiB plus bounded key/revision metadata; the unchanged kernel also allocates bounded numerical temporaries. Full raw handles, file bytes and namespace-switch observations are in the preserved receipts and manifest.

## Derived 384D stress comparison

One matched pair per cell; these results are exploratory, not three-repetition confirmation. The primary acceptance decision uses 1,536D. All original answers and expected hit/miss decisions are still checked.

| Entries | Readers | Path | Baseline P50/P95/P99 ms | Snapshot P50/P95/P99 ms | Requests/s baseline → snapshot |
|---:|---:|---|---|---|---|
| 100 | 1 | exact | 5.530/6.115/6.525 | 2.617/4.301/6.244 | 178.539 → 352.348 |
| 100 | 1 | semantic | 5.470/6.253/7.131 | 2.592/3.591/6.218 | 178.192 → 362.268 |
| 100 | 1 | miss | 3.924/4.354/4.520 | 1.574/1.816/1.870 | 253.147 → 626.489 |
| 100 | 1 | readonly | 3.194/3.621/3.777 | 0.869/1.042/1.163 | 310.484 → 1,115.129 |
| 100 | 1 | mixed | 5.799/6.484/6.972 | 2.803/4.902/5.713 | 182.497 → 309.142 |
| 100 | 4 | exact | 21.620/23.565/24.090 | 10.669/12.699/16.738 | 181.792 → 359.884 |
| 100 | 4 | semantic | 22.567/23.727/23.896 | 10.955/12.189/12.347 | 177.276 → 358.506 |
| 100 | 4 | miss | 16.090/17.274/17.492 | 6.483/7.115/7.243 | 247.102 → 610.392 |
| 100 | 4 | readonly | 12.398/13.206/13.305 | 3.589/4.247/4.554 | 320.269 → 1,096.662 |
| 100 | 4 | mixed | 21.869/27.780/30.379 | 13.292/16.347/20.028 | 180.285 → 299.450 |
| 100 | 16 | exact | 86.746/89.697/89.897 | 44.417/46.723/47.003 | 182.502 → 354.735 |
| 100 | 16 | semantic | 92.868/97.881/98.337 | 43.401/45.254/45.406 | 169.729 → 360.683 |
| 100 | 16 | miss | 63.256/65.660/67.624 | 25.500/27.398/27.546 | 248.061 → 619.423 |
| 100 | 16 | readonly | 49.999/51.621/51.958 | 13.699/14.598/14.878 | 316.620 → 1,149.287 |
| 100 | 16 | mixed | 86.987/94.118/96.321 | 48.835/55.498/56.326 | 185.481 → 317.806 |
| 1000 | 1 | exact | 31.391/34.733/37.274 | 4.097/4.806/6.705 | 31.374 → 239.285 |
| 1000 | 1 | semantic | 31.421/33.043/33.909 | 4.817/7.308/8.005 | 31.542 → 187.343 |
| 1000 | 1 | miss | 25.228/28.028/28.671 | 2.901/3.342/3.409 | 39.177 → 346.945 |
| 1000 | 1 | readonly | 25.321/32.901/44.285 | 1.610/2.126/2.158 | 38.297 → 596.710 |
| 1000 | 1 | mixed | 31.227/33.118/33.695 | 5.387/29.973/32.116 | 37.714 → 97.895 |
| 1000 | 4 | exact | 126.441/132.597/133.170 | 14.765/15.968/16.756 | 31.469 → 267.175 |
| 1000 | 4 | semantic | 126.230/131.173/134.878 | 14.734/19.373/23.471 | 31.516 → 260.847 |
| 1000 | 4 | miss | 101.527/105.818/112.644 | 9.891/10.787/11.341 | 39.202 → 399.328 |
| 1000 | 4 | readonly | 94.702/98.252/99.180 | 6.748/7.841/8.705 | 42.043 → 576.795 |
| 1000 | 4 | mixed | 105.663/134.695/135.855 | 32.148/42.035/48.411 | 37.727 → 133.827 |
| 1000 | 16 | exact | 491.274/502.139/502.621 | 59.657/61.843/62.711 | 32.398 → 267.746 |
| 1000 | 16 | semantic | 492.225/519.806/521.515 | 57.184/61.454/61.808 | 31.996 → 275.134 |
| 1000 | 16 | miss | 398.620/402.143/402.843 | 40.114/44.824/45.290 | 40.210 → 389.649 |
| 1000 | 16 | readonly | 375.609/380.632/381.334 | 27.303/28.930/29.200 | 42.458 → 576.291 |
| 1000 | 16 | mixed | 408.641/482.891/483.495 | 88.273/120.838/127.459 | 38.090 → 174.355 |
| 4000 | 1 | exact | 186.704/197.534/208.779 | 7.873/9.431/10.718 | 5.324 → 125.666 |
| 4000 | 1 | semantic | 189.151/201.693/206.617 | 7.681/8.338/10.122 | 5.246 → 128.352 |
| 4000 | 1 | miss | 159.147/168.705/174.109 | 6.283/6.939/7.445 | 6.257 → 158.062 |
| 4000 | 1 | readonly | 155.249/163.634/168.757 | 5.385/6.044/7.070 | 6.416 → 182.539 |
| 4000 | 1 | mixed | 189.623/205.245/213.943 | 7.607/121.331/122.142 | 6.305 → 29.732 |
| 4000 | 4 | exact | 778.302/848.747/883.494 | 30.145/31.739/32.691 | 5.063 → 133.123 |
| 4000 | 4 | semantic | 785.606/824.398/831.904 | 29.755/32.725/33.750 | 5.070 → 132.942 |
| 4000 | 4 | miss | 637.268/665.903/677.865 | 25.236/27.844/30.926 | 6.227 → 156.924 |
| 4000 | 4 | readonly | 627.541/742.485/834.865 | 21.699/23.055/24.594 | 6.191 → 183.264 |
| 4000 | 4 | mixed | 641.924/789.537/797.896 | 144.865/210.008/222.241 | 6.346 → 30.826 |
| 4000 | 16 | exact | 2,964.184/2,999.229/3,001.297 | 115.658/126.548/126.793 | 5.383 → 136.432 |
| 4000 | 16 | semantic | 2,997.916/3,086.873/3,088.249 | 119.349/124.050/124.215 | 5.301 → 132.474 |
| 4000 | 16 | miss | 2,455.508/2,524.479/2,527.956 | 95.909/99.103/100.223 | 6.500 → 164.515 |
| 4000 | 16 | readonly | 2,485.319/2,559.179/2,567.434 | 81.031/82.069/82.375 | 6.427 → 195.928 |
| 4000 | 16 | mixed | 2,516.771/2,893.019/2,893.999 | 318.580/497.549/532.824 | 6.346 → 47.415 |

## Correctness and compatibility evidence

- Full offline cache run: 1,605 passed, 80 skipped, 401 service-marked cases deselected. All 225 SQLite cases pass with zero skips on CPython 3.11.15 and 3.14.6, linked SQLite 3.53.1. Skips comprise 76 unavailable live Redis cases and four pre-existing generic backend capability cases. No skipped/live-service gate is reported as passing.
- The 33 new snapshot cases cover warmed reuse plus real hit/LRU increments, namespace/eviction bounds, insert/replace/delete/clear, independent-process commit fences, external rollback/commit, unexpected local DML/rollback, exact two-change retention, corruption/schema failures, inclusive TTL and backward clocks, partial build failure, busy close and eventual release after cancelled/timed-out cleanup.
- Existing numerical, cancellation, timeout, commit-uncertainty, partial startup, schema ownership, inspection, revision and lifecycle regressions remain unchanged. The shared numerical kernel, worker, migration bytes and dependency pins are unchanged.
- Server parity: 47 passed, 10 service cases deselected. Ruff check/format, strict configured mypy, Pyright 1.1.414, 50 backport certification unit tests, source/sdist/wheel archive checks, Twine and a clean installed-wheel/core-only SQLite consumer pass. The wheel consumer also passes against cached Pydantic 2.14.1; timed trials use the preserved 2.13.4 environment.
- Offline package branch coverage is 68% because external backend implementations are not exercised. The SQLite database helper is 94%, facade 92%, worker 93%, format 92%. This is partial evidence: the unchanged 90% combined package gate requires full GitHub MySQL/PostgreSQL/Redis jobs.
- CI selection now includes the new snapshot module on Windows managed Python 3.11–3.14, the minimum Linux runtime and both separately verified 3.44.6/3.50.7 backports. Backport certification also now explicitly includes existing inspection/cleanup suites. Passing those current-head jobs is required; local 3.53.1 probes alone do not certify the older libraries.

## Provenance and reproduction

See [manifest.json](manifest.json) for source/data/plan/harness hashes, every final pair and cell summary, cold observations, writer/resource diagnostics and raw-evidence digests. The original research workspace is `C:\Users\ASUS\Downloads\Semantix_SQLite_P4_20261025_6a41de92`. Its `results/`, `seeds/`, `variants/` and scripts preserve all raw observations and frozen sources outside both product repositories. CSVs are untracked; the ignore rule is scoped to this benchmark directory.

Exact local replay uses the preserved V2 Python/NumPy environment, saved corpus/vector manifests, baseline snapshot, identical closed seeds and `bench.py` with the arguments recorded in each JSON receipt. `final.py` defines source/cell rotation and `assess_final.py` applies the predeclared thresholds to every pair. Scripts and data are not bundled into this public product diff: independently reproducing these exact numbers requires access to that preserved workspace. Absolute local paths, Windows BLAS DLL readback and CPU/OS conditions limit portability. No raw-vector availability or independent replication is implied.

The timed runtime is CPython 3.14.6, NumPy 2.4.6, Pydantic 2.13.4, SQLite 3.53.1, Windows x64, eight physical/sixteen logical CPUs, with one OpenBLAS thread verified from the loaded DLL. WAL, synchronous FULL, 8 MiB SQLite page cache, mmap disabled, worker admission 32 and capacity/TTL policy are unchanged. Host busy values are retained; there is no host-load exclusion or posthoc timing adjustment. Failed diagnostic harness preflights remain preserved and are not successful final trials.

SQLite documents [connection-local data-version comparison](https://www.sqlite.org/pragma.html#pragma_data_version) and [WAL snapshot isolation](https://www.sqlite.org/isolation.html). Local probes plus deterministic transaction-fence tests check their interaction for this design. Restoring/replacing a live file remains unsupported; restore requires a new embedding identity as before.

## Remaining limits and competitor gap

The largest remaining costs are the unchanged full float64 row norms/search, facade embedding/validation, serialized worker admission and durable hit writes. Every other-connection commit, including a hit-only commit or another binding, conservatively invalidates the index. Frequent mutations and alternating populated namespaces reduce warm reuse; initial population remains a full native baseline cost. No persistent or independently durable index is created.

The historical V2 GPTCache SQLite+FAISS P50 values are 5.579/6.107/10.795 ms at 1/4/16 readers, using its pinned float32 L2 index and different durability/validation architecture. The table below is a historical reference, not a newly matched competition run or a victory claim. The overall performance target remains open.

| Readers | Selected 1,000-entry exact P50 ms | Historical GPTCache P50 ms | Reference ratio |
|---:|---:|---:|---:|
| 1 | 10.449 | 5.579 | 1.87x |
| 4 | 41.223 | 6.107 | 6.75x |
| 16 | 165.303 | 10.795 | 15.31x |

Stop scope: no MemoryStore/numerical-kernel changes, worker-concurrency redesign, provider calls, new dependency or next-phase work. Human review and current-head CI remain required; no automatic merge.
