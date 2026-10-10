# Hardened deployment

This deployment path is optional for local development and required before Semantix is shared with untrusted users. The production Compose stack runs two backend replicas behind one frontend gateway; it is not a complete multi-tenant platform.

## Deployment boundary

`docker-compose.prod.yml` publishes only the frontend gateway. Neither backend publishes a host port; the gateway reaches `backend-a` and `backend-b` over `edge`. Both backends also join `data`, where PostgreSQL has no host port and the network is marked `internal: true`. The gateway balances `/api`, `/health`, and `/ready` across the two replicas.

`docker-compose.prod.yml` uses the explicit Compose project name `semantix-prod`. Its PostgreSQL volume is therefore isolated from the local development volume and from volumes created by earlier versions of the default development stack.

The default host binding is:

```env
SEMANTIX_BIND_ADDRESS=127.0.0.1
SEMANTIX_PORT=8080
```

Evaluation runs have an independent bounded wall-clock setting:

```env
EVALUATION_TIMEOUT_SECONDS=300
EVALUATION_DATASET_MAX_CASES=50
EVALUATION_DATASET_MAX_DECODED_BYTES=49152
EVALUATION_MAX_WORKLOAD_QUERIES=250
EVALUATION_DATASET_STORAGE=session
EVALUATION_DATASET_DEFAULT_RETENTION_DAYS=30
EVALUATION_DATASET_MAX_RETENTION_DAYS=365
EVALUATION_DATASET_MAX_PERSISTED_PER_NAMESPACE=100
EVALUATION_DATASET_CLEANUP_BATCH_SIZE=100

EVALUATION_RUN_HISTORY_STORAGE=disabled
EVALUATION_RUN_HISTORY_RETENTION_DAYS=
EVALUATION_RUN_HISTORY_MAX_PER_NAMESPACE=
EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE=
```

The value must be greater than zero and no more than 3,600 seconds. It bounds
the serialized run and discards its run-local cache on timeout. Size it for the
bounded built-in dataset and configured provider latency without treating it as
proof that remote provider work was cancelled.

The remaining settings independently bound session-local JSON imports: case
count, canonical decoded UTF-8 content, and `cases × repetitions` query work.
Accepted ranges are 1–500 cases, 1,024–1,048,576 decoded bytes, and 1–2,500
query executions. Keep these limits within the capacity and data-handling
policy of the deployment; threshold projections do not repeat provider work.
The requested `cases × repetitions` cap is checked for inline sources. Built-in
and persisted sources do not reapply that same check at the requested repetition
count; saving a dataset validates it at one repetition. Budget their requested
work explicitly rather than treating this setting as a universal run-admission cap.
The `session` dataset-storage default does not itself require PostgreSQL. A memory
live cache with session datasets, disabled history and memory coordination opens
no PostgreSQL pool. Production PostgreSQL coordination still requires that pool. Set dataset storage to `postgres` only
after configuring the database, retention, namespace capacity, backup, and
recovery policy.

Durable run history is independently disabled by default. Setting
`EVALUATION_RUN_HISTORY_STORAGE=postgres` requires `DATABASE_URL` plus explicit
positive values for retention days, per-namespace capacity, and cleanup batch
size. History retains terminal aggregate evidence only. Persisted-dataset run
history cannot outlive its source dataset, and deleting that dataset cascades
to retained history.

Run a TLS reverse proxy on the host and forward to `127.0.0.1:8080`. Public plaintext HTTP is unsupported.

## Access tokens

The backend stores only SHA-256 token digests in configuration. Users enter the original token at runtime. The browser keeps it in `sessionStorage`; it is not compiled into the frontend bundle.

Production deployments must use HTTPS. This digest scheme assumes high-entropy
random access tokens; do not use it to store ordinary user-chosen passwords.
Generate a token and digest with Python:

```bash
python -c "import hashlib,secrets; t=secrets.token_urlsafe(32); print('token='+t); print('sha256='+hashlib.sha256(t.encode()).hexdigest())"
```

Windows PowerShell 5.1 or later:

```powershell
$RandomBytes = New-Object byte[] 32
$Random = [Security.Cryptography.RandomNumberGenerator]::Create()
$Random.GetBytes($RandomBytes)
$Random.Dispose()
$Token = [Convert]::ToBase64String($RandomBytes)
$Bytes = [Text.Encoding]::UTF8.GetBytes($Token)
$Sha256 = [Security.Cryptography.SHA256]::Create()
$HashBytes = $Sha256.ComputeHash($Bytes)
$Sha256.Dispose()
$Hash = -join ($HashBytes | ForEach-Object { $_.ToString("x2") })
"token=$Token"
"sha256=$Hash"
```

Linux/macOS shell:

```bash
Token=$(openssl rand -base64 32)
Hash=$(echo -n "$Token" | openssl dgst -sha256 -hex | sed 's/^.* //')
echo "token=$Token"
echo "sha256=$Hash"
```

Set up an operator token as follows:

1. Generate a high-entropy random token using one of the commands above.
2. Calculate its lowercase SHA-256 digest.
3. Store only the digest in `AUTH_PRINCIPALS`.
4. Give the original token to the authorized operator through a secure
   channel. Never store the plaintext token in `AUTH_PRINCIPALS`.
5. Set `AUTH_MODE=token`.
6. Recreate both backend containers so they receive the changed environment.
7. Verify that `/api/v1/auth/config` reports authentication as required.
8. Test one wrong token, then authenticate with the valid original token.

The relevant environment values are:

```env
AUTH_MODE=token
AUTH_PRINCIPALS=[{"name":"ops-admin","token_sha256":"<64-lowercase-hex>","role":"admin","namespaces":["*"]},{"name":"team-reader","token_sha256":"<64-lowercase-hex>","role":"viewer","namespaces":["team-a"]}]
```

Keep the original tokens in a secret manager. Rotating a token means generating
a new token, replacing its digest, and recreating both backend containers.

For local Docker development, `docker-compose.dev.yml` reads both values from
`apps/server/.env`. After changing any value in that file, recreate the backend
container so Compose supplies the new environment. A plain container restart
does not reload changed environment values. An image rebuild is not required
for environment-only changes.

From the repository root in Windows PowerShell:

```powershell
docker compose `
  -f docker-compose.dev.yml `
  --profile pgvector `
  up -d --force-recreate backend
```

Verify the container and public authentication configuration:

```powershell
docker compose -f docker-compose.dev.yml --profile pgvector exec backend printenv AUTH_MODE
```

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/auth/config
```

Token mode reports:

```text
authentication_required
-----------------------
True
```

Test a rejected token and then the valid original token:

```powershell
$WrongHeaders = @{ Authorization = "Bearer intentionally-wrong-token" }
try {
    Invoke-RestMethod http://localhost:8000/api/v1/auth/session -Headers $WrongHeaders
} catch {
    $_.Exception.Response.StatusCode.value__
}

$ValidHeaders = @{ Authorization = "Bearer $Token" }
Invoke-RestMethod http://localhost:8000/api/v1/auth/session -Headers $ValidHeaders
```

### Progressive authentication lockouts

Only failed authentication attempts against `/api/v1/auth/session` advance
the lockout. The first three failures lock that client address for 30 seconds.
After the lock expires, three additional failures lock it for 60 seconds.
After that lock expires, three additional failures lock it for 3,600 seconds.
Later stages remain at 3,600 seconds. A successful authentication completely
resets the client to the initial stage.

`/api/v1/auth/config` is an unmetered authentication bootstrap endpoint.
Successful `/api/v1/auth/session` restoration is also excluded from the
ordinary `RATE_LIMIT` quota so browser refreshes do not consume application
request capacity. Invalid session attempts remain protected by the progressive
lockout above. Query, cache, benchmark, observability, and other limited API
routes continue to use the configured `RATE_LIMIT`.

Requests made during an active lock receive HTTP `429`, a `Retry-After`
header, and the standard `authentication_temporarily_locked` error. They do
not extend the lock or count as additional failures. Authentication failures
on other protected endpoints do not advance this state.

Production Compose stores lockout state in PostgreSQL, so the progression
survives backend restarts and is enforced across replicas using the trusted
client address. Local development defaults to process memory. If PostgreSQL
coordination is unavailable, session authentication returns HTTP `503`
instead of accepting attempts without lockout protection.

## Roles

| Role | Allowed operations |
|---|---|
| `viewer` | Read permitted cache metadata, threshold state, built-in datasets, namespace-authorized persisted dataset metadata/cases, and authorized retained run history/comparisons |
| `operator` | All viewer operations plus provider-backed queries, session-local validation, explicit dataset persistence, and evaluation runs |
| `admin` | All operator operations plus cache deletion, namespace clear, persisted dataset deletion, and retained run-history deletion |

Updating the global similarity threshold and reading process-wide runtime
metrics require an `admin` principal with `namespaces:["*"]`. A namespace
administrator remains limited to its authorized cache operations and receives
`403 Forbidden` from `/api/v1/metrics`.

Monitor mirrors these capabilities for clarity: Viewers cannot submit live
queries, Operators and Admins can, and only wildcard Admins see the global
threshold Apply action. These controls are usability boundaries; the API role
dependencies remain authoritative.

## Namespace authorization

Every principal receives one or more namespaces. A non-global principal cannot query, inspect, delete, or clear another namespace.

For cache list, statistics and clear operations, omission is scoped to a sole
restricted namespace; multiple restricted namespaces must select one. Query
JSON instead defaults an omitted namespace to `default`, which must be
authorized. Principals with multiple namespaces must select one for creation.
Only `namespaces:["*"]` can list globally. The
`*` marker is authorization scope, never persisted ownership: wildcard
administrators must provide a concrete namespace for persisted dataset create,
delete, built-in history retention, retained-history deletion, and Monitor
queries. Monitor preselects a sole namespace, requires a choice when several
are authorized, and validates wildcard users' explicit concrete namespace.
Persisted runs inherit their source dataset namespace.

Scoped history access preserves non-disclosure: foreign and missing retained
run IDs use the same not-found behavior.

This is server-side authorization. Frontend controls are not treated as a security boundary.

## Semantic-cache integrity before exposure

Namespace authorization prevents cross-namespace cache poisoning, but it does
not create trust tiers inside one namespace. Any Operator allowed to seed a
namespace can influence later semantic reuse there through the generated
response.

Before exposing Semantix to untrusted clients:

1. Give Operator tokens only the namespaces they require; use separate
   namespaces for workloads with different trust boundaries.
2. Measure entity changes, numeric drift, negation, and benign paraphrases with
   the deployed embedding model and proposed threshold.
3. Keep threshold changes under wildcard-Admin review; do not treat a clean
   finite run as universal poisoning immunity.
4. Use Private or Bypass cache for requests that must not read or seed shared
   semantic state, and use Refresh and write only when forced provider
   generation and a cache write are intentional.
5. Clear the affected cache after changing embedding space or prompt
   normalization, and delete suspect entries through the authorized Cache
   Inspector workflow.

See [Cache policies](../guides/cache-policies.md#cache-poisoning-and-integrity)
and the repository [threat model](../../SECURITY.md#semantic-cache-poisoning-threat-model).

## Proxy-aware client addresses

The frontend gateway replaces incoming `X-Forwarded-For` with the peer address it observes. The limiter trusts that gateway-provided address only when the backend's direct peer belongs to `TRUSTED_PROXY_CIDRS`. Direct callers outside those CIDRs cannot override their identity with a header.

The production Compose network uses `172.28.0.0/24`, so the default is:

```env
TRUSTED_PROXY_CIDRS=["172.28.0.0/24"]
```

Docker Desktop can present both a host TLS proxy and another host process to the gateway as the same bridge peer (`172.28.0.1` in the verified production network). Source CIDR alone cannot authenticate the host proxy. By default, the gateway ignores incoming `X-Forwarded-For`, `X-Real-IP`, and `Forwarded` for identity and forwards its observed peer; users behind that host proxy then share a rate-limit bucket.

To retain per-client identity, keep the published port bound to loopback and configure the host TLS proxy to **replace** incoming `X-Forwarded-For` with its actual client TCP peer address. It must also replace `X-Semantix-Host-Proxy-Token` with a private, randomly generated 64-character hexadecimal token; never pass either header through from the external caller. For a host Nginx proxy, the upstream location needs the equivalent of:

```nginx
proxy_pass http://127.0.0.1:8080;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Semantix-Host-Proxy-Token "<private-64-hex-token>";
```

Generate the token with `python -c "import secrets; print(secrets.token_hex(32))"`. Put one map entry in a private file outside the repository, using the **exact gateway-observed source of the host proxy** and the same token:

```nginx
"172.28.0.1|<private-64-hex-token>" $http_x_forwarded_for;
```

Set `SEMANTIX_HOST_PROXY_RULE_FILE` to that file's absolute host path before starting production Compose. Compose mounts it read-only over the gateway's disabled rule file. Verify the observed source on the target Docker host; `172.28.0.1` is the tested Docker Desktop value, not a portable assumption. Keep the rule file private and untracked. The gateway accepts the proxy-supplied address only when **both** the source and token match. It strips the token, `X-Real-IP`, and `Forwarded` before the backend. Missing or mismatched trust falls back to the gateway-observed peer; malformed forwarded addresses fail closed in the backend. An untrusted intermediate proxy remains the host proxy's observed client unless separately authenticated there. Keep `TRUSTED_PROXY_CIDRS` limited to the backend's actual gateway network; do not add broad public ranges.

Production Compose uses PostgreSQL as the shared authority for per-client,
per-route `RATE_LIMIT` buckets. It keeps `/auth/session` outside this ordinary
quota; the progressive lockout above applies there. Local development defaults
to process memory. If PostgreSQL coordination is unavailable, limited routes
return HTTP `503` instead of falling back to independent replica counters.
Expired rate buckets and stale lockout rows are cleaned up opportunistically.
Cross-replica query coalescing remains local by design.

The global similarity threshold is also stored in PostgreSQL in production.
`SIMILARITY_THRESHOLD` seeds it only when the coordination table is empty;
later Admin updates survive backend restarts and are read by every replica.
Use the authorized threshold API to change a persisted value.
`GET /ready` checks this authority and returns `503` if it is unavailable.

See the [multi-replica readiness audit](multi-replica-readiness.md) for the initial state inventory and rollout gates, followed by the shared coordination and two-replica verification results.

## Two-replica operation

The gateway uses [the upstream file](../../apps/web/upstream.prod.conf) and Docker DNS to discover both backends. Keep both replicas on identical auth, provider, embedding, cache, and coordination settings. Production uses the shared pgvector cache and PostgreSQL coordination. A gateway `/ready` response describes the selected replica; inspect each one before and after a rollout:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend curl -f http://backend-a:8000/ready
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend curl -f http://backend-b:8000/ready
```

For a planned restart, copy `apps/web/upstream.prod.conf` to a private host file and set `SEMANTIX_UPSTREAM_FILE` to its absolute path before starting Compose. Remove the target replica's `server` line from that mounted file, validate and reload Nginx, and wait for its admitted requests to finish. Then stop or recreate that replica. Reinsert its line only after its direct `/ready` check succeeds, and validate/reload again:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend nginx -t
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T frontend nginx -s reload
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend-a
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --no-deps --force-recreate backend-a
```

Repeat for `backend-b` only after `backend-a` is serving traffic. The gateway is configured for retries on connection errors and timeouts; this does not guarantee that every failed request is replayed or that no gateway errors occur. See the [production runtime audit](production-runtime-audit.md) for residual failures and evidence limits. Its API read timeout is 330 seconds and the backend stop grace is 360 seconds, covering the default 300-second evaluation limit; size them together if that limit changes. The gateway access log records status, upstream address, URI path, and duration without query strings, prompts, tokens, or responses.

Each replica owns its HTTP client, PostgreSQL pool, evaluation run lock and runtime metrics. Coalescing and `/api/v1/metrics` remain process-local; aggregate replica-labelled observations externally. Shared cache, datasets/history when enabled, and PostgreSQL coordination persist independently of replica lifetimes.

At the default pool maximum of five connections per replica, the two backends can use up to ten PostgreSQL connections, plus migration, maintenance, and monitoring connections. Reserve server headroom accordingly. Provider calls, retries, and evaluation runs can also occur on both replicas at once. Set provider quotas against the aggregate demand before using real providers; the mock-provider CI burst measures concurrency but does not establish a remote-provider quota.

For a bounded two-to-three-replica managed rollout, use the [autoscaling readiness policy](autoscaling-readiness.md).

## URL configuration validation

`ALLOWED_ORIGINS` entries must be bare HTTP or HTTPS origins: a host
(including `localhost` or a bracketed IPv6 host) and an optional valid port.
A single trailing slash is normalized away. Credentials, paths, parameters,
queries, fragments, and malformed ports are rejected.

`DATABASE_URL` continues to accept PostgreSQL DSNs with optional valid ports,
query parameters, IPv6 hosts, and percent-encoded credentials. Malformed ports
now fail during startup validation. This intentionally rejects configurations
that were previously accepted even though they were not usable URLs.

## Request-size limits

The frontend gateway enforces `client_max_body_size 64k`. The backend independently enforces `MAX_REQUEST_BODY_BYTES=65536` before JSON parsing.

The ASGI limit handles both declared `Content-Length` and streamed/chunked request bodies. Oversized requests return HTTP `413` with the standard JSON error structure.

Keep the proxy and backend values aligned. The backend limit is the final authority when requests bypass or are forwarded by another proxy.

Imported evaluation datasets remain session-local unless an authorized
Operator explicitly saves a successfully validated document. Validation and
inline run requests must fit the global request limit in addition to the
decoded-content, case, and workload limits above. Persistent storage adds
metadata and ordered cases only; it stores no run evidence or generated
responses.

## Liveness and readiness

`GET /health` confirms the process can answer and reports only configured provider types. It is cheap and unrate-limited.

`GET /ready` checks active cache statistics, the persistent evaluation dataset
repository when configured, and the coordination threshold when coordination is
configured. Handled cache, dataset or coordination storage failures return HTTP
`503` with the `not_ready` error. Other failures use the normal error boundary.

The successful response reports configured `cache_backend` and
`evaluation_dataset_storage`, without an independent history-readiness result.
Enabling durable run history does not add a direct run-history repository probe.
The endpoint does not call hosted embedding or generation providers and cannot
prove every later read or write will succeed. A gateway response covers the
selected replica; use the direct checks in [Two-replica operation](#two-replica-operation)
for rollout decisions.

`GET /api/v1/diagnostics` is separate from those public probes. It requires a
wildcard global Admin and returns only reviewed provider categories, safe
evaluation fingerprints, cache readiness, normalization status, bounded
evaluation limits, persistence booleans, and the application version for one
backend process. It never returns credentials, URLs, model names, namespace or
dataset identities, prompts, responses, run IDs, or raw settings. Keep this
route behind the same authenticated proxy boundary as the other `/api` routes.

## Database roles and migrations

The production database has two roles. Use URL-safe random passwords for the Compose example, or percent-encode credentials before placing them in a PostgreSQL URL.

- `POSTGRES_MIGRATION_USER` owns extension/schema migration work;
- `POSTGRES_RUNTIME_USER` receives selected schema usage and table DML privileges, plus read-only access to the official cache migration ledger. These grants do not create migration authority or revoke any preexisting privileges.

The initialization script creates the runtime login. The one-shot `migrate`
service connects with `MIGRATION_DATABASE_URL`, applies migrations for the
enabled cache, evaluation, and coordination features, grants runtime privileges,
and exits. Explicit cache setup enables pgvector and applies server legacy
migration `0001`, then initializes the package-owned official cache schema and
ledger. Legacy entries are preserved and are not adopted into that store.
Evaluation migration `0002` adds dataset and case tables; migration `0003` adds
the aggregate history tables `evaluation_runs` and `evaluation_run_thresholds`.
The evaluation bundle contains both migrations, while dataset/history enablement
and runtime grants remain independent. Coordination migration `0004` adds rate
buckets, session-auth lockout state, and the global similarity threshold. Both
backends start only after the one-shot job succeeds. Do not run privileged
migrations independently on each replica. This job does not build providers or
verify their credentials.

For official-store ownership, explicit cache setup and preserved legacy PostgreSQL
records, see the [server storage transition](../guides/platform-storage.md#postgresql-setup-and-legacy-transition).

The migration runner records and verifies SHA-256 SQL-content checksums;
a recorded non-null mismatch fails setup. A legacy `0001` row without a checksum
is backfilled only after the implemented relation/required-column-name checks;
these do not prove complete schema equivalence. Later checksum-less versions
fail closed and require operator review. Production backends in `external` mode
do not rerun server migrations. Ordinary cache startup validates the official
package-owned layout and ledger instead.

One PostgreSQL pool is shared by whichever PostgreSQL-backed Semantix features
are enabled: pgvector cache, persisted evaluation datasets, durable run
history, and PostgreSQL coordination. A memory live cache can use either
evaluation persistence feature independently; pgvector cache can keep datasets
session-only and history disabled.

The backend receives only `DATABASE_URL` for the runtime role and sets:

```env
DATABASE_MIGRATION_MODE=external
```

Local development keeps:

```env
DATABASE_MIGRATION_MODE=auto
```

Development `auto` applies enabled PostgreSQL coordination/evaluation migrations;
it does not initialize the official cache schema. Follow the explicit storage
setup guide before starting a persistent cache.

Never pass the migration DSN to the production backend service.

Changing Compose password variables does not update roles in an existing
volume. Follow [Operations and recovery](recovery.md) for credential rotation,
backup, restore, destructive rebuild, migration rollback, and incident response.

## Static server behavior

The production frontend image:

- runs `npm ci` and `npm run build` in a Node build stage;
- copies only `dist/` into an unprivileged Nginx runtime;
- provides SPA fallback for client-side routes;
- compresses text assets;
- gives fingerprinted assets immutable caching;
- prevents caching of `index.html`;
- adds CSP, frame, referrer, MIME-sniffing, and permissions headers.

`vite preview` is not used as a production server.

## Validation

```bash
docker compose -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.dev.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml build
```

Verify the production runtime:

```bash
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
curl -i http://127.0.0.1:8080/cache
```

The `/cache` request must return the SPA entry document. An API request without a token must return `401`. A viewer token must not delete or globally clear cache data. Inspect the running frontend container and confirm its user is non-root.
