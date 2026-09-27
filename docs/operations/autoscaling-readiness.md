# Phase 12D: managed autoscaling readiness

**Scope:** a bounded two-to-three-replica pilot behind a managed load balancer, with shared PostgreSQL/pgvector and PostgreSQL coordination. The [two-replica deployment](deployment.md#two-replica-operation) remains the starting point. The chosen platform must implement the routing and scale policy below; this document is not a platform autoscaler configuration.

## Pilot policy

| Decision | Initial setting | Required signal |
| --- | --- | --- |
| Replica bounds | Minimum 2, maximum 3 healthy replicas | Count only replicas passing their own `/ready` probe |
| Scale up | Add one replica after three consecutive one-minute windows with more than 4 in-flight API requests per ready replica **or** query P95 above twice the measured two-replica baseline; at least 2 minutes between scale-ups | Load balancer concurrency and P95 across the fleet; inspect errors and downstream saturation before acting |
| Scale down | Remove one replica after 15 minutes at or below 1 in-flight request per ready replica, CPU below 35%, P95 at baseline, and no elevated errors; at least 15 minutes between scale-downs | Load balancer concurrency/P95/error rate and container CPU |
| Warm-up | Register a new replica only after its direct `/ready` succeeds; exclude its first 30 seconds from scale decisions | Per-replica readiness and start time |
| Freeze scaling | Hold at the last healthy count when DB connection use, provider concurrency/wait, or provider error rate exceeds the tested budget; investigate before increasing capacity | Database and provider telemetry |

These are conservative **pilot values**, not measured production thresholds. Record a representative two-replica baseline, then tune against a real workload and the selected platform's metric semantics. CPU above 70% can corroborate sustained demand, but CPU alone does not trigger scale-up. A high P95 caused by a saturated database or provider cannot be fixed by adding API replicas.

`/api/v1/metrics` is process-local: its P95 and provider-call counters reset on each replica boot. Aggregate instance-labelled metrics externally or use the managed load balancer for fleet P95, in-flight requests, and error rate. The current app does not expose total in-flight work, DB pool busy/wait, or provider queue wait as fleet metrics. Instrument those at the platform/pool/provider boundary before enabling an unattended policy that depends on them. A process-level readiness response is not fleet health.

## Capacity checks before enabling the policy

At the default `DATABASE_POOL_MAX_SIZE=5`, three replicas reserve **up to 15 runtime connections**. Budget at least another 5 connections for the one-shot migration job, administration, monitoring, and failover operations, then verify the actual PostgreSQL `max_connections`, reserved slots, other clients, and pooler limits on the target service. If that headroom is unavailable, reduce the pool maximum or replica cap. Watch `pg_stat_activity` and pool busy/wait during scale-up; the disposable test asserts no more than 15 runtime-role connections. The migration service must finish once before replicas start; production backends keep `DATABASE_MIGRATION_MODE=external`.

Budget provider demand **across all three replicas**, including misses on separate replicas, evaluation runs, and retries. Hosted adapters permit up to three attempts per operation. For example, if the ingress admits four concurrent cache misses per replica, three replicas can start 12 embedding calls and up to 36 embedding attempts under retries; misses that reach generation can add 12 generation calls and up to 36 generation attempts. This is a planning upper bound, not an existing global admission limit. Set ingress/provider concurrency and rate caps from the actual account quotas and observe retry and wait metrics. Do not turn on autoscaling with live providers until this budget is measured and enforced. The CI burst uses the deterministic mock provider and proves routing and lifecycle behavior, not external quota safety.

## Register, drain, and recover

1. Deploy the same image, secrets, provider configuration, embedding space, and cache settings to every replica. Start a new container outside the load balancer's active targets. Run no per-replica production migrations.
2. Probe that replica's `/ready` directly until it succeeds, then register it. `/health` only proves that the process answers; it does not check the shared cache and coordination dependencies. Start its warm-up clock at registration. Record container-start, first DB connection, readiness, and first-request times.
3. For scale-down, stop routing new requests to one replica and wait for its admitted requests to finish. Then terminate it with a grace period longer than the longest admitted operation. The Compose baseline is 330 seconds gateway read timeout, 300 seconds default evaluation timeout, and 360 seconds backend stop grace. Preserve that relationship in the managed platform. Confirm HTTP clients and the PostgreSQL pool close and cache writes complete before the deadline.
4. Continue serving from the other two ready replicas. Check shared cache entries, threshold/rate-limit/lockout coordination, error rate, and DB connections after termination. If readiness flaps, drain fails, provider wait rises, or errors increase, freeze scaling and restore the previous healthy count after correcting the cause.

The managed load balancer must probe **each** target's `/ready`, remove it from routing before termination, and support connection draining. The Compose gateway's dynamic DNS upstream is a two-replica baseline; simply scaling that Compose service is not the managed routing policy. The controlled smoke test explicitly gates and removes the third target around readiness and drain.

## Reproduce the controlled cycle

The hardened CI stack runs `ops/ci/autoscaling_smoke.py` after the two-replica smoke. It starts from two ready replicas, adds a third without restarting dependencies, times its DB connection/readiness/first request, routes it only after readiness, sends a concurrent mock-provider burst, then removes it from routing while a request is active and scales back to two. Assertions cover runtime DB connection bounds, provider call count/peak, no gateway routing errors or readiness failures, successful shutdown, unchanged migration start time, and shared cache/threshold state after scale-down. The stack uses an isolated project and disposable data.

For a local reproduction, use the hardened smoke wrapper with the same environment as CI and run:

```bash
bash ops/ci/linux/hardened-smoke.sh bash -c 'python3 ops/ci/two_replica_smoke.py && python3 ops/ci/autoscaling_smoke.py'
```

The script prints the observed timing and peak values. Keep those numbers with the target platform's rollout evidence; local Docker timings are not a cloud cold-start guarantee. The exit criterion **MANAGED AUTOSCALING READY** applies only after the chosen platform implements the policy, metrics, provider quota budget, per-target readiness, and drain, and passes the controlled cycle there.

On a local Docker Desktop run, the controlled 2→3→2 cycle passed with a first observed third runtime DB connection at 3.54 seconds, third-replica readiness at 11.28 seconds, and its first provider-backed request at 2,453 ms. The 12-request mock burst had 2,001 ms P95, 12 generation calls, 12 peak concurrent generation calls, and 9 peak runtime DB connections. There were no routing or readiness errors. These values describe the disposable mock stack and must be remeasured on the chosen managed platform.
