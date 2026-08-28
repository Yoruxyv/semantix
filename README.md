<p align="center">
  <sub><a href="/docs/translation/id/README.ID.md">ID</a> · <a href="README.md">EN</a></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/React-19.2.8-61DAFB?logo=react&logoColor=white" alt="React 19.2.8">
  <img src="https://img.shields.io/badge/Vite-7.3.6-646CFF?logo=vite&logoColor=white" alt="Vite 7.3.6">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white" alt="Python 3.11 through 3.14">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL with pgvector">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Auth-Scoped%20Tokens-D4A15A" alt="Scoped token authentication">
  <img src="https://img.shields.io/badge/Docker-Dev%20%2B%20Hardened-2496ED?logo=docker&logoColor=white" alt="Development and hardened Docker stacks">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?logo=opensourceinitiative&logoColor=white" alt="MIT License">
</p>

<div align="center">

# 🧠 Semantix

### Observe, measure, and tune semantic caching instead of treating it like a black box

Semantix is a full-stack semantic-cache laboratory for inspecting cache
decisions, measuring provider savings, evaluating similarity thresholds, and
comparing replaceable AI and storage providers.

<sub>Monitor · Cache Inspector · Evaluations · Runtime Observability</sub>

</div>

---

## ✨ What Semantix provides

| Workspace | Purpose |
|---|---|
| **Monitor** | Submit namespace-scoped policy probes and inspect cache hits, misses, latency, matched prompts, and similarity evidence |
| **Cache Inspector** | Search entries, inspect metadata, delete records, clear namespaces, and manage the threshold |
| **Evaluations** | Measure precision, recall, false hits, false misses, inspect filtered case evidence, and export reproducible runs |
| **Observability** | Track process metrics and inspect safe, read-only runtime diagnostics for evaluation reproducibility |

Core capabilities:

- independent embedding and generation providers;
- memory or persistent PostgreSQL + pgvector storage;
- TTL, LRU eviction, namespaces, private requests, and read/write policies;
- role-aware Monitor controls, private trace minimization, and live-hit links to
  authorized Cache detail;
- request coalescing for identical concurrent misses;
- optional typo-aware prompt normalization;
- global-admin-only runtime diagnostics with safe provider categories,
  fingerprints, readiness, and evaluation limits;
- token roles and namespace authorization for hardened deployments;
- deterministic mock providers for safe local testing.
- run-local evaluation caches, complete confusion-matrix accounting, and
  configurable bounded frozen-candidate threshold sweeps;
- versioned session-local JSON evaluation datasets with provider-free preview,
  strict validation, and no browser persistence;
- optional namespace-authorized PostgreSQL evaluation dataset catalog with
  explicit save, bounded retention, and no stored run results.

## ⚙️ How it works

```text
Prompt
  │
  ▼
Normalize matching text
  │
  ▼
Create embedding
  │
  ▼
Search the active namespace and embedding space
  │
  ├── score >= threshold ──► return cached response
  │
  └── score < threshold ───► call provider ─► store response
```

Semantix returns a cached response only when the nearest compatible entry meets
the active similarity threshold. See
[Cache policies](docs/guides/cache-policies.md) for the complete rules.

## 🐍 Python SDK

External Python applications can use the independently installable
[`semantix-client`](sdk/python/README.md) package through the public HTTP API.
Python code imports it as `semantix_client`. It provides typed synchronous and
asynchronous clients without installing or importing Semantix backend internals.

## 🚀 Quick start

### Requirements

Install Git and Docker Desktop, or Docker Engine with Compose.

### 1. Clone the repository

Linux or macOS:

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

### 2. Configure local development

For a zero-key persistent setup, use these values in `backend/.env`:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384

CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_MIGRATION_MODE=auto
EVALUATION_DATASET_STORAGE=postgres
EVALUATION_DATASET_DEFAULT_RETENTION_DAYS=30

AUTH_MODE=disabled
AUTH_PRINCIPALS=[]
TRUSTED_PROXY_CIDRS=[]
MAX_REQUEST_BODY_BYTES=65536
```

These authentication and proxy values are intentionally empty or disabled for
trusted local development. Do not use the development configuration for a
public deployment.

To use Hugging Face, OpenAI, Anthropic, Gemini, or Ollama, see
[Providers](docs/guides/providers.md). For every environment option, see
[Getting started](docs/guides/getting-started.md) and `backend/.env.example`.

### 3. Start the complete development stack

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

This single command starts:

- the React frontend with Vite hot reload;
- the FastAPI backend with Uvicorn reload;
- PostgreSQL with pgvector;
- automatic development database migrations.

### 4. Open the application

| Service | Address |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |
| Runtime metrics | <http://localhost:8000/api/v1/metrics> |
| Runtime diagnostics | <http://localhost:8000/api/v1/diagnostics> |
| PostgreSQL from the host | `127.0.0.1:5433` |

Useful commands:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector ps
docker compose -f docker-compose.dev.yml --profile pgvector logs -f backend
docker compose -f docker-compose.dev.yml --profile pgvector down
```

`down` keeps named volumes. Adding `--volumes` deletes the local PostgreSQL
data.

## 🔌 Providers

Embedding and generation providers are selected independently.

| Provider | Embeddings | Generation | Credentials |
|---|:---:|:---:|:---:|
| Hugging Face | Yes | Yes | Required |
| OpenAI | Yes | Yes | Required |
| Anthropic | No | Yes | Required |
| Gemini | Yes | Yes | Required |
| Ollama | Yes | Yes | Not required locally |
| Mock | Yes | Yes | Not required |

Only settings required by the selected capabilities are validated. See
[Providers](docs/guides/providers.md) for configuration examples and networking
notes.

## 🛡️ Development and hardened deployment

| Mode | Intended use | Main behavior |
|---|---|---|
| **Development** | One trusted local developer | Hot reload, loopback ports, disabled authentication, automatic migrations |
| **Hardened** | Shared or public single-instance deployment | Token authentication, namespace roles, internal backend/database networks, external migrations, TLS proxy required |

Create `.env.production` from `.env.production.example` only when preparing a
hardened deployment:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Do not start it until every placeholder has been replaced. See
[Hardened deployment](docs/operations/deployment.md) for token generation,
trusted proxies, database roles, TLS, and validation.

## 📊 Measured benchmark

A local run on July 19, 2026 used the eight-query **Quick semantic safety set**,
Hugging Face providers, typo normalization, an empty isolated cache, and a
`0.92` threshold:

| Provider calls avoided | Average hit | Average miss | Precision / Recall / F1 |
|---:|---:|---:|---:|
| **4 of 8 (50%)** | **330.3 ms** | **3772.7 ms** | **1.0 / 1.0 / 1.0** |

This is one dated measurement, not a performance guarantee. See
[Benchmarking](docs/guides/benchmarking.md) for the dataset, run details, and
limitations.

## ✅ Quality checks

### Backend cache setup

Backend tool caches are centralized under `backend/.cache/`. Enable the Python
bytecode cache redirect before running backend commands.

From the repository root:

Windows PowerShell:

```powershell
. .\backend\scripts\windows\enable_cache.ps1
```

Linux or macOS:

```bash
source backend/scripts/linux/enable_cache.sh
```

When already inside `backend/`:

Windows PowerShell:

```powershell
. .\scripts\windows\enable_cache.ps1
```

Linux or macOS:

```bash
source scripts/linux/enable_cache.sh
```

The leading dot in PowerShell and `source` in Bash are required so
`PYTHONPYCACHEPREFIX` remains active in the current terminal. Ruff, mypy, and
pytest use their cache paths from `backend/pyproject.toml`.

To remove generated caches and editable-install metadata:

```powershell
.\backend\scripts\windows\clean_artifacts.ps1
```

For Linux or macOS:

```bash
bash backend/scripts/linux/clean_artifacts.sh
```

Platform-specific automation lives in `windows/` and `linux/` directories.
Shared Compose overlays remain beside those directories under `ops/ci/`.
For example, the development health smoke has matching entry points:

Windows PowerShell:

```powershell
.\ops\ci\windows\dev-healthcheck-smoke.ps1
```

Linux or macOS:

```bash
bash ops/ci/linux/dev-healthcheck-smoke.sh
```

The smoke entry points generate ephemeral database passwords and authentication
tokens for each run unless the corresponding environment variables are already
set. Credentials are not stored in the scripts.

Repository-wide developer reports are available through paired platform
helpers:

```powershell
.\scripts\windows\get_total_lines.ps1
.\scripts\windows\find_undocumented_files.ps1
```

```bash
bash scripts/linux/get_total_lines.sh
bash scripts/linux/find_undocumented_files.sh
```

They inspect Git-tracked and unignored project files, so ignored dependencies,
caches, virtual environments, and build output are excluded automatically.

Backend:

```bash
cd backend
uv sync --locked --extra dev
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

See [Development](docs/guides/development.md) for local toolchains, architecture
rules, and contribution steps.

## 🗂️ Project structure

```text
semantix/
├── backend/
├── frontend/
├── sdk/
│   └── python/
├── ops/
│   ├── ci/
│   ├── load-testing/
│   ├── postgres/
│   └── supply-chain/
├── scripts/
│   ├── linux/
│   └── windows/
├── docs/
├── docker-compose.dev.yml
├── docker-compose.prod.yml
└── README.md
```

The backend and frontend use feature-first ownership. See
[Architecture](docs/reference/architecture.md) for the runtime flow and package
boundaries.

## ⚠️ Important limitations

- Semantic similarity is probabilistic and must be evaluated for each model and
  workload.
- Hosted providers may receive prompts and can introduce cost, latency, and
  external data-handling requirements.
- Runtime metrics, diagnostics, rate limiting, and request coalescing are
  process-local.
- The hardened stack is a single-instance baseline, not a complete multi-tenant
  or multi-replica platform.
- Mock providers are for tests, demonstrations, and UI development.
- Evaluation sweeps reuse one measured run; alternate thresholds are
  projections, not ordered replays or automatic threshold recommendations.

## 📚 Documentation

The [documentation index](docs/README.md) groups the full guides by purpose.

| Start here | Use it for |
|---|---|
| [Getting started](docs/guides/getting-started.md) | Local setup, environment files, and Docker workflows |
| [Providers](docs/guides/providers.md) | Hosted, local, and mock provider configuration |
| [Python SDK](sdk/python/README.md) | Install and use the typed public HTTP client |
| [Architecture](docs/reference/architecture.md) | Runtime flow, feature ownership, and package boundaries |
| [Hardened deployment](docs/operations/deployment.md) | Authentication, TLS, database roles, and production validation |

## 🤝 Contributors

Made with ❤️ by:

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/Yoruxyv">
        <img src="https://github.com/Yoruxyv.png?size=96" width="96" alt="Hans avatar"><br>
        <b>Hans</b>
      </a><br>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/Kasanee-Teto">
        <img src="https://github.com/Kasanee-Teto.png?size=96" width="96" alt="Louis avatar"><br>
        <b>Louis</b>
      </a><br>
    </td>
  </tr>
</table>

## 📄 License

Licensed under the [MIT License](LICENSE).
