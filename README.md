<p align="center">
  <sub><a href="docs/translation/id/README.ID.md">ID</a> · <a href="README.md">EN</a></sub>
</p>

<div align="center">

# 🧠 Semantix

### Observe, measure, and tune semantic caching instead of treating it like a black box

Semantix is a full-stack semantic-cache laboratory for inspecting cache
decisions, measuring provider savings, evaluating similarity thresholds, and
comparing replaceable AI and storage providers.

Self-host it for multiple applications and users: namespace-scoped access keeps
their cache data separate, while PostgreSQL + pgvector persists entries across
restarts. The hardened deployment routes traffic across two backend replicas.

<sub>Monitor · Cache Inspector · Evaluations · Observability</sub>

</div>

![Semantix Monitor showing a cache hit, similarity evidence, and the skipped provider call](docs/assets/screenshots/monitor-decision.png)

*Actual Semantix UI with deterministic mock providers and example prompts.*

---

## ✨ What Semantix provides

| Workspace | Purpose |
|---|---|
| **Monitor** | Submit namespace-scoped policy probes and inspect cache hits, misses, latency, matched prompts, and similarity evidence |
| **Cache Inspector** | Search entries, inspect metadata, delete records, clear namespaces, and manage the threshold |
| **Evaluations** | Measure precision, recall, false hits, false misses, inspect filtered case evidence, and export reproducible runs |
| **Observability** | Track process metrics and inspect safe, read-only runtime diagnostics for evaluation reproducibility |

## Product tour

The local mock-provider demo also shows the other workspaces. Select a preview to see the full-size screenshot.

| Workspace | Current UI |
|---|---|
| **Cache Inspector** — Search stored prompts and inspect entry age, hits, and expiry without showing embeddings. | <a href="docs/assets/screenshots/cache-inspector.png"><img src="docs/assets/screenshots/cache-inspector.png" alt="Cache Inspector listing safe example entries with hit counts and TTL" width="320"></a> |
| **Evaluations** — Run an isolated dataset and review measured hit rate, provider calls, and classification outcomes. | <a href="docs/assets/screenshots/evaluations-results.png"><img src="docs/assets/screenshots/evaluations-results.png" alt="Evaluations showing results for the built-in quick semantic safety set" width="320"></a> |
| **Observability** — Read process-local request, cache, provider, and latency metrics. | <a href="docs/assets/screenshots/observability-metrics.png"><img src="docs/assets/screenshots/observability-metrics.png" alt="Observability showing mock-provider traffic, cache, and latency metrics" width="320"></a> |

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
- deterministic mock providers for safe local testing;
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
Reusing a suitable response avoids another generation call and can reduce
latency and provider cost; evaluate false matches for your own workload.

## 🐍 Python SDK

External Python applications can use the independently installable
`semantix-client` distribution through the public HTTP API.
Python code imports it as `semantix_client`. It provides typed synchronous and
asynchronous clients without installing or importing Semantix backend internals.

The package is not currently published to PyPI; install it from a built wheel or
directly from the repository as described in the full guide.

```python
from semantix_client import SemantixClient

with SemantixClient(base_url="http://localhost:8000") as client:
    result = client.query("Explain semantic caching", namespace="default")

print(result.response, result.cache_hit)
```

[Full Python SDK guide →](sdk/README.md)

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
| **Hardened** | Shared or public two-replica deployment | Token authentication, namespace roles, internal backend/database networks, external migrations, TLS proxy required |

Create `.env.production` from `.env.production.example` only when preparing a
hardened deployment:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Do not start it until every placeholder has been replaced. See
[Hardened deployment](docs/operations/deployment.md) for token generation,
trusted proxies, database roles, TLS, and validation.

## 📈 Performance and scalability

The hardened stack balances backend replicas over shared PostgreSQL + pgvector
state. PostgreSQL also coordinates deployment-wide rate limits, session lockout,
and cache threshold changes. Replica failover, draining, and controlled scaling
have been exercised.

In a local Docker test on the documented hardware, the two-replica stack
completed a **10-minute cache-heavy run with 1,000 virtual users**: 195,961
requests (about 324 RPS), P95 latency 186 ms, and zero HTTP 4xx, HTTP 5xx,
transport, or sampled readiness failures. The workload used deterministic mock
providers and 2–4 seconds of think time per virtual user. These figures are
specific to that machine and workload, not a production capacity guarantee.

Controlled generation-heavy tests at 1,000 virtual users improved from about
167 RPS and 4.86 s P95 with one replica to 270 RPS and 1.95 s P95 with two.
PostgreSQL connection and lock pressure limits extrapolation to more replicas.
See [Capacity testing](docs/operations/load-testing.md#capacity-baseline-on-the-local-docker-host)
for hardware, methodology, all profiles, failures, and limitations. The Python
SDK was also exercised through the load-balanced gateway.

## 📊 Semantic cache benchmark

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
│   ├── src/
│   └── tests/
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
- Runtime metrics, diagnostics, and request coalescing are process-local;
  production rate limiting uses shared PostgreSQL coordination.
- The hardened stack balances two backend replicas; it is not a complete
  multi-tenant platform or a general-purpose autoscaling system.
- Mock providers are for tests, demonstrations, and UI development.
- Evaluation sweeps reuse one measured run; alternate thresholds are
  projections, not ordered replays or automatic threshold recommendations.

## 📚 Documentation

The [documentation index](docs/README.md) groups the full guides by purpose.

| Start here | Use it for |
|---|---|
| [Getting started](docs/guides/getting-started.md) | Local setup, environment files, and Docker workflows |
| [Providers](docs/guides/providers.md) | Hosted, local, and mock provider configuration |
| [Python SDK](sdk/README.md) | Install and use the typed public HTTP client |
| [Architecture](docs/reference/architecture.md) | Runtime flow, feature ownership, and package boundaries |
| [Hardened deployment](docs/operations/deployment.md) | Authentication, TLS, database roles, and production validation |
| [Capacity testing](docs/operations/load-testing.md#capacity-baseline-on-the-local-docker-host) | Load profiles, hardware, one/two-replica results, and the 1,000-VU soak |

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
