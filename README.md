<div align="center">

<h1>🧠 Semantix</h1>

<p><strong>Async semantic caching for Python.</strong></p>

<p>Memory or PostgreSQL storage. Your generation flow stays yours.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-555555?logo=python&amp;logoColor=FFD43B&amp;labelColor=3776AB" alt="Python 3.11–3.14" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639" alt="MIT license" /></a>
</p>

<p><sub><a href="README.md">EN</a> · <a href="docs/translation/id/README.ID.md">ID</a></sub></p>

</div>

<p align="center">
  <a href="#install-and-run">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#verified-ai-providers">Providers</a> ·
  <a href="#storage">Storage</a> ·
  <a href="#performance">Benchmarks</a> ·
  <a href="packages/cache/benchmarks/reuse_quality/README.md">Reuse quality</a>
</p>

**semantix-cache** is the intended first public PyPI product. Its 0.1.0 API
is async-only and runs in your Python process. No Semantix server, web UI,
Docker or PostgreSQL is required.

## Install and run

> [!NOTE]
> **0.1.0 is not yet published.** The public install command below applies after publication.

```bash
python -m pip install semantix-cache
```

Before publication, install a built candidate wheel from the directory containing it:

```bash
python -m pip install semantix_cache-0.1.0-py3-none-any.whl
```

See the [package guide](packages/cache/README.md) for local builds and the full
contract. The minimal package depends on NumPy and Pydantic; provider networking
and PostgreSQL drivers are optional.

This credential-free example runs as a script. The toy vectors demonstrate the
integration, not language understanding or semantic-match quality. Replace the
embedder and generation function with your application's existing async integrations.

```python
import asyncio
from semantix_cache import AsyncSemanticCache, EmbeddingSpace, MemoryStore

class DemoEmbedder:
    embedding_space = EmbeddingSpace(identity="demo-v1", dimensions=2)

    async def embed(self, text: str) -> tuple[float, float]:
        return (1.0, 0.0) if "weather" in text.lower() else (0.0, 1.0)

async def generate(prompt: str) -> str:
    return "Completed answer for: " + prompt

async def main() -> None:
    embedder = DemoEmbedder()
    async with MemoryStore(embedding_space=embedder.embedding_space) as store:
        async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
            prompt = "weather today"
            miss = await cache.resolve(prompt, namespace="demo", generate=generate)
            hit = await cache.resolve(prompt, namespace="demo", generate=generate)
            assert miss.provider_called and miss.cache_written
            assert hit.cache_hit and hit.generation_skipped
            print(hit.response, "cache_hit=", hit.cache_hit)

asyncio.run(main())
```

The first resolve generates and writes; the second reports a confirmed cache hit
and skips generation. Reuse the store/cache across requests: creating a new
MemoryStore loses its process-local entries. Context managers close the facade
and store; the application owns any other injected resources.

## At a glance

| Aspect | Summary |
| --- | --- |
| **Runtime** | Async, in-process Python |
| **Storage** | MemoryStore or optional PostgreSQL/pgvector |
| **Generation** | Your own async callable |

## Why Semantix?

Reuse completed responses inside an existing async application while keeping
prompt construction, model selection, RAG, tools and approval logic in your code.
Choose a similarity threshold and retention policy explicitly, inspect the returned
hit/miss evidence, and add persistence when your application needs it.

## How it works

For the default NORMAL policy, the embedded path is:

```mermaid
flowchart LR
    A[Your app] --> B[AsyncSemanticCache]
    B --> C[Embed]
    C --> D{Confirmed cache hit?}
    D -->|Yes| H[Return hit]
    D -->|No| G[Generate, validate and write]
    G --> R[Return miss]
```

Eligible candidates pass validation and atomic TTL/revision confirmation before
a hit is returned.

The application owns the embedder, generator and store lifetimes. A CacheStore can
be MemoryStore, optional PgVectorStore or your custom implementation. Other policies
control reads/generation/writes; opt-in coalescing adds waiting and each follower's
own confirmed lookup. See the [cache contract](packages/cache/README.md#contract).

## Semantic cache behavior

Matching uses validated embeddings and cosine similarity, rather than requiring
identical strings. The inclusive threshold defaults to 0.92; evaluate false matches
for your own model and workload. Even a repeated prompt goes through embedding and
lookup. Namespace and EmbeddingSpace isolate compatible cache data; they do not
replace application authorization.

Version the namespace when response context, model, permissions or approval policy
changes. Keep embedding identity stable for a particular model/revision/dimensions/
preprocessing combination. Matching dimensions alone do not establish compatibility.
TTL starts at the write and does not extend on hits. See
[policies, TTL and matching](packages/cache/README.md#contract).

See [context identity and migration](docs/context-identity-and-migration.md) for
model/tenant/knowledge/output scopes, embedding revisions and safe migration recipes.

## Key capabilities

- **Async API** — AsyncSemanticCache with explicit CachePolicy, CacheResult and CacheHit evidence.
- **Memory** — Bounded MemoryStore with exact float64 cosine scoring, TTL and confirmed-hit LRU.
- **Persistence** — Optional PostgreSQL/pgvector with explicit schema initialization.
- **Extensions** — Maintained embedding/generation adapters and structural custom integration ports.
- **Coalescing** — Opt-in NORMAL cold misses within one cache instance and event loop.

## Performance

Historical development measurements compared the optimized base `ee915140` with
opt-in coalescing in three fresh alternating control/treatment pairs per store.
The workload used 256 requests, concurrency 128, two compatible prompts and a
200 ms deterministic generation delay. Generation calls fell from 256 to 2;
embedding calls remained 256.

| Store | Burst P50, disabled → enabled | Burst P95, disabled → enabled |
| --- | ---: | ---: |
| MemoryStore | 294.095 → 434.127 ms | 316.949 → 458.839 ms |
| PgVectorStore | 916.670 → 941.012 ms | 1366.900 → 1087.602 ms |

These are median per-trial burst percentiles, not isolated follower timings.

Provider-work reduction can increase cold-follower latency, as the MemoryStore
numbers show. Sharing requires equivalent attested inputs, bounded admission and
successful persistence/confirmation. It is disabled by default and does not promise
universal latency, duplicate elimination or dollar savings. See the
[complete tradeoff](packages/cache/README.md#measured-provider-work-and-latency-tradeoff).
Optional server measurements are retained below and describe a different workload.

<details>
<summary>Measurement environment and methodology</summary>

Conditions: Windows 11, Ryzen 9 5900HX/16 logical CPUs/about 32 GiB RAM; Python
3.14.6, NumPy 2.4.6, Pydantic 2.13.5; 384 dimensions, 500 seeded candidates,
capacity 5,000, threshold 0.92, TTL 3,600 s; child BLAS threads=1. PostgreSQL
17.10/pgvector 0.8.5 used a local four-CPU/2-GiB container, asyncpg 0.31.0 and
pool eight. Setup/warmup/cleanup were excluded; measured requests had no errors.

Reproduce with the [coalescing experiments](packages/cache/benchmarks/COALESCING.md)
and [runtime benchmark methodology](packages/cache/benchmarks/README.md).

</details>

## Production behavior

The facade borrows injected resources. Adapters borrow their HTTP clients;
PgVectorStore.connect owns its pool, while an injected pool is borrowed. Drain or
cancel active work before closing: busy resources raise CacheBusyError. Total
deadlines are finite, cancellation propagates, and no automatic generation retry
is added. Caller-configured transports/callbacks remain the caller's responsibility.

Lookup/write failures raise; generated output followed by a failed write is not a
successful resolve. Typed errors and bounded result evidence are documented in the
[package guide](packages/cache/README.md#extension-and-ownership).
Coalescing needs explicit `coalescing_key` attestation; it does not infer equivalent
ContextVars/closures or coordinate across processes. Followers confirm their own
hits. Changing that key alone does not invalidate stored answers. Read the
[coalescing safety rules](packages/cache/README.md#optional-cold-miss-coalescing).

Optional [numeric coalescing evidence](docs/embedded-observability.md) is collected
only with `collect_coalescing_metrics=True`. General instrumentation remains application-owned.

Documented `AsyncSemanticCache` usage is covered by the package's
[0.1.x compatibility policy](packages/cache/README.md#01x-compatibility).

## Verified AI Providers

The maintained OpenAI, Gemini, and Hugging Face adapters were exercised against
real provider APIs on **2026-10-05**, including embedding, generation, and an
`AsyncSemanticCache` + MemoryStore miss → generate → write → confirmed-hit flow.
Generation was skipped on the repeated-prompt hit; the checks cover the models
listed in the [provider guide](docs/embedded-providers.md#010-verification).

| Provider | Embeddings | Generation | Verification |
| --- | --- | --- | --- |
| OpenAI | Yes | Yes | ✅ Live verified |
| Gemini | Yes | Yes | ✅ Live verified |
| Hugging Face | Yes | Yes | ✅ Live verified |
| Ollama | Yes | Yes | Previously exercised locally; current release evidence incomplete |
| Anthropic | No native embedding API | Yes | ⚠️ Contract-tested; first-party live verification pending |

**Public extension path verified.** Independent HTTPX integrations for OpenAI,
Gemini, and Hugging Face used only Semantix's public `AsyncSemanticCache`
extension interfaces, without built-in provider adapters or private helpers.
Each completed a live miss → generate → write → confirmed-hit flow.

> **Anthropic:** The generation adapter is covered by deterministic contract and
> regression tests, but was not live-verified against the first-party Anthropic API
> for 0.1.0. It has no native embedding API; pair generation with any supported
> embedding adapter. Contributions using your own first-party Anthropic API access
> are welcome for verification, reproducible compatibility reports, and focused
> fixes with regression coverage when a defect is reproduced.

Built-in adapters live in `semantix_cache.adapters`, outside minimal root imports.
Choose models and embedding-space identity explicitly and supply a borrowed HTTPX
client. The optional HTTP extras do not install provider SDKs. See
[embedded providers and custom integrations](docs/embedded-providers.md) for
configuration and the custom-provider path.

Provider APIs evolve independently of Semantix. I intend to keep the maintained
integrations current; reproducible compatibility reports and focused fixes are
welcome. Never include API keys, credentials, or raw provider responses in issues,
commits, logs, or fixtures.

## Storage

Start with MemoryStore for bounded process-local state. Optional
`semantix_cache.stores.pgvector.PgVectorStore` persists across processes/restarts
using an application-controlled PostgreSQL database. Provision the vector extension
and initialize its separate marked cache schema explicitly; normal cache operations
perform no DDL. Runtime operations enforce ownership markers, version and migration
checksums, not a complete catalog fingerprint. Protect out-of-band schema changes.

See [embedded storage and user databases](docs/embedded-storage.md) for least-privileged
runtime access, pool ownership, migrations and custom stores. pgvector stores float32
vectors; near-threshold scores can differ from MemoryStore's float64 scoring.

## Extension points

Supply a structural EmbeddingAdapter (`embedding_space` and async `embed`), an async
GenerationCallable returning approved completed text, or a structural CacheStore.
No subclass or registry is required. Streaming/RAG/tool flows can use `get`/`set`
around their final approved text; Semantix does not run those application workflows.

## Examples

- [Custom embedding and generation](packages/cache/examples/custom_integration.py).
- [Custom CacheStore](packages/cache/examples/custom_store.py) and the [developer conformance kit](docs/cache-store-conformance.md).
- [Persistent customer support](packages/cache/examples/persistent_support.py).
- [Public API and source layout](packages/cache/src/README.md).

## Repository components

| Path | Component |
| --- | --- |
| `packages/cache/` | Primary semantix-cache embedded library; first intended PyPI product |
| `apps/server/` | Optional official self-hosted FastAPI server |
| `apps/web/` | Optional official web/workbench for inspecting and evaluating server cache decisions |
| `packages/client/` | Maintained optional/reference semantix-client HTTP client; not a first-release PyPI target |

The optional server/workbench is a full-stack laboratory for inspecting cache
decisions, evaluating thresholds and measuring provider work. Its namespace-scoped
authorization and hardened two-replica deployment are server features, not embedded
prerequisites. Operational tooling lives in `ops/`; developer tooling in `scripts/`.

<details>
<summary>Optional server/workbench: tour, Docker setup and deployment evidence</summary>

![Semantix Monitor showing a cache hit, similarity evidence, and the skipped provider call](docs/assets/screenshots/monitor-decision.png)

*Actual Semantix UI with Hugging Face providers and example prompts.*

---

### ✨ Optional server workspaces

| Workspace | Purpose |
|---|---|
| **Monitor** | Submit namespace-scoped policy probes and inspect cache hits, misses, latency, matched prompts, and similarity evidence |
| **Cache Inspector** | Search entries, inspect metadata, delete records, clear namespaces safely |
| **Evaluations** | Measure precision, recall, false hits, false misses, inspect filtered case evidence, and export reproducible runs |
| **Observability** | Track process metrics and inspect safe, read-only runtime diagnostics for evaluation reproducibility |

### Product tour

The optional server workbench inspects its connected server cache, evaluates
ordered runs, and diagnoses that server. It does not observe arbitrary embedded
application caches. The local Hugging Face demo exposes the same workspaces. The screenshots
below show the current UI; select any image to open the original resolution.

#### Cache Inspector

Search stored prompts and inspect entry age, hit counts, expiry, and cache
metadata without exposing raw embeddings.

[![Cache Inspector showing safe example cache entries with hit counts and TTL](docs/assets/screenshots/cache-inspector.png)](docs/assets/screenshots/cache-inspector.png)

#### Evaluations

Run an isolated dataset and inspect measured cache behavior, provider calls,
latency, and classification outcomes. Bookmark `/evaluations?view=runs`,
`?view=datasets`, `?view=history`, or `?view=reuse-quality` to reopen the selected
view. Reuse quality displays [reviewed static library evidence and methodology](packages/cache/benchmarks/reuse_quality/README.md),
with calibration and held-out results separate from ordered server runs. These
synthetic results do not establish production quality or a universally safe threshold.

[![Evaluations showing results for the built-in semantic safety dataset](docs/assets/screenshots/evaluations-results.png)](docs/assets/screenshots/evaluations-results.png)

#### Observability

Inspect safe runtime diagnostics, provider categories, matching fingerprints,
storage readiness, and other reproducibility signals.

[![Observability showing runtime diagnostics and provider readiness](docs/assets/screenshots/observability-diagnostics.png)](docs/assets/screenshots/observability-diagnostics.png)

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

### 🚀 Quick start

#### Requirements

Install Git and Docker Desktop, or Docker Engine with Compose.

#### 1. Clone the repository

Linux or macOS:

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

#### 2. Configure local development

For a zero-key persistent setup, use these values in `apps/server/.env`:

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
[Getting started](docs/guides/getting-started.md) and `apps/server/.env.example`.

#### 3. Start the complete development stack

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d
```

This single command starts:

- the React frontend with Vite hot reload;
- the FastAPI backend with Uvicorn reload;
- PostgreSQL with pgvector;
- automatic development database migrations.

#### 4. Open the application

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

### 🔌 Providers

Embedding and generation providers are selected independently.

| Provider | Embeddings | Generation | Credentials |
|---|:---:|:---:|:---:|
| Hugging Face | Yes | Yes | Required |
| OpenAI | Yes | Yes | Required |
| Anthropic | No native embedding API | Yes (contract-tested; live pending) | Required |
| Gemini | Yes | Yes | Required |
| Ollama | Yes | Yes | Not required locally |
| Mock | Yes | Yes | Not required |

Only settings required by the selected capabilities are validated. See
[Providers](docs/guides/providers.md) for configuration examples and networking
notes.

### 🛡️ Development and hardened deployment

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

### 📈 Performance and scalability

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

### 📊 Semantic cache benchmark

A local run on July 19, 2026 used the eight-query **Quick semantic safety set**,
Hugging Face providers, typo normalization, an empty isolated cache, and a
`0.92` threshold:

| Provider calls avoided | Average hit | Average miss | Precision / Recall / F1 |
|---:|---:|---:|---:|
| **4 of 8 (50%)** | **330.3 ms** | **3772.7 ms** | **1.0 / 1.0 / 1.0** |

This is one dated measurement, not a performance guarantee. See
[Benchmarking](docs/guides/benchmarking.md) for the dataset, run details, and
limitations.

### ⚠️ Important limitations

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

</details>

Use semantix-client only with an already-running compatible Semantix server.
It remains maintained, is not a first-release PyPI target, and does not provide
the embedded engine.

### Reference HTTP client

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

[Full Python SDK guide →](packages/client/README.md)

## Documentation

The [documentation index](docs/README.md) separates embedded and server guides.

| Start here | Use it for |
| --- | --- |
| [Cache package guide](packages/cache/README.md) | Embedded quick start, policies, ownership and canonical compatibility |
| [Embedded providers](docs/embedded-providers.md) | Maintained adapters and custom embedding/generation |
| [Context identity and migration](docs/context-identity-and-migration.md) | Explicit scopes, embedding revisions and safe migration |
| [Embedded storage](docs/embedded-storage.md) | Memory, optional PostgreSQL and user-owned databases |
| [Examples](packages/cache/examples/) | Application-controlled generation and stores |
| [Reviewed reuse quality](packages/cache/benchmarks/reuse_quality/README.md) | Semantic baseline, lexical controls, calibration/held-out split and evidence limitations |
| [Benchmark methodology](packages/cache/benchmarks/README.md) | Reproducible local runtime workloads and limitations |
| [Server getting started](docs/guides/getting-started.md) | Optional server environment files and Docker workflows |
| [HTTP client guide](packages/client/README.md) | Typed client for an already-running compatible server |
| [Server architecture](docs/reference/architecture.md) | Feature ownership and request flow |
| [Hardened deployment](docs/operations/deployment.md) | Server auth, TLS, database roles and validation |

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md), [cache contributor checks](packages/cache/README.md#separate-products)
and [server/web development](docs/guides/development.md).

<details>
<summary>Repository layout and server/web development checks</summary>

### 🗂️ Project structure

```text
semantix/
├── apps/
│   ├── server/
│   └── web/
├── packages/
│   ├── cache/
│   │   ├── src/semantix_cache/
│   │   └── tests/
│   └── client/
│       ├── src/semantix_client/
│       └── tests/
├── ops/
│   ├── ci/
│   ├── load-testing/
│   ├── postgres/
│   └── supply-chain/
├── scripts/
│   ├── linux/
│   └── windows/
├── docs/
├── .github/
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.prod.yml
└── README.md
```

`apps/server` is the official self-hosted FastAPI application; `apps/web` is
the official web/workbench. `packages/cache` contains the primary reusable
**semantix-cache** library, the intended first public PyPI distribution.
`packages/client` contains the maintained optional/reference **semantix-client**
HTTP client, which is not currently required for that first release. `ops` holds
operational tooling and `scripts` holds repository/developer tooling.

The backend and frontend use feature-first ownership. See
[Architecture](docs/reference/architecture.md) for the runtime flow and package
boundaries.

### ✅ Quality checks

#### Backend cache setup

Backend tool caches are centralized under `apps/server/.cache/`. Enable the Python
bytecode cache redirect before running backend commands.

From the repository root:

Windows PowerShell:

```powershell
. .\apps\server\scripts\windows\enable_cache.ps1
```

Linux or macOS:

```bash
source apps/server/scripts/linux/enable_cache.sh
```

When already inside `apps/server/`:

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
pytest use their cache paths from `apps/server/pyproject.toml`.

To remove generated caches and editable-install metadata:

```powershell
.\apps\server\scripts\windows\clean_artifacts.ps1
```

For Linux or macOS:

```bash
bash apps/server/scripts/linux/clean_artifacts.sh
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
cd apps/server
uv sync --locked --extra dev
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
npm run format:check
npm run imports:check
npm run test:coverage
npm run build
npm run bundle:check
```

See [Development](docs/guides/development.md) for local toolchains, architecture
rules, and contribution steps.

</details>

## Security

Applications own authorization, generation context, credentials, transport security
and provider data handling. Namespace separation is not authorization. See
[SECURITY](SECURITY.md) for reporting and server deployment boundaries, plus the
[embedded provider](docs/embedded-providers.md) and [storage](docs/embedded-storage.md)
guides for caller-owned resource and database responsibilities.

## 📄 License

Licensed under the [MIT License](LICENSE).
