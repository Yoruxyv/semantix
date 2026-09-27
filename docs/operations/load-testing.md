# Load testing and runtime observability

Semantix includes isolated k6 workloads and a process-local JSON metrics
endpoint. Run load tests only against a local or otherwise disposable instance.

## Safe test configuration

Mock providers are the recommended default for load testing because they are
deterministic, require no network, and cannot incur provider charges:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384

CACHE_BACKEND=memory
MAX_CACHE_SIZE=500
CACHE_TTL_SECONDS=3600
RATE_LIMIT=100000/minute
PROMPT_TYPO_CORRECTION_ENABLED=false
```

Recreate the backend after changing `backend/.env`:

```powershell
docker compose up --build --force-recreate -d backend frontend
```

Use pgvector only when the storage backend itself is under test. Do not point
the load test at production data. The near-capacity scenario can evict entries
across namespaces because cache capacity applies to the active embedding
space, not to one namespace.

Every run requires:

```text
LOAD_ACKNOWLEDGE_PROVIDER_CALLS=true
```

This acknowledgement is required even with mock providers so changing the
provider configuration cannot silently create billable traffic.

## Scenarios

| `SCENARIO` | Workload | What it proves |
|---|---|---|
| `repeated-identical` | Five VUs repeat one prompt | A warm cache reduces provider calls |
| `mixed-hits-misses` | Repeated and distinct prompts | Hit/miss counters and mixed latency remain coherent |
| `concurrent-identical-misses` | Twenty VUs submit one cold prompt once | In-flight request coalescing limits duplicate generation |
| `high-cardinality` | Unique prompts at a fixed arrival rate | Miss-heavy traffic remains stable |
| `threshold-changes` | Traffic runs while one VU alternates thresholds | Threshold updates remain safe during query traffic |
| `near-capacity` | Writes `MAX_CACHE_SIZE + 25` unique prompts | Cache size stays bounded and evictions are recorded |

The threshold scenario requires
`LOAD_ALLOW_THRESHOLD_CHANGES=true`. It records the current threshold and
restores it during teardown.

The capacity scenario requires `LOAD_ALLOW_CACHE_EVICTION=true`. Use it only
against an isolated cache because evicted entries cannot be restored.

Mock embeddings are not semantically meaningful. They test concurrency,
instrumentation, limits, and endpoint stability. Use a real embedding provider
only when evaluating semantic threshold quality, after reviewing its cost,
rate limits, and data-handling requirements.

## Run with an installed k6

From the repository root in PowerShell:

```powershell
$env:BASE_URL = "http://localhost:8000"
$env:LOAD_ACKNOWLEDGE_PROVIDER_CALLS = "true"
$env:SCENARIO = "repeated-identical"
k6 run .\ops\load-testing\semantix.js
```

Change `SCENARIO` to run the other workloads. For the protected scenarios:

```powershell
$env:SCENARIO = "threshold-changes"
$env:LOAD_ALLOW_THRESHOLD_CHANGES = "true"
k6 run .\ops\load-testing\semantix.js
```

```powershell
$env:SCENARIO = "near-capacity"
$env:CACHE_CAPACITY = "500"
$env:LOAD_ALLOW_CACHE_EVICTION = "true"
k6 run .\ops\load-testing\semantix.js
```

`CACHE_CAPACITY` must match `MAX_CACHE_SIZE`. `P95_LIMIT_MS` controls the k6
P95 threshold and defaults to `5000`.

## Run k6 through Docker

Start Semantix first so the `semantix_default` network exists. Then run:

```powershell
docker run --rm `
  --network semantix_default `
  --volume "${PWD}\ops\load-testing:/scripts:ro" `
  --env BASE_URL=http://backend:8000 `
  --env LOAD_ACKNOWLEDGE_PROVIDER_CALLS=true `
  --env SCENARIO=repeated-identical `
  grafana/k6 run /scripts/semantix.js
```

Docker downloads the k6 image on the first run. The bind mount is read-only.

## Runtime metrics

The backend exposes:

```text
GET /api/v1/metrics
```

The built-in local load-test workflow assumes authentication is disabled. In
a token-authenticated deployment, this process-wide endpoint requires a global
administrator token; namespace-scoped principals receive `403 Forbidden`.

Inspect it from PowerShell in local development:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/metrics |
  ConvertTo-Json
```

For a token-authenticated deployment:

```powershell
$Headers = @{ Authorization = "Bearer $GlobalAdminToken" }
Invoke-RestMethod http://localhost:8000/api/v1/metrics -Headers $Headers |
  ConvertTo-Json
```

Response fields:

| Field | Meaning |
|---|---|
| `request_count` | Interactive query requests started in this process |
| `error_count` | Query workflows that completed with an error |
| `cache_hits` | Actual cache lookups served from cache |
| `cache_misses` | Actual cache lookups that missed |
| `provider_calls` | Generation attempts, including failed attempts |
| `in_flight_coalesced_requests` | Followers currently sharing leader work |
| `average_latency_ms` | Mean completed-query latency since startup |
| `p95_latency_ms` | Nearest-rank P95 from the bounded recent sample |
| `latency_sample_size` | Samples currently retained for P95 |
| `cache_size` | Current entries in the active embedding space |
| `evictions` | Entries removed by the configured size limit |
| `expirations` | Entries removed after TTL expiry |
| `uptime_seconds` | Age of the metrics collector |
| `observed_at` | UTC snapshot timestamp |

Average and P95 latency are `null` before a query completes. The P95 window is
bounded to 2,048 completed requests. Counters reset when the backend process
restarts and are not stored in pgvector.

Validation errors and rate-limit rejections happen before `QueryService` and
are therefore not included in `request_count` or `error_count`. HTTP-level
errors remain visible in k6's `http_req_failed` metric.

## Reading results

k6 checks require:

- more than 99% successful checks;
- less than 1% failed HTTP requests;
- HTTP P95 below `P95_LIMIT_MS`.

The script also reports:

- `semantix_cache_hits`;
- `semantix_cache_misses`;
- `semantix_provider_calls`;
- `semantix_query_errors`;
- `semantix_query_latency_ms`.

The k6 hit and miss counters describe the decision returned to each caller.
The backend counters describe actual cache lookups. Coalesced followers can
therefore receive a miss response without performing another lookup or
provider call. During concurrent traffic, use the backend `cache_misses` and
`provider_calls` counters to measure work avoided by coalescing.

At teardown, k6 prints the backend metrics snapshot and clears its generated
namespace. Compare both views:

- repeated traffic should have substantially more hits than provider calls;
- concurrent identical misses should normally produce one provider call;
- high-cardinality traffic should be miss-heavy;
- cache size must not exceed `MAX_CACHE_SIZE`;
- the capacity run should increase evictions;
- the coalesced gauge returns to zero after traffic stops.

Provider speed, model warm-up, hardware, Docker resource limits, database
latency, and network conditions all affect absolute latency. Record the
environment with every performance result rather than treating one local run
as a universal benchmark.

## Capacity baseline on the local Docker host

This section records a **single-machine capacity characterization**, not a production SLO. The tested source was `d7954a55ae338280604aa996976e2d46472236c9` (the commit containing the controlled autoscaling readiness work). The normal development stack was left running. Each measurement used a uniquely named disposable Compose project, PostgreSQL volume, networks, random credentials, and a synthetic test namespace; the runner removed those resources after each topology. No hosted provider was called.

The host was Windows 11 build 26200 on an AMD Ryzen 9 5900HX (16 logical CPUs), with 33.7 GB physical RAM and about 13 GB available during the run. Docker Desktop Engine was 29.6.2 with 16 CPUs and 16.45 GB available to its VM; the Compose services had no explicit CPU or memory limits. The production backend image ran Python 3.14 (soak container image ID `sha256:cdb3ca2058a1cee38ebba7d2a6b482f3c96ccb497763b443e8d9e71af0c8a1bc`); the database image was pinned `pgvector/pgvector:pg17` (`sha256:d2ef61f42ef767baa5a1475393303cc235bcd92febd9d7014eddb48b41f3bad0`), and the gateway used `nginxinc/nginx-unprivileged:1.31.3-alpine` (soak image ID `sha256:4d28fc73c33feb2572c283325bb829fd92534c2e612cb8dd32be54ffc9711684`). The k6 container was v2.1.0 (`sha256:e7eeddf1ce2361df6920d925297f487c0ba549c44be242c6a9c22f28d9b08efa`). The local ignored `ops/load-testing/results/phase13-20260927/environment.json` snapshot contains the exact test settings if retained from the original run.

Both topologies used the production Compose backend, gateway, shared PostgreSQL rate-limit/threshold/session coordination, pgvector cache, token authentication, and mock embedding/generation providers. The only topology difference was one versus two backend replicas in the gateway upstream. Settings were: 384-dimensional mock embeddings, threshold 0.92, cache TTL 3,600 seconds, pool min/max 1/5 **per replica**, `RATE_LIMIT=100000/minute`, and deterministic mock generation delay 50 ms. The elevated rate limit retained the PostgreSQL coordination path while keeping ordinary quota rejection out of the capacity measurement. No connection proxy or third replica was used.

The capacity profile lives in [capacity.js](../../ops/load-testing/capacity.js), with the isolated runner in [phase13.py](../../ops/load-testing/phase13.py). Each VU waits 2, 3, or 4 seconds between requests (mean 3 seconds); 1,000 VUs do not mean 1,000 requests in one millisecond. Every 60-second stage clears the test namespace, prewarms eight repeated prompts, and records k6 JSON, probe/resource/DB telemetry, provider-log counts, and a compact result JSON. The k6 summary includes the short initial VU start and graceful completion period, so these ladder points are exploration measurements rather than pure steady-state SLO samples. The later soak and stabilized repeats provide longer windows. The profiles were:

| Profile | Request construction |
| --- | --- |
| Cache-heavy | 80% from a repeated prompt set, 20% unique |
| Generation-heavy | 10% repeated, 90% unique |
| Mixed-policy | 60% normal, 10% each read-only, refresh, bypass, private, using the public policy flags |
| Cold burst | 50 VUs each submit the same initially cold prompt once, without think time |

Mock embeddings can consider distinct synthetic prompts similar. The profile percentages describe **prompt selection**, while measured hit rates below describe the actual pgvector decisions. The shared cache retained its default 500-entry maximum, so high-cardinality stages also exercised evictions.

Reproduce the original ladder from the repository root in Windows PowerShell, after ensuring Docker Desktop is running:

```powershell
python ops/load-testing/phase13.py `
  --output ops/load-testing/results/phase13-20260927 `
  --topologies 1 2 `
  --profiles cache-heavy generation-heavy mixed-policy `
  --vus 50 100 250 500 1000 --duration 60s
```

Choose a fresh output directory for a new run. The runner stops escalating a profile after a nonzero k6 exit, failed health/readiness sample, more than 1% 5xx/transport failures, or P95 above 5 seconds. It does not turn a degraded stage into a successful stage. Raw ladder results (`summary.json`), per-stage `k6.json`, `result.json`, and `telemetry.jsonl` are written locally under the selected output directory, which Git ignores. k6's custom counters distinguish 4xx, 429, 5xx, transport failures, response hits/misses, and provider responses. Backend `/api/v1/metrics` snapshots are process-local; the runner sums per-replica deltas for comparisons. PostgreSQL `pg_stat_activity` samples capture runtime connections, active sessions, and lock wait events, **not** unexposed asyncpg pool-wait time. Probes sample each replica directly through the gateway container.

### Ladder results

RPS is achieved HTTP requests per second. Latencies are k6 HTTP P50/P95/P99 in milliseconds. `E` is 5xx count; every listed stage had zero 4xx, zero 429, and zero transport failures. All sampled `/health` and `/ready` calls returned 200, and no backend restart was observed.

| Profile | VUs | 1 replica RPS | 1 replica P50/P95/P99 | 1 E | 2 replicas RPS | 2 replicas P50/P95/P99 | 2 E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cache-heavy | 50 | 15.9 | 11/139/226 | 0 | 15.9 | 11/99/330 | 0 |
| Cache-heavy | 100 | 31.5 | 14/210/298 | 0 | 31.8 | 11/143/254 | 0 |
| Cache-heavy | 250 | 78.0 | 25/437/623 | 1 | 78.4 | 14/234/522 | 0 |
| Cache-heavy | 500 | 152.2 | 52/831/1309 | 1 | 154.0 | 19/869/1298 | 0 |
| Cache-heavy | 1000 | 261.3 | 443/2125/2598 | 2 | 286.6 | 97/1506/1885 | 0 |
| Generation-heavy | 50 | 15.7 | 63/124/289 | 0 | 15.7 | 64/104/317 | 0 |
| Generation-heavy | 100 | 31.6 | 64/292/598 | 0 | 31.9 | 64/182/446 | 0 |
| Generation-heavy | 250 | 77.0 | 66/513/1223 | 0 | 76.5 | 67/644/1284 | 0 |
| Generation-heavy | 500 | 149.5 | 74/1246/2256 | 0 | 144.4 | 68/2311/4295 | 0 |
| Generation-heavy | 1000 | 191.6 | 1831/3755/4910 | 0 | 235.7 | 757/3173/4331 | 1 |
| Mixed-policy | 50 | 15.9 | 47/98/147 | 0 | 15.9 | 25/82/140 | 0 |
| Mixed-policy | 100 | 31.3 | 55/248/328 | 0 | 31.5 | 55/129/240 | 0 |
| Mixed-policy | 250 | 77.4 | 57/554/782 | 0 | 78.2 | 56/342/496 | 0 |
| Mixed-policy | 500 | 151.2 | 68/949/1583 | 0 | 154.6 | 56/608/1037 | 0 |
| Mixed-policy | 1000 | 268.8 | 312/2256/2774 | 0 | 297.1 | 77/1304/1975 | **1585** |

**Single-replica capacity knee.** The last clearly stable generation-heavy stage was 500 VUs: 149.5 RPS and P95 1.25 s with no errors. At 1,000 VUs, doubling users raised throughput only 28% to 191.6 RPS while P95 tripled to 3.76 s; sampled backend CPU reached about 117% of one core, the five-connection runtime pool was fully opened, and sampled DB lock waits appeared. Cache-heavy and mixed-policy stages also had a marked P95 inflection at 1,000 VUs, though they continued returning mostly successful responses. These observations support an API/DB contention hypothesis; they do not separately quantify pool wait or prove one SQL statement is the cause.

**One versus two replicas.** At 1,000 VUs, two replicas improved cache-heavy RPS about 10% and generation-heavy RPS about 23%, with lower P95 for both. At 500 generation-heavy VUs, two replicas were slightly slower and had substantially worse P95, so a second replica was not a uniform latency win. Both backend request counters advanced under the two-replica gateway (for example, 9,172 and 9,169 cache-heavy requests at 1,000 VUs). The two-replica runtime connection budget was 10 versus 5 for one replica; the sampled maximum reached both budgets. At the 1,000-VU two-replica cache-heavy stage, `pg_stat_activity` sampled up to 10 active runtime connections and 9 lock waits, while each backend used roughly one CPU core. These shared-dependency signals and the modest throughput gain do **not** justify a third replica on this host. The load-balanced topology remains independently useful for availability and failover.

**Cache, provider, coalescing, and probes.** At 1,000 VUs, cache-heavy responses were about 82% hits in both topologies, with 3,019 generation starts on one replica and 3,321 across two; generation-heavy response hits were 34% and 36%, with 8,311 and 9,704 generation starts. The mock provider peak was about 29 concurrent generations in the 1,000-VU cache-heavy and generation-heavy stages; these are local mock figures, not hosted quota measurements. The cold 50-request burst completed in about 157 ms overall with one replica (P50/P95/P99/max 152/155/155/155 ms): **one** generation leader, 49 miss/no-provider followers. With two replicas it completed in about 175 ms (165/172/172/172 ms): each replica handled 25 requests and produced one leader, for two leaders and 48 followers total. That is consistent with intentionally process-local coalescing. Backend cache-hit counts can be lower than caller-visible hit counts because followers may reuse a leader's result. No 1,000-VU stage caused sampled readiness flapping or a restart, but one-replica probe latency reached about 1.7–2.0 seconds at the top stage; two-replica direct readiness samples reached about 0.5–1.1 seconds. The raw telemetry contains each health/readiness latency and RSS sample.

**Unresolved 5xx anomaly.** The first two-replica mixed-policy 1,000-VU stage returned 1,585 5xx out of 19,041 requests (8.3%), while both backend query error counters stayed at zero and direct probes stayed ready. A fresh isolated repeat at the same VU count and profile returned 0/18,894 5xx at 295 RPS and P95 1.53 s. Earlier one-replica cache-heavy runs recorded isolated gateway 502s with Nginx `recv() failed (104: Connection reset by peer) while reading response header from upstream`; local `one-replica-gateway-errors.txt` excerpts support a gateway/upstream transport hypothesis, not a confirmed root cause for the mixed-stage spike. Keep the degraded first run in capacity decisions; do not infer a reliable 1,000-VU mixed-policy SLO from the clean repeat. The local `phase13-diagnostic-mixed-20260927/summary.json` repeat is separate evidence. A focused resilience investigation should reproduce and classify the 5xx before tuning production code. Its command was:

```powershell
python ops/load-testing/phase13.py `
  --output ops/load-testing/results/phase13-diagnostic-mixed-20260927 `
  --topologies 2 --profiles mixed-policy --vus 1000 `
  --duration 60s --skip-burst
```

### Stabilized repeats at the comparison points

The 500- and 1,000-VU cache-heavy and generation-heavy points were repeated on fresh stacks with an **unmeasured 20-second same-VU warm-up** immediately before each 60-second measurement. The warm-up metrics are retained as `warmup.json` but excluded from the table; they exercise the same prompt set and leave the cache warm. The original ladder had only the eight-prompt prewarm. These are separate measurement conditions, so compare topologies **within** each series.

```powershell
python ops/load-testing/phase13.py `
  --output ops/load-testing/results/phase13-stabilized-20260927 `
  --topologies 1 2 --profiles cache-heavy generation-heavy `
  --vus 500 1000 --duration 60s --stabilize 20s --skip-burst
```

| Profile | VUs | 1 replica RPS | 1 replica P50/P95/P99 ms | 1 E | 2 replicas RPS | 2 replicas P50/P95/P99 ms | 2 E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cache-heavy | 500 | 150.5 | 88/1029/1178 | 1 | 154.5 | 26/592/1077 | 0 |
| Cache-heavy | 1000 | 253.4 | 564/2378/3095 | 1 | 299.4 | 72/1038/1969 | 0 |
| Generation-heavy | 500 | 143.1 | 123/1366/2829 | 0 | 151.5 | 70/912/2413 | 0 |
| Generation-heavy | 1000 | 167.4 | 2494/4861/5932 | 0 | 269.6 | 367/1947/4117 | 0 |

The local `phase13-stabilized-20260927/summary.json` and per-stage telemetry preserve maximum latency, HTTP totals, CPU/RSS, database/probe samples, provider calls, and gateway errors. Every repeat had zero 4xx/429/transport failures, zero sampled probe failures, and zero restarts. The isolated one-replica cache-heavy 5xx in each repeat was a gateway 502 with an upstream connection-reset log; the generation-heavy repeats had no 5xx. At 1,000 generation-heavy VUs, one replica's P95 rose from 1.37 s at 500 VUs to 4.86 s while throughput rose only 17%; sampled CPU peaked at 115% of a core, RSS at 140 MiB, and the five-connection DB budget was fully opened. Two replicas served 270 RPS with P95 1.95 s and no errors, but opened all ten allowed runtime connections, sampled six lock waits, and reached 97%/119% of a core. This supports an API replica capacity benefit **for this workload** alongside measurable shared PostgreSQL contention. It does not establish safe headroom for three replicas. The one-replica knee is corroborated; its exact RPS/P95 varies between the original and stabilized runs. For example, original one-replica generation-heavy 1,000 VUs yielded 192 RPS/P95 3.76 s, versus 167 RPS/P95 4.86 s after same-load warm-up. The two-replica counterparts were 236 RPS/P95 3.17 s and 270 RPS/P95 1.95 s. Do not select only the favorable run.

### Ten-minute soak and SDK compatibility

After the ladder, a fresh two-replica disposable stack ran the cache-heavy profile at 1,000 VUs for **600 seconds** with the same 2–4-second think time:

```powershell
python ops/load-testing/phase13.py `
  --output ops/load-testing/results/phase13-soak-20260927 `
  --topologies 2 --profiles cache-heavy --vus 1000 `
  --duration 600s --skip-burst
```

The local `phase13-soak-20260927/summary.json` recorded 195,961 requests (324.4 RPS), 195,961 successes, no 4xx/429/5xx/transport failures, and P50/P95/P99/max of 31/186/606/2,441 ms. All 50 sampled probe sets stayed 200 with no restarts. Both replicas served traffic nearly evenly (97,983/97,978 queries); no readiness flapping was observed. Sampled backend CPU peaked at 93%/117% of one core and RSS at 92/104 MiB; direct readiness samples peaked at 812/693 ms. Runtime-role PostgreSQL connections and active sessions peaked at 10, the combined 2×5 pool budget, and sampled lock waits peaked at 8. The mock provider recorded 34,817 generation starts and peak concurrency 32; response hit rate was 82%. The backend reported 34,325 cache evictions, zero expirations. Per-replica samples are in `telemetry.jsonl`. These results establish this **cache-heavy** workload on this host for ten minutes; they do not validate a 1,000-VU generation-heavy or mixed-policy soak, nor a hosted provider quota. The much lower soak P95 than the short initial ladder shows that ramp and host conditions materially affect short-stage estimates.

The existing Python SDK integration suite ran through the **two-replica gateway URL** on a separate disposable stack, plus direct cross-replica shared-cache and threshold checks. The smoke exercised `SemantixClient`, `AsyncSemantixClient`, normal queries, miss/hit, per-request TTL, authentication, namespaces, `/health`, `/ready`, SDK 429 decoding after setting a disposable low quota, and SDK 5xx decoding after stopping only its disposable database:

```powershell
sdk/.venv/Scripts/python.exe ops/load-testing/sdk_gateway_smoke.py `
  --output ops/load-testing/results/phase13-sdk-20260927.json
```

The local `phase13-sdk-20260927.json` result passed all six checks, including rejection of the **third** query against a deployment-wide `2/minute` quota. No SDK source change was needed. The low-quota and database-outage checks were isolated from the capacity runs.

**Managed autoscaling policy feedback.** The provisional P95-above-twice-baseline rule would have triggered as early as 250 VUs in some profiles even while achieved throughput still rose nearly linearly; this laptop run does not justify using that signal alone. The CPU corroboration threshold was met near the top of the one-replica ladder. Full DB pool use and sampled lock waits at high load support freezing further scale-up until shared capacity is measured. Fleet in-flight work and provider queue wait were not exposed, and a local Docker host cannot validate managed-platform warm-up, drain, or production thresholds. Keep the [pilot values](autoscaling-readiness.md#pilot-policy) provisional.

**Measurement integrity and limits.** A one-VU/5-second harness pilot was excluded because the first summary parser read the wrong k6 JSON shape; its disposable files were removed after the parser was fixed. The original ladder, degraded mixed-policy stage, clean diagnostic repeat, stabilized repeats, and ten-minute soak were retained locally after testing; generated output is ignored by Git and may not be present in another checkout. The normal development containers remained running and host interference was not independently quantified. PostgreSQL `pg_stat_activity` shows sampled sessions and lock waits, but the application does not expose pool wait time or embedding-call counts separately. In the measured stages, backend provider-call deltas matched mock generation-start counts, with no observed generation retry amplification; this says nothing about hosted-provider retries or quotas. No three-replica capacity run was made because the two-replica stages already reached the configured PostgreSQL runtime connection budget and showed lock waits. A separate investigation should classify the intermittent gateway 502s and the unreproduced mixed-policy 5xx spike before treating the latter as a reliable capacity limit. The baseline added load harness and SDK smoke assets without optimizing production or SDK source.

The runner writes `environment.json`, `summary.json`, per-stage `result.json`, k6 metric JSON, sampled `telemetry.jsonl`, and gateway error excerpts under `ops/load-testing/results/`. These generated measurements stay local and are ignored by Git; the tables and observations above are the committed reviewable record. Back up local raw output separately if it must be retained beyond this checkout. Temporary root-level `phase13-*` runner directories are also ignored.

The runner and SDK smoke removed their uniquely named Compose containers, networks, volumes, and temporary credentials. A post-run Docker check found no `semantix-phase13` containers, networks, or volumes; the existing `semantix-frontend-1`, `semantix-backend-1`, and `semantix-postgres-1` remained running.
