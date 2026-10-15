# Getting started

This guide covers the **optional backend/dashboard application**. For the primary
embedded Python library, use the [package quick start](../../packages/cache/README.md#run-from-source);
embedded users need neither Docker nor the official server.

Semantix has separate development and hardened deployment paths. The development stack is for one trusted developer on a local machine. The hardened stack is the starting point for shared or public deployment and must sit behind TLS.

## Prerequisites

Install Git, a local Docker Desktop or Docker CLI/Engine 23+ (API 1.42+) with Compose 2.20+, and Python 3.11–3.14 for the recommended development launcher. The launcher uses only Python's standard library; backend dependencies stay in Docker. [uv](https://docs.astral.sh/uv/guides/scripts/) can invoke it without a host backend environment. The advanced Docker-only path and hardened deployment do not require host Python. Hosted providers require their own credentials.

## Local development

Clone the repository and create the backend environment file:

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix
cp apps/server/.env.example apps/server/.env
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix
Copy-Item apps\server\.env.example apps\server\.env
```

For a credential-free mock development configuration, set:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
EVALUATION_DATASET_STORAGE=session
EVALUATION_RUN_HISTORY_STORAGE=disabled
COORDINATION_BACKEND=memory
AUTH_MODE=disabled
```

For hosted or local inference, choose the embedding and generation providers in
[Providers](providers.md) before starting the stack. Mock responses are example
output, not production answers. The first Docker build can download images and
dependencies; the mock providers make no AI API calls.

### Recommended: development launcher

From the repository root, after configuring `apps/server/.env`:

```bash
python scripts/dev.py up
```

Or, with uv (no root project or backend dependency installation):

```bash
uv run --no-project scripts/dev.py up
```

Use `uv run --no-project --python 3.14 scripts/dev.py up` to select an
installed supported interpreter explicitly. Both forms work from PowerShell and
Linux/macOS shells; Docker must use a local Engine/Desktop context. Unset
`DOCKER_HOST` overrides and select that context with Docker's usual context tools.

The launcher reads Compose's resolved backend environment, validates settings,
and selects services from the cache **and** independent PostgreSQL feature
settings. Memory-only starts no databases. It builds development images, performs
separate setup only for volumes it creates and verifies in that invocation,
validates existing storage, waits for backend `/ready`, then starts the frontend.
The printed dashboard origin must match `ALLOWED_ORIGINS`. Keep configuration
unchanged during startup.

For PostgreSQL or Redis, complete the configuration below first. Existing volumes
and external URLs receive validation only: the launcher never resets data,
rotates an existing password, adopts an unmarked schema, or creates a missing
binding in existing storage. No fallback or automatic replay of failed setup occurs.

### Advanced: direct Docker Compose

For the memory configuration above, Git and Docker are sufficient:

```bash
docker compose -f docker-compose.dev.yml up --build -d --wait --wait-timeout 120 backend frontend
```

Compose 2.20+ can also use `docker compose up --build -d --wait --wait-timeout 120 backend frontend`.
These commands do not derive profiles from `CACHE_BACKEND` or provision storage.
Persistent storage requires the matching profile and successful
[explicit operator setup](#development-with-persistent-storage) before applications start.

All published development ports bind to `127.0.0.1` by default:

| Service | Address |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |

Open the frontend and run a Monitor query. The [product tour](../../README.md#product-tour)
shows the current Cache Inspector, Evaluations, and Observability views. For
requests from a Python application, continue with the [Python SDK](../../packages/client/README.md).

The development frontend image installs Node dependencies and runs the Vite
development server with HMR; it does not compile production frontend assets.
`VITE_API_BASE_URL` is supplied to that development server at runtime. The
hardened frontend image performs the production build described later in this
guide. For reliable bind-mount updates when native notifications are
unavailable, the development stack polls for frontend and backend source
changes once per second. Vite ignores generated coverage output, and Uvicorn
reloads only for changes under `apps/server/app`. The hardened stack is unaffected.

Changes normally appear within about one second. If they do not, confirm that
Docker Desktop can share the repository drive, then recreate the affected
service. Inspect idle usage with `docker stats --no-stream`. Do not expose the
development stack to an untrusted network.

### Development with persistent storage

The dashboard supports `memory`, `pgvector` and `redis`. SQLite and MySQL
remain embedded-package choices, not dashboard backends. PostgreSQL is also
required by `EVALUATION_DATASET_STORAGE=postgres`,
`EVALUATION_RUN_HISTORY_STORAGE=postgres` or `COORDINATION_BACKEND=postgres`,
even with memory or Redis cache; configure their existing retention/capacity
requirements in `apps/server/.env`.

#### PostgreSQL runtime credentials

Generate your own runtime password; it does **not** come from an AI provider:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep that output private. Put it in the untracked `apps/server/.env`, replacing
`replace-runtime-password` below:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix_runtime:replace-runtime-password@postgres:5432/semantix
DATABASE_MIGRATION_MODE=external
```

`semantix_runtime` is the restricted application login. For a volume created by
this launcher, it creates that role with the configured password, then runs the
existing migrations using separate bootstrap authority. The normal backend never
receives that migration authority. The local Compose bootstrap account is
`semantix`; do not use it as `DATABASE_URL`'s runtime user.

The generated URL-safe password needs no additional encoding. For an existing
password containing `@`, `:`, `/`, `#`, `%` or other reserved URL characters,
percent-encode the username/password components with
`urllib.parse.quote(value, safe="")`; do not encode the entire URL.
Never commit credentials, paste them into issues, expose them in logs, or put
them in `VITE_*`/frontend configuration. Keep operator URLs and initialization
credentials out of the backend `.env`.

For an existing role, the password must match the database's current password.
Changing `.env` does not rotate it. Missing/placeholder URLs fail configuration
validation; incorrect credentials or incomplete schemas fail storage validation.
Review the actual account and back up existing data rather than deleting a volume
or rerunning privileged setup blindly. The launcher deliberately leaves an
already-created but incompletely provisioned database for explicit recovery.

For advanced direct Compose setup, follow the ordered
[PostgreSQL walkthrough](../../README.md#optional-postgresql-persistence).
It covers separate runtime/migration accounts, explicit setup, preserved legacy
data and starting the applications only after setup succeeds.

#### Redis configuration

For the project's local standalone Redis service:

```env
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

The launcher initializes the selected binding only in a newly created owned
Redis volume. Existing bindings are validated without changing their descriptor
or contents. The local profile retains AOF and `noeviction`. Other Redis URLs
require prior explicit setup and their existing ACL/TLS policy; the launcher
does not convert `rediss` to plaintext. See
[Redis operator setup](platform-storage.md#redis-setup-permissions-and-recovery).

#### Shutdown and recovery

```bash
docker compose -f docker-compose.dev.yml --profile pgvector --profile redis down
```

This keeps named volumes. Do not add `--volumes` unless you deliberately intend
to delete your data. Routine startup uses the same launcher command.

Setup and readiness have finite budgets. A failed/interrupted setup can leave
partially initialized storage; stopping a client cannot prove that server-side DDL
stopped or rolled back. Review uncertain outcomes before operator recovery; it is never automatically repaired or retried.
A project-specific Docker lock serializes cooperating launcher invocations.
After a hard interruption, first confirm no launcher or setup job is active.
Inspect only names, state and ownership labels—not full container environments:

```bash
docker ps -a --filter "name=<project>-dev-"
docker inspect --format '{{json .Config.Labels}}' <container-id>
docker inspect --format '{{.State.Running}}' <container-id>
```

Verify the Compose project/checkout labels on setup jobs and the
`com.semantix.dev-startup.project` / `.checkout` labels on the stopped lock.
Their `com.semantix.dev-startup` owner tokens must match. Only then stop/remove
the abandoned setup job and its stopped lock
container by ID. Do not remove volumes. If a job cannot be confirmed stopped,
retain the lock and resolve Docker/resource ownership first. Review partial
database state separately with explicit operator authority; creating a new
project name is not recovery of existing data.

Existing local volumes require either a matching development-service mount or
a prior launcher ownership marker for this checkout. A pre-launcher volume left
after `compose down`, or a moved checkout, may lack that proof. Review it using
its original known development configuration and the advanced setup workflow;
the launcher does not adopt, relabel or reset unknown volumes.

Changing `BACKEND_PORT` also configures Vite's API URL. If changing
`FRONTEND_PORT`, include the corresponding loopback browser origin in
`ALLOWED_ORIGINS`. The launcher checks readiness and configuration; it does
not certify hosted providers, production TLS, or prevent a Docker administrator
from modifying resources concurrently. Hardened deployment remains separate.

### Local toolchains

Backend:

```bash
cd apps/server
uv sync --locked --extra dev
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows PowerShell activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before
using the local backend workflow. The checked-in lock keeps local, CI, and
container dependency resolution aligned.

Frontend:

```bash
cd apps/web
npm ci
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `apps/web/.env` for local Vite development.

## Hardened deployment

The hardened stack uses:

- a compiled frontend served by a non-root Nginx image;
- two backend replicas (`backend-a` and `backend-b`) behind the gateway, with no published backend ports;
- a database on an internal Docker network with no host port;
- token authentication, roles, and namespace scopes;
- proxy-aware rate limiting;
- reverse-proxy and ASGI request-size limits;
- separate migration and runtime database roles;
- unrate-limited liveness and dependency-aware readiness checks.

Create the deployment environment file:

```bash
cp .env.production.example .env.production
```

Generate strong database passwords and access tokens, replace every placeholder, then start:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

The frontend gateway binds to `127.0.0.1:8080` by default. Terminate TLS with a host reverse proxy and forward traffic to that loopback address. Do not publish the backend or database ports.

The hardened stack uses the separate `semantix-prod` Compose project and does not reuse the development PostgreSQL volume.

See [Hardened deployment](../operations/deployment.md) for token hashing, role
configuration, proxy trust, database privileges, readiness behavior, and
validation.

## Health checks

`GET /health` is a cheap process liveness check and is not rate-limited.

`GET /ready` checks active cache statistics, the configured persistent
evaluation dataset catalog, and PostgreSQL threshold coordination when enabled.
It returns `503` for handled storage failures. It does not directly probe the
optional run-history repository or hosted AI providers.

## Shutdown and volumes

Development:

```bash
docker compose -f docker-compose.dev.yml down
```

Hardened deployment:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Named volumes are preserved. Adding `--volumes` permanently removes PostgreSQL data.

## Quality checks

Backend:

```bash
cd apps/server
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd apps/web
npm ci
npm run lint
npm run imports:check
npm run test
npm run build
```

Container validation:

```bash
docker compose -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.dev.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml build
```
