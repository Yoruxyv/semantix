# Current architecture

This describes the implementation at the current source revision. For product principles
see [DESIGN.md](DESIGN.md); for deployment procedures and measured limits see
[docs/operations/deployment.md](docs/operations/deployment.md) and
[docs/operations/production-runtime-audit.md](docs/operations/production-runtime-audit.md).

## Product and request path

Semantix consists of a FastAPI semantic-cache service, a React browser dashboard, and an
independently installable Python HTTP client. Applications can call the public HTTP API
directly or use the SDK. The SDK is a remote client, not another cache engine.
Configured embedding and generation providers are external to the cache service; the
mock provider supports deterministic local use. The live cache is either process memory
or PostgreSQL with pgvector, according to settings.

An independently installable [semantix-cache](packages/cache/README.md) supplies the async
embedded facade and bounded MemoryStore for applications that do not run this server.
It accepts structural embedding adapters and application-owned async generation.
Its private semantic core owns canonicalization, keys, namespace rules, vector
normalization/scoring, TTL resolution, threshold eligibility and resolution ordering.
The backend consumes the local embedded package through its locked path dependency,
while preserving its HTTP schemas, authorization, metrics, global threshold and
request coalescer. semantix-client remains a separate HTTP-only product.
Optional embedded adapters live in `semantix_cache.adapters`, with borrowed HTTPX
clients and explicit model/space configuration. Root imports retain the minimal
NumPy/Pydantic boundary. Backend/embedded parity tests protect common provider wire
contracts; generation still enters the cache as an application-owned async callable.
See the [provider guide](docs/embedded-providers.md). PostgreSQL storage is not implemented.

In the hardened Compose deployment, the browser and other HTTP clients reach the
frontend Nginx gateway, which serves the browser assets and balances API requests across
backend-a and backend-b. A development browser uses Vite and can reach the backend
directly. The gateway does not own cache decisions.

For POST /api/v1/query, the request passes Pydantic validation, rate limiting,
token authentication, and resolution to an authorized concrete namespace. QueryService
coalesces identical in-flight work within one process. When reads are enabled,
SemanticCache normalizes matching text, asks the embedding provider for a vector, and
searches compatible entries in that namespace and embedding space. A candidate at or
above the current threshold is returned with decision evidence. On a miss, or when reads
are disabled, the generation provider receives the original prompt. Successful,
nonempty, bounded output is stored only when the policy permits writes. Private and
bypass policies neither read nor write the live cache. The response reports hit,
similarity, match, provider-call, and latency evidence.
[query schema](apps/server/app/query/api/schemas.py) and
[cache policies](apps/server/app/query/domain/policies.py) define the exact fields and modes.

## Repository layout

| Path | Role |
|---|---|
| `apps/server/` | Official self-hosted FastAPI application |
| `apps/web/` | Official web/workbench application |
| `packages/cache/` | Primary reusable semantix-cache library |
| `packages/client/` | Maintained optional/reference semantix-client HTTP client |
| `ops/` | Operational and deployment tooling |
| `scripts/` | Repository and developer tooling |

Each Python project retains its own `pyproject.toml` and lockfile. The web app
retains its independent Node project. Compose entry points remain at the root.

## Backend ownership

- [app/api](apps/server/app/api/router.py) composes feature routes;
  [factory](apps/server/app/factory.py) and [lifespan](apps/server/app/lifecycle.py) construct
  shared dependencies.
- app/query owns the query HTTP contract, policy and normalization rules, coalescing,
  and lookup/generation orchestration.
- app/cache owns keys, namespaces, threshold behavior, inspection and mutation routes,
  backend protocols, memory and pgvector adapters, and cache SQL.
- app/benchmark owns bounded, serialized evaluation execution, dataset
  validation/catalog, projections, optional run history, and its SQL. Each run uses a
  fresh in-memory cache; it does not read or seed the live cache.
- app/providers owns embedding and generation protocols, startup selection, and
  provider-specific adapters. A lifespan-owned httpx.AsyncClient supplies their HTTP
  transport.
- app/embedding validates vectors before cache use. app/observability owns process-local
  metrics and allowlisted diagnostics.
- app/security owns token principals, roles, and namespace resolution. Middleware owns
  body limits, client address handling, and rate limiting.
- app/infrastructure owns the shared PostgreSQL pool, migration runner, and PostgreSQL
  coordination for rate buckets, session lockouts, and global threshold. app/core owns
  settings, shared limits, error responses, and safe logging.

Feature application code generally uses provider and storage protocols; infrastructure
adapters implement them. The small observability feature remains flat.

## Browser and SDK boundaries

The frontend has feature-owned Monitor, Cache, Evaluations (under features/benchmark),
Observability, and Auth modules. Each owns its pages, components, hooks, API adapter,
types, decoders, and route registry where needed. app/router composes lazy routes;
shared/api supplies HTTP and common validators; React Query handles server data. Monitor
traces and imported inline evaluation definitions live in browser memory. Feature state
clears on relevant principal or lifecycle changes; an explicit authorized save can
persist a dataset on the server. Browser role checks shape the UI but never replace
server authorization.

The semantix-client runtime depends only on the standard library and httpx. SemantixClient and
AsyncSemantixClient expose query, health, and ready over the public HTTP API, with typed
models and errors. Each owns a pooled httpx client and exposes close/aclose plus a
context manager. The SDK has no dependency on FastAPI, backend modules, database
adapters, or local cache state. Backend public query/health/readiness contracts and SDK
decoders must be reviewed together when either changes.

## State and migrations

Process-local state includes memory-cache entries, coalescing, metrics, the evaluation
run lock and run cache, provider HTTP connections, and settings snapshots.
PostgreSQL-backed deployments share pgvector cache entries and counters, the configured
evaluation dataset catalog and optional terminal run history, rate-limit buckets,
authentication lockouts, and the mutable global threshold. External providers own their
own service state and quota behavior. The application does not have a distributed
coalescer or fleet-wide metrics store.

One backend pool serves enabled PostgreSQL features. With memory cache, session-only
datasets, disabled run history, and memory coordination, no database pool is required.
Cache migration 0001 owns vector/cache tables; evaluation migrations 0002 and 0003 own
datasets and aggregate run history; shared coordination migration 0004 owns rate,
lockout, and threshold tables. The shared runner uses an advisory lock, transactions,
ordered packaged migrations within each owner, and SHA-256 checksums. Development may
apply enabled migrations automatically. Hardened Compose runs a one-shot migration
service with a migration role before backends start; backend runtime uses a separately
granted role and external migration mode. See
[pool lifecycle](apps/server/app/infrastructure/lifecycle.py),
[migrator](apps/server/app/infrastructure/migrate.py), and
[deployment](docs/operations/deployment.md).

## Production and failure boundaries

The documented hardened Compose topology is one Nginx gateway, two backend replicas, and
one shared PostgreSQL/pgvector service. Only the gateway binds a host port, loopback by
default; public traffic requires an external TLS reverse proxy. The tested readiness,
failover, drain, and capacity evidence applies to this topology and mock-provider
workload, not arbitrary replica counts, managed autoscaling, hosted-provider quotas, or
HA PostgreSQL.

GET /health is a cheap process liveness answer with provider categories. GET /ready
checks cache statistics, the enabled persistent dataset catalog, and PostgreSQL
threshold coordination; it returns 503 for their handled storage failures. It does not
directly probe the optional run-history repository. It does not test hosted providers,
and a gateway response covers only the selected replica. For planned drain, operators remove a
replica from the gateway upstream, validate and reload Nginx, let admitted work
complete, stop it, then rejoin only after direct readiness passes. Gateway retry
behavior covers connection errors/timeouts, while stopped-replica failover and blocked
cache-write shutdown have focused smokes. The production audit retains rare residual
upstream resets and their scope; it does not promise zero 502s.

Token authentication and role/namespace checks are backend-owned. Hardened traffic
relies on configured trusted proxy CIDRs, bounded bodies, shared abuse controls, and an
external TLS/secret-management boundary. Diagnostics expose an explicit safe allowlist;
prompts, responses, credentials, private endpoints, and raw settings are excluded.
Namespace filters apply before cache candidate selection, and foreign entry detail is
not disclosed.

Current deliberate exclusions include a message bus, Redis requirement, distributed
request coalescing, fleet-wide telemetry inside the app, generic tenant/billing
services, and a certified multi-region or HA database design. Add those only for a
separately evidenced need.
