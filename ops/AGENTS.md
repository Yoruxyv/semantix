# Operations agent instructions

Read [root instructions](../AGENTS.md), [current architecture](../ARCHITECTURE.md),
[deployment](../docs/operations/deployment.md), and
[production audit](../docs/operations/production-runtime-audit.md) for operational changes. These
rules cover ops, root Compose files, gateway configuration, and CI workflows.

## Deployment and safety

- Preserve the supported hardened Compose boundary: gateway, two backends, shared
  PostgreSQL/pgvector and coordination, token auth, separate migration/runtime roles,
  and external TLS termination. Do not silently change replica count, upstream
  retry/drain behavior, trust proxies, body limits, role grants, or production defaults.
- Validate production Compose against an example or disposable environment before
  rollout. The normal development stack uses different credentials, auto migrations, and
  local ports; never use it as proof of hardened behavior.
- Every smoke, migration, backup/restore, and load run must use explicitly named
  disposable resources. Verify targets before cleanup. Never prune Docker globally or
  delete another project's volumes.
- Keep credentials generated or supplied through environment/secret handling, out of
  command output and tracked files. Preserve safe gateway access logging and header
  forwarding.
- Keep health, per-replica readiness, planned upstream removal, active-request drain,
  failover, and recovery behavior consistent. A gateway readiness response reflects one
  selected replica, so check each backend directly for rollout decisions.
- Do not add Redis, Kubernetes, HA PostgreSQL, a message bus, or a managed autoscaling
  claim without a separate demonstrated need and evidence.

## Evidence and CI

- Use deterministic mock providers for repeatable capacity comparisons unless a
  provider-specific experiment is explicitly approved. Record source SHA, topology, host
  resources, settings, workload, duration, warm-up, cache state, failures, and retained
  raw results.
- Preserve failed benchmark and production-audit evidence alongside remediation; do not
  present a clean repeat as if a degraded run never happened. Performance conclusions
  are limited to the measured hardware, workload, providers, and topology.
- Write generated k6, smoke, and audit results only to ignored/local locations. Clean up
  only the run's named Compose project and volume; keep failed evidence available for
  diagnosis.
- Keep CI checks and action permissions intentional. Changes to image pins, workflow
  gates, shell line endings, or package artifacts require validation of the
  corresponding job behavior. Do not mark an unrun check as passed.
- For relevant Compose edits run docker compose config --quiet, the development pgvector
  config, and the production config with .env.production.example. Use the existing
  focused smoke for gateway, readiness, failover, drain, or scaling changes. Full load
  tests require a specific question and a reproducible plan.
