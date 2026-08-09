# Getting started

Semantix has separate development and hardened deployment paths. The development stack is for one trusted developer on a local machine. The hardened stack is the starting point for shared or public deployment and must sit behind TLS.

## Prerequisites

Install Git and Docker Desktop or Docker Engine with Compose. Hosted providers also require credentials for the selected provider capabilities.

## Local development

Clone the repository and create the backend environment file:

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix
cp backend/.env.example backend/.env
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix
Copy-Item backend\.env.example backend\.env
```

For a network-free development configuration, set:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
AUTH_MODE=disabled
```

Start the explicitly named development stack:

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

Docker Compose 2.20 or newer can also use the compatibility entry point, which loads the same development stack:

```bash
docker compose up --build -d
```

All published development ports bind to `127.0.0.1` by default:

| Service | Address |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |

The development frontend image installs Node dependencies and runs the Vite
development server with HMR; it does not compile production frontend assets.
`VITE_API_BASE_URL` is supplied to that development server at runtime. The
hardened frontend image performs the production build described later in this
guide. For reliable bind-mount updates when native notifications are
unavailable, the development stack polls for frontend and backend source
changes once per second. Vite ignores generated coverage output, and Uvicorn
reloads only for changes under `backend/app`. The hardened stack is unaffected.

Changes normally appear within about one second. If they do not, confirm that
Docker Desktop can share the repository drive, then recreate the affected
service. Inspect idle usage with `docker stats --no-stream`. Do not expose the
development stack to an untrusted network.

### Development with pgvector

Set the backend database values:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_MIGRATION_MODE=auto
```

Start the profile:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

The database is available to host-side tools at `127.0.0.1:5433` by default. The development role intentionally owns migrations and runtime operations.

The development commands keep the repository's existing `semantix` Compose project name, so an existing local `pgvector_data` volume continues to be used.

### Local toolchains

Backend:

```bash
cd backend
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
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend/.env` for local Vite development.

## Hardened deployment

The hardened stack uses:

- a compiled frontend served by a non-root Nginx image;
- an internal backend that is not published directly;
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

`GET /ready` checks the active cache dependency. The memory backend returns immediately. The pgvector backend performs a bounded cache-statistics query and returns `503` when the database is unavailable.

Readiness does not call hosted AI providers and therefore does not consume provider quota.

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
cd backend
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd frontend
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
