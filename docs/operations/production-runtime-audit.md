# Production runtime audit — 2026-09-27

**Verdict: NOT PRODUCTION READY — the audited two-replica gateway returned 1,907 HTTP 502 responses during a 10-minute, 1,000-VU soak.** This is a local Docker Desktop verdict for the exact topology below. It is neither a managed-autoscaling certification nor a universal capacity limit.

## Scope and environment

| Item | Audited value |
| --- | --- |
| Source | Clean `origin/main` at `8a5ec1e1bb006ed3e894cfb2c79615c5b6504206`; audit scripts and this report are on a separate branch. No application or production Compose source was changed. |
| Topology | Production Compose: Nginx gateway, two Python backends, shared PostgreSQL/pgvector cache and PostgreSQL rate-limit, lockout, and threshold coordination. Token authentication and namespaces enabled. No managed autoscaler. |
| Host | Windows 11 build 26200; AMD Ryzen 9 5900HX, 16 logical CPUs, 33.7 GB physical RAM. Docker Desktop Engine 29.6.2 reported 16 CPUs and 16.45 GB VM memory. No per-service CPU or memory limits. The ordinary development stack remained running. |
| Images | Backend Python 3.14, based on pinned `python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83`; gateway based on pinned `nginxinc/nginx-unprivileged:1.31.3-alpine@sha256:f972e5322b9797dc2a6b830030094426437b1ae7032e4644496395336ac6fdac`; database `pgvector/pgvector:pg17@sha256:d2ef61f42ef767baa5a1475393303cc235bcd92febd9d7014eddb48b41f3bad0`. The final audit build image IDs were `sha256:c0e8d033185567b41e4b33091a2358053c50992bf1b70b3280a07199c200ba90` (backend) and `sha256:58a70276c3c72aa740dc5c8fec8dc50e51032e63677e837b80908e3ea3ca73fd` (gateway). |
| Load configuration | k6 v2.1.0 in a pinned container; deterministic mock embedding and generation, 384 dimensions, 50 ms generation delay, similarity threshold 0.92, cache TTL 3,600 seconds, cache capacity 500, DB pool 1–5 per replica, `RATE_LIMIT=100000/minute`. Shared coordination remained enabled. Each VU waited a deterministic 2, 3, or 4 seconds between requests. |
| Isolation | Each runtime exercise used a unique disposable Compose project, PostgreSQL volume, networks, credentials, and synthetic prompts. No hosted provider or normal development database was used. |

The exact-main [quality run](https://github.com/Yoruxyv/semantix/actions/runs/36325627432) passed CodeQL for Python and JavaScript/TypeScript, frontend and backend image scans, secret scanning, SBOM/provenance, container validation, pgvector integration, backend/frontend/SDK quality, and hardened smoke. Dependency review was skipped on that main-branch run. Local checks independently passed: 509 non-pgvector backend tests (80.38% coverage), 44 disposable-pgvector integration tests, Ruff, format, mypy, Compose validation, and shell EOL validation. The pgvector integration database was removed afterward.

## Runtime verification

| Area | Result | Evidence and boundary |
| --- | --- | --- |
| Security | **PASS for tested local boundary** | Two-replica smoke exercised auth roles, namespace scope, shared progressive lockout, and deployment-wide quota. Gateway smoke observed unauthenticated 401; five security headers; 413 for both declared and chunked oversized bodies; 400 for large headers and conflicting `Content-Length`/`Transfer-Encoding`; and `401, 401, 429` despite three forged `X-Forwarded-For` values. Existing real-Uvicorn tests passed for secret redaction and provider URL suppression. CI scans passed at the audited SHA. External TLS termination and production secrets delivery were not exercised. |
| Provider safety | **PASS for tested contracts** | The passing provider suite includes total deadline, retry/backoff budget, cancellation, response-size and encoded-response rejection, malformed JSON/vector handling, safe public errors, and log redaction. Mock providers were used in all load runs; hosted-provider latency, quotas, and live credentials were not tested. |
| Cache correctness | **PASS** | 44 pgvector integration tests covered clean and idempotent migrations, schema/checksum behavior, runtime permissions, persistence, expiry, and embedding-space/namespace isolation. Two-replica smoke verified cross-replica hit, TTL, deletion/clear, shared threshold, and cache-policy behavior. The 50-request identical cold burst reached both replicas (25 requests each) and produced exactly two generation leaders and 48 coalesced followers, as expected for process-local coalescing. |
| Database and migration | **PASS for disposable recovery** | Fresh pgvector tests passed. The recovery exercise restarted both backends and the gateway without losing a cached entry; after stopping PostgreSQL, a direct `/ready` returned 503 in about 4.5 seconds. A custom-format 11,606-byte dump restored into a fresh PostgreSQL volume, after which both replicas were ready and the cached prompt hit. The SDK smoke also decoded a server error during its own isolated DB outage. |
| HTTP gateway | **PASS for bounds and identity; load defect below** | The gateway smoke tested routing, `/health`, `/ready`, security headers, body limits, large headers, conflicting framing, and forwarded-address spoofing. The sustained load result failed separately at the gateway/upstream boundary. |
| Shutdown and recovery | **PARTIAL** | Two-replica smoke exercised an active mock-provider request while draining/stopping a replica, failover, and restart. A separate disposable 2→3→2 scale cycle passed with zero routing errors, 12.47-second new-replica readiness, and a 10-connection sampled DB peak; this is not managed-autoscaling certification. Backup/restore and database outage/recovery passed. A deliberately blocked in-flight database query during shutdown was not separately exercised; do not infer its behavior from the provider drain. |
| SDK through gateway | **PASS** | The existing Python SDK integration flow passed sync and async clients, query/cache behavior, per-request TTL, authentication, namespaces, `/health`, `/ready`, shared cache/threshold, 429 decoding, and server-error decoding against a disposable two-replica gateway. No SDK source change was required. |

The Windows hardened-smoke wrapper initially serialized its single principal as an object, which the backend correctly rejected because it requires a JSON list. The wrapper now passes an array and supports the existing two-replica smoke. The CI scale-cycle smoke also assumed one gateway log line would arrive per read; the runner sometimes delivered a batch of two valid upstream entries. Its assertion now accepts valid batches and still rejects unexpected or drained upstreams. The disposable 2→3→2 cycle passed after this focused test fix. These were audit-harness defects, not application runtime changes.

## Load evidence

The current k6 harness ran 60-second stages at 50, 100, 250, 500, and 1,000 VUs. It prewarmed repeated prompts but did not use an unmeasured same-VU stabilization interval, so short-stage values include ramp effects. Cache-heavy chose 80% repeated and 20% unique prompts; generation-heavy chose 10% repeated and 90% unique; mixed policy used 60% normal and 10% each read-only, refresh, bypass, and private. Percentages describe prompt/policy selection; actual semantic-cache hits can differ. Every ladder stage had zero 4xx, zero 429, zero transport failures, zero sampled probe failures, and zero restarts.

| Profile | VUs | Requests | RPS | P50/P95/P99 ms | 5xx | Cache hit | Mock generations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cache-heavy | 50 | 1,004 | 15.7 | 17/155/469 | 0 | 83.7% | 164 |
| Cache-heavy | 100 | 2,008 | 31.4 | 18/287/362 | 1 | 82.4% | 354 |
| Cache-heavy | 250 | 4,969 | 77.7 | 27/458/705 | 0 | 81.4% | 926 |
| Cache-heavy | 500 | 9,780 | 152.8 | 43/810/1,463 | 0 | 81.4% | 1,818 |
| Cache-heavy | 1,000 | 16,717 | 259.8 | 344/2,693/4,102 | 1 | 81.9% | 3,033 |
| Generation-heavy | 50 | 1,002 | 15.7 | 70/158/408 | 0 | 27.0% | 731 |
| Generation-heavy | 100 | 1,995 | 31.5 | 72/186/681 | 0 | 18.2% | 1,632 |
| Generation-heavy | 250 | 4,866 | 76.0 | 76/673/1,518 | 0 | 20.6% | 3,863 |
| Generation-heavy | 500 | 9,213 | 140.9 | 156/1,713/3,659 | 0 | 30.1% | 6,439 |
| Generation-heavy | 1,000 | 9,822 | 145.6 | 3,324/5,779/6,953 | 0 | 29.7% | 6,909 |
| Mixed policy | 50 | 1,005 | 15.7 | 57/122/181 | 0 | 53.5% | 467 |
| Mixed policy | 100 | 2,003 | 31.3 | 58/202/357 | 0 | 52.3% | 955 |
| Mixed policy | 250 | 4,955 | 77.7 | 59/508/887 | 0 | 51.2% | 2,417 |
| Mixed policy | 500 | 9,680 | 151.1 | 72/956/1,831 | 0 | 52.1% | 4,640 |
| Mixed policy | 1,000 | 15,758 | 245.2 | 563/2,930/3,708 | 0 | 53.5% | 7,322 |

The 50-VU cold burst completed 50/50 requests at 267.5 RPS with P50/P95/P99/max 176/179/181/182 ms, two provider calls, and 48 followers. The two-replica smoke separately recorded `upstreams=2`, an observed 10-connection DB peak, a mock-provider concurrency peak of 12, two same-prompt generations, and no transient failover error. Both backend request counters advanced during every load profile.

At 1,000 generation-heavy VUs, throughput rose only from 140.9 to 145.6 RPS versus 500 VUs while P95 rose from 1.71 to 5.78 seconds. Sampled runtime-role connections reached the two-pool maximum of 10, active connections reached 9, and lock waits reached 8; mock generation concurrency peaked at 28. These support a capacity knee on this host, but do not isolate whether API CPU, DB work, or another shared resource is dominant. The application does not expose pool-wait timing. This capacity observation is **NO ACTION** for production code during this audit; it does not justify an automatic third replica or a new shared component.

### Ten-minute 1,000-VU cache-heavy soak

The independent 600-second soak returned **164,401 requests at 271.1 RPS: 162,494 successes and 1,907 HTTP 502s (1.16%)**, with zero 4xx, 429, or transport failures. P50/P95/P99/max were 424/2,072/4,009/8,086 ms; successful responses were 82.2% cache hits. Both backends served nearly evenly (81,298 and 81,196 request-counter increments), recorded zero application error-counter increments and zero restarts, and made 28,855 mock-generation calls combined (peak concurrency 18). Cache evictions totalled 28,363; no expiry was observed. Sampled runtime-role connections, active sessions, and lock waits peaked at 10/10/8, against a 10-connection pool budget. Sampled backend CPU peaked at 170%/156% of one core and RSS at 109/112 MiB.

All 37 direct `/health` and `/ready` sample sets returned 200 for both replicas, including a sample about five seconds after a gateway `no live upstreams` burst. No readiness flapping or container restart was sampled. Maximum sampled ready latency was about 6.0/2.1 seconds for backends A/B. These timings include `docker compose exec` and curl startup; they are not pure HTTP latency, and 37 samples cannot prove continuous readiness.

Raw local results are Git-ignored under `ops/load-testing/results/runtime-audit-20260927/` (ladder), `ops/load-testing/results/runtime-audit-soak-20260927/` (soak), and `ops/load-testing/results/runtime-audit-sdk-20260927.json` (SDK). Each load stage has `k6.json`, `result.json`, `telemetry.jsonl`, `k6.log`, and a bounded `gateway-errors.txt` excerpt. The full high-volume gateway log was not retained after disposable cleanup; k6 counters and first/last error excerpts remain. No raw output or Docker artifacts are committed.

## Finding R1 — gateway 502 amplification under sustained load

- **Classification/severity:** HIGH DEFECT; resilience defect in the tested two-replica production Compose topology.
- **Reproduction:** From the repository root on a fresh disposable Docker host, run `python ops/load-testing/phase13.py --output ops/load-testing/results/<new-name> --topologies 2 --profiles cache-heavy --vus 1000 --duration 600s --skip-burst`. It uses authenticated synthetic traffic, shared PostgreSQL coordination, and deterministic mock providers. The preceding 60-second ladder also produced isolated gateway 502s at 100 and 1,000 cache-heavy VUs.
- **Observed impact:** 1,907 of 164,401 soak requests failed as 502. The Nginx excerpt shows `recv() failed (104: Connection reset by peer) while reading response header from upstream`, followed by `no live upstreams while connecting to upstream`. Nginx's production upstream uses `max_fails=1 fail_timeout=5s`. Both backends had zero restarts and zero application error-counter increments; nearby sampled direct probes were 200. The initial upstream connection-reset cause is **unconfirmed**. The evidence does support gateway error amplification after upstreams are passively marked unavailable.
- **Smallest plausible remediation:** Reproduce with request-correlated gateway and backend connection logs, identify why established upstream connections reset, and review the `max_fails=1`/five-second passive-failure behavior so one reset per replica cannot briefly exhaust all healthy targets. Keep failover for genuinely dead replicas. Rerun the same ladder and 10-minute soak after a focused fix; do not mix that result into this baseline.

The earlier capacity document also recorded intermittent gateway 5xx on an older commit. This audit's current-main 502 count stands independently; the older result is context, not a substituted pass or failure.

### Gateway resilience follow-up — 2026-09-28

The original 164,401-request failure above remains the before-fix baseline. Work began from `origin/main` at `07a232fd296386c07ffe93bb3084eaef1a70ae4a` on `fix/gateway-upstream-resilience`. The host (Ryzen 9 5900HX, 16 logical CPUs, 33.7 GB RAM), Docker Engine 29.6.2 (16 CPUs, 16.45 GB VM RAM), backend Python 3.14, Nginx 1.31.3, pgvector PostgreSQL 17, k6 2.1.0, pinned base images, two-replica topology, DB pool 1–5 per replica, cache settings, mock providers, k6 profile, 1,000 VUs, think time, and 600-second duration were retained. The starting gateway used `max_fails=1 fail_timeout=5s`, `proxy_next_upstream error timeout`, and two total upstream attempts; Nginx does not automatically replay non-idempotent POST requests after sending them upstream. Two fresh pre-change 600-second runs did **not** reproduce the historical burst: the traced run completed 194,538 requests with zero errors, and the untraced run completed 197,081 requests with zero errors. This limits attribution of any later load-test improvement to the change.

A bounded deterministic test using the production Nginx configuration reproduced the gateway amplification mechanism. With `max_fails=1 fail_timeout=5s`, one deliberately reset POST on each of two still-running peers returned two 502s; a subsequent gateway `/health` returned 502 while both peers continued serving. Thus the passive failure threshold can temporarily exhaust healthy upstreams. It does **not** establish why the original connections reset. The historical logs show two peer resets 144 ms apart followed by `no live upstreams`; backend restarts, application error counters, and sampled direct readiness did not explain the initiating resets.

The production upstream and matching generated smoke/load configurations now use `max_fails=2 fail_timeout=5s`. The threshold allows one transient failure per peer without ejecting both; a genuinely unavailable peer still reaches the threshold. The gateway records a request ID, selected upstream, upstream status and timings, and forwards the ID to the backend. Optional `SEMANTIX_GATEWAY_TRACE=1` emits backend request start/end, completion, cancellation, or exception with that ID. It defaults off and records no tokens, prompts, secrets, or raw payloads. The load runner retains bounded gateway error lines and matching backend trace lines after disposable cleanup.

| 600-second cache-heavy run | Requests | RPS | P50/P95/P99/max ms | 502 | Other 4xx/429/transport |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original audit, before fix | 164,401 | 271.1 | 424/2,072/4,009/8,086 | 1,907 | 0 |
| Fresh pre-change, traced | 194,538 | 322.1 | 34/323/938/2,227 | 0 | 0 |
| Fresh pre-change, untraced | 197,081 | 326.3 | 20/137/517/2,096 | 0 | 0 |
| After threshold change, untraced | 182,681 | 302.5 | 63/1,444/4,141/9,994 | 5 | 0 |
| After threshold change, traced | 196,061 | 324.6 | 25/200/778/2,207 | 1 | 0 |

The post-change run had no `no live upstreams` lines. Its five 502s were isolated `recv() failed (104: Connection reset by peer) while reading response header from upstream` events, so the initiating reset remains open. Both backends served traffic (92,170/90,506 request increments), with zero application error increments and zero restarts. All 47 sampled health/readiness sets passed. Sampled backend CPU peaked at 143%/123% of one core and RSS at 106/106 MiB. Sampled DB connection/active/lock-wait peaks were 10/10/8; there were 32,415 mock generations (peak concurrency 29), 150,261 cache hits, and 32,415 misses. These are separate runs under the same specified load conditions, not paired requests; host scheduling and tracing can vary.

The second, traced post-change run also had no `no live upstreams` burst, zero restarts, and zero sampled readiness failures (50 sample sets). Both replicas served about 98,000 requests. Sampled backend CPU peaked at 109%/120% of one core and RSS at 101/93 MiB; DB connection/active/lock-wait peaks were 10/10/9. It recorded 34,843 mock generations (peak concurrency 28), 161,217 cache hits, and 34,843 misses. The single gateway 502 had a matching Nginx request ID but no backend lifecycle entry. At a late-run sample, backend A's TCP `OutRsts` counter and the gateway's `EstabResets` counter had each risen from zero to one. Together with a 0–1 ms failed upstream response, this places the observed reset at the backend TCP/HTTP-server boundary before ASGI middleware handling. It does not distinguish Uvicorn socket lifecycle from kernel/network pressure, and the Docker counter sample is not packet-level proof for that exact request.

The controlled reset test now passes with two deliberately induced 502s followed by gateway `/health` 200, confirms both upstreams are running, then checks real one-replica stop, surviving-peer routing, and recovery. The production two-replica smoke also passed routing distribution, direct readiness, graceful drain, restart, cache, auth, namespace, and rate-limit behavior. The high-load run still has isolated 502s, so the original initiating reset is not claimed fixed and this follow-up does not certify the entire product for production. Raw generated results are Git-ignored under `ops/load-testing/results/gateway-repro-20260928/`, `gateway-repro-no-trace-20260928/`, `gateway-remediation-20260928/`, and `gateway-remediation-trace-20260928/`.

## Limits and NO ACTION observations

- **TEST ENVIRONMENT LIMITATION:** The local gateway was bound to loopback HTTP. External TLS termination, production certificate rotation, real reverse-proxy identity configuration, managed secret delivery, hosted-provider quotas, and managed autoscaling were not certified here. Provider boundary contracts and local trusted-proxy behavior were tested; live provider performance was not.
- **TEST ENVIRONMENT LIMITATION:** Active provider drain was exercised, but a deliberately blocked in-flight DB operation during backend shutdown was not. This is a remaining verification gap for any claim of complete shutdown safety.
- **NO ACTION:** Two generation leaders for a cold identical prompt across two replicas are consistent with intentionally process-local coalescing. A third replica is not justified by this run while the shared DB pool is at budget and lock waits are observed. The load balancer still provides availability/failover value independently of throughput gain.
- **NO ACTION:** The provisional managed-autoscaling thresholds remain unvalidated by this Docker Desktop run. The generation-heavy knee and 502 burst argue against tuning a production threshold from one local measurement. No SDK, cache algorithm, SQL, pool-size, or production proxy setting was changed during the baseline.

## Reproduction and cleanup

The ladder and soak commands are shown above. For the focused runtime checks, use fresh `COMPOSE_PROJECT_NAME` values and run `powershell -NoProfile -ExecutionPolicy Bypass -File ops/ci/windows/hardened-smoke.ps1 python ops/ci/two_replica_smoke.py` or replace the follow-up with `python ops/ci/runtime_proxy_smoke.py`, after setting `SEMANTIX_PORT=18080` and isolated mock-provider environment values. The wrapper removes its named Compose project and volume. Run `python ops/load-testing/backup_restore_smoke.py` for the disposable dump/restore exercise and `sdk/.venv/Scripts/python.exe ops/load-testing/sdk_gateway_smoke.py --output <ignored-path>` for SDK compatibility. Both helpers clean their own disposable projects and volumes. Never point these commands at the normal development database.

After the audit, `docker ps` showed only the original `semantix-frontend-1`, `semantix-backend-1`, and `semantix-postgres-1`; no audit container or PostgreSQL volume remained. Generated k6 results stayed in the ignored results directory for local investigation. No global Docker prune was used.
