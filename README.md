<div align="center">

<h1>🧠 Semantix</h1>

<p><strong>Async semantic caching for Python.</strong></p>

<p>Memory, SQLite, MySQL, PostgreSQL, Redis or Valkey storage. Your generation flow stays yours.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-555555?logo=python&amp;logoColor=FFD43B&amp;labelColor=3776AB" alt="Python 3.11–3.14" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639" alt="MIT license" /></a>
</p>

<p><sub><a href="README.md">EN</a> · <a href="docs/translation/id/README.ID.md">ID</a></sub></p>

</div>

<p align="center">
  <a href="#install-and-run">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#compatibility-and-supported-backends">Compatibility</a> ·
  <a href="#optional-dashboard--quick-start">Dashboard</a> ·
  <a href="docs/README.md">Documentation</a>
</p>

**semantix-cache** is the primary embedded Python library and the intended first
public PyPI product. Its 0.1.0 API is async-only and runs in your Python process.
No Semantix server, web UI, Docker or PostgreSQL is required.

| Use Semantix | Start here |
| --- | --- |
| **Embedded Python (primary)** | [Source quick start](#install-and-run); no Docker or official server |
| **Backend/dashboard (optional)** | [Dashboard quick start](#optional-dashboard--quick-start); optional local application |
| **PostgreSQL persistence** | [Embedded setup](docs/embedded/storage.md#new-postgresql-database) or [dashboard setup](#optional-postgresql-persistence); explicit initialization required |

## Install and run

> [!NOTE]
> **0.1.0 is not yet published to PyPI.** Use the GitHub source or a locally built
> wheel. The distribution is named **semantix-cache**; Python imports **semantix_cache**.

Install Git, Python 3.11–3.14 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Start from a new checkout, or use your existing checkout and enter `packages/cache`.

Bash (Linux/macOS):

```bash
git clone https://github.com/Yoruxyv/semantix.git
cd semantix/packages/cache
```

Windows PowerShell:

```powershell
git clone https://github.com/Yoruxyv/semantix.git
Set-Location semantix/packages/cache
```

Then run these commands in either shell:

```bash
uv sync --locked
uv run --no-sync python -m examples.custom_integration
```

The maintained [custom integration example](packages/cache/examples/custom_integration.py)
uses `AsyncSemanticCache`, `EmbeddingSpace` and `MemoryStore` with no API key,
Docker, server or database. It exits silently on success and raises if the first
resolve does not generate/write or the second does not confirm a hit and skip
generation. Its deterministic two-dimensional vectors verify API wiring, **not
semantic understanding or match quality**. `provider_called` means the local
application generation callable ran; this example makes no provider API calls.
Setup downloads Python dependencies; the example itself runs offline.

For an independent Python project, see [local source and wheel installation](packages/cache/README.md#use-in-another-python-project).
The minimal package depends on NumPy and Pydantic; provider networking and persistent
store drivers are optional. The backend/dashboard is a separate optional application;
embedded usage does not pass through it.

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
| **Storage** | MemoryStore, local SQLite, optional MySQL, PostgreSQL/pgvector, Redis or Valkey |
| **Generation** | Your own async callable |

## Compatibility and supported backends

The embedded `semantix-cache` package supports **CPython 3.11–3.14**.
Backend links below lead to setup requirements and complete certification details.

| Backend | Supported server/runtime | Python driver | Availability |
| --- | --- | --- | --- |
| [MemoryStore](docs/embedded/storage.md#choose-a-store) | In-process, non-durable; no external database | Included in the minimal core; no database driver | Embedded + optional server/dashboard |
| [SQLiteStore](docs/embedded/storage.md#sqlite-local-file-persistence) | Thread-capable linked SQLite **>=3.51.3, except withdrawn 3.52.0**, or exact upstream WAL-patched **3.44.6 / 3.50.7** | Python's standard-library `sqlite3`; no extra driver package | Embedded + single-process server |
| [MySQLStore](docs/embedded/mysql.md#verified-compatibility) | Runtime: MySQL Community **8.4.x**; CI-certified: **8.4.11 / 8.4.12** | `[mysql]`: exact PyMySQL **1.2.1, 1.2.2 or 1.2.3** | Embedded + official server |
| [PgVectorStore](docs/embedded/storage.md#verified-postgresql-combinations) | Verified PostgreSQL / pgvector: **16.15 / 0.8.7**, **17.10 / 0.8.5**, **18.6 / 0.8.7** | `[pgvector]`: `asyncpg>=0.31,<=0.32.0`; certified **0.31.0 / 0.32.0** in different CI combinations | Embedded + optional server/dashboard |
| [RedisStore — Redis Open Source](docs/embedded/redis.md#supported-versions) | Admitted minor families and patch floors: **7.4.x >=7.4.11; 8.2.x >=8.2.10; 8.4.x >=8.4.7; 8.6.x >=8.6.7; 8.8.x >=8.8.3; 8.10.x >=8.10.2** | `[redis]`: exact redis-py **7.4.1**, exact **8.0.1**, or stable **8.1.x** | Embedded + optional server/dashboard |
| [RedisStore — Valkey](docs/embedded/redis.md#valkey-912) | Separate server product; exact **Valkey 9.1.2** | Same RedisStore and `[redis]` extra; verified redis-py **8.1.0**, no Valkey-specific dependency | Embedded certified; existing server `redis` path (see below) |

**Runtime-admitted** versions pass the implementation's compatibility policy.
**CI-verified** combinations are the exact targets exercised in maintained tests,
listed in the linked guides. Admission does not mean every server, extension,
driver, Python, architecture, OS or managed-service combination has been tested.
The PostgreSQL targets above are **not runtime minimum versions**.

Development locks retain asyncpg **0.31.0**, PyMySQL **1.2.3** and redis-py
**8.1.0**. The Redis dependency resolver range is broader than runtime admission;
see the [driver policy](docs/embedded/redis.md). redis-py **8.0.1** does not imply
Redis **8.0** server support. MySQL 8.0/9.x, MariaDB and managed variants are
outside the MySQL verified boundary.

For SQLite, use trusted upstream builds or verify the vendor's WAL-fix provenance:
a version number alone does not authenticate a binary. Valkey certification pairs
**9.1.2 / redis-py 8.1.0 / Linux x86-64 / CPython 3.14**, with additional local
Windows-client evidence. Other Valkey releases, drivers and platforms are not
individually certified. TLS, managed-service and failover limits remain specific
to each guide; Redis/Valkey data-file migration remains unverified.

The [optional server/dashboard](docs/guides/platform-storage.md) accepts only
`CACHE_BACKEND=memory`, `pgvector`, `redis`, `sqlite` or `mysql`. SQLite requires a native
single-process server on trusted local disk with explicit setup; bundled Compose
is unsupported. MySQL requires explicit setup, restricted runtime credentials and verified TLS;
see [server MySQL configuration](docs/guides/platform-storage.md#mysql-explicit-setup-and-owned-connections).
Valkey uses the existing `redis` path, with no separate ValkeyStore or `valkey`
selector. An end-to-end Valkey dashboard deployment has not been separately certified.

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
be MemoryStore, SQLiteStore, optional MySQLStore/PgVectorStore/RedisStore or your custom implementation. Other policies
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

See [context identity and migration](docs/embedded/context-identity-and-migration.md) for
model/tenant/knowledge/output scopes, embedding revisions and safe migration recipes.

### Prompt normalization

Normalization transforms text for embedding-based lookup and newly computed write
embeddings. Generation and cache entries retain the application prompt under the
existing canonicalization rules. This can help matching; it does not verify answer
correctness.

The optional **server** corrects common English typos and accidental word splits with
SymSpell, disabled by default. Enable it at startup with
`PROMPT_TYPO_CORRECTION_ENABLED=true` and configure distance with
`PROMPT_TYPO_MAX_EDIT_DISTANCE=2`. It generally preserves capitalization: typo
correction is not case-insensitive matching, and capitalization alone guarantees
neither a hit nor a miss. These settings are not editable from the dashboard.

The standalone **semantix-cache** package exposes a synchronous `prompt_normalizer`
callable; installing it alone does not install SymSpell or enable the server's
correction behavior. See the [package hook](packages/cache/README.md#matching-text-preprocessing)
and [normalization guide](docs/guides/prompt-typo-normalization.md) for examples,
configuration and limitations. Preprocessing changes require compatible storage
isolation and a coordinated transition; follow the
[identity and migration guide](docs/embedded/context-identity-and-migration.md).

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

Optional [numeric coalescing evidence](docs/embedded/observability.md) is collected
only with `collect_coalescing_metrics=True`. General instrumentation remains application-owned.

Documented `AsyncSemanticCache` usage is covered by the package's
[0.1.x compatibility policy](packages/cache/README.md#01x-compatibility).

## Verified AI Providers

Hosted provider examples are optional, require your own credentials and may incur
charges. Start with the credential-free MemoryStore workflow above.

The maintained OpenAI, Gemini, and Hugging Face adapters were exercised against
real provider APIs on **2026-10-05**, including embedding, generation, and an
`AsyncSemanticCache` + MemoryStore miss → generate → write → confirmed-hit flow.
Generation was skipped on the repeated-prompt hit; the checks cover the models
listed in the [provider guide](docs/embedded/providers.md#010-verification).

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
[embedded providers and custom integrations](docs/embedded/providers.md) for
configuration and the custom-provider path.

Provider APIs evolve independently of Semantix. I intend to keep the maintained
integrations current; reproducible compatibility reports and focused fixes are
welcome. Never include API keys, credentials, or raw provider responses in issues,
commits, logs, or fixtures.

## Storage

Start with MemoryStore for bounded process-local state. See the
[compatibility table](#compatibility-and-supported-backends) for admitted versions,
verified targets and embedded versus server availability.

For local persistence, `semantix_cache.stores.sqlite.SQLiteStore` owns a dedicated
file and worker with explicit setup. Check the thread-capable linked runtime and
WAL-fix provenance; Python's version alone is insufficient. Run
`uv run --no-sync python -m examples.sqlite_cache` from `packages/cache` for a
credential-free miss/write/hit and reopen check. See
[SQLite setup and limits](docs/embedded/storage.md#sqlite-local-file-persistence)
for the bounded complete float64 scan, file ownership and cancellation restrictions.

Optional `semantix_cache.stores.mysql.MySQLStore` uses the local wheel's `[mysql]`
extra, an owned worker, verified TLS and explicit setup on a dedicated MySQL
Community 8.4.x database. Hosted CI covers both certified server releases and all
three admitted PyMySQL versions in the combinations listed in the
[MySQL guide](docs/embedded/mysql.md#verified-compatibility). See that guide for
least-privileged grants, the locked schema verifier, exact float64 search, deadlines,
uncertain COMMIT and bounded failed-construction recovery.

`semantix_cache.stores.redis.RedisStore` uses `[redis]` for Redis Open Source or
exact Valkey 9.1.2. Both require explicit binding initialization and a directly
addressed writable standalone primary with **noeviction**. Operators own persistence,
backups, TLS and recovery; Cluster, Sentinel, replica reads and automatic failover
are unsupported. See [Redis and Valkey setup and limits](docs/embedded/redis.md).

Optional
`semantix_cache.stores.pgvector.PgVectorStore` persists across processes/restarts
using an application-controlled PostgreSQL database. Provision the vector extension
and initialize its separate marked cache schema explicitly; normal cache operations
perform no DDL. Runtime operations enforce ownership markers, version and migration
checksums, not a complete catalog fingerprint. Protect out-of-band schema changes.

`PgVectorStore.connect()` can raise typed errors and returns no usable store on
failure. Applications own recovery or fail-startup decisions; see
[PostgreSQL connection failures](docs/embedded/storage.md#connections-cancellation-and-failures).

See [embedded storage and user databases](docs/embedded/storage.md) for least-privileged
runtime access, pool ownership, migrations and custom stores. pgvector stores float32
vectors; near-threshold scores can differ from MemoryStore's float64 scoring.

## Extension points

Supply a structural EmbeddingAdapter (`embedding_space` and async `embed`), an async
GenerationCallable returning approved completed text, or a structural CacheStore.
No subclass or registry is required. Streaming/RAG/tool flows can use `get`/`set`
around their final approved text; Semantix does not run those application workflows.

## Examples

- [Custom embedding and generation](packages/cache/examples/custom_integration.py).
- [Custom CacheStore](packages/cache/examples/custom_store.py) and the [developer conformance kit](docs/embedded/cache-store-conformance.md).
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

<a id="-quick-start"></a>

## Optional Dashboard — Quick Start

<a id="requirements"></a>

Install Git, Python 3.11–3.14, and Docker Desktop or Docker CLI/Engine 23+
(API 1.42+) with Compose 2.20+. Start the local Docker engine. Host Python is
only needed for the development launcher; backend dependencies stay in Docker.

<a id="1-clone-the-repository"></a>

Use the [checkout above](#install-and-run) and run from the **repository root**
(`cd ../..` if you are still in `packages/cache`). For a new configuration,
copy the example; if `apps/server/.env` already exists, keep it and edit it instead:

```bash
cp apps/server/.env.example apps/server/.env
```

In PowerShell, use `Copy-Item apps/server/.env.example apps/server/.env`.

<a id="2-configure-local-development"></a>

Set these values in the **untracked** `apps/server/.env`, keeping the other
example defaults, for a credential-free MemoryStore dashboard:

```env
EMBEDDING_PROVIDER=mock
GENERATION_PROVIDER=mock
MOCK_EMBEDDING_DIMENSIONS=384
CACHE_BACKEND=memory
EVALUATION_DATASET_STORAGE=session
EVALUATION_RUN_HISTORY_STORAGE=disabled
COORDINATION_BACKEND=memory
AUTH_MODE=disabled
AUTH_PRINCIPALS=[]
TRUSTED_PROXY_CIDRS=[]
MAX_REQUEST_BODY_BYTES=65536
```

<a id="3-start-the-complete-development-stack"></a>

Then start the dashboard:

```bash
python scripts/dev.py up
```

Or use `uv run --no-project scripts/dev.py up`. The launcher waits for backend
readiness before starting the frontend; this configuration needs no database or
provider API key. The first build can download images and dependencies.

<a id="4-open-the-application"></a>

Open **<http://localhost:4173>** (or the URL printed for your configured ports).
Mock responses are deterministic examples; memory cache/session data disappear
when the backend restarts. Authentication is disabled for **trusted local
use only**; never expose this development stack publicly.

For [other providers](docs/guides/providers.md), persistent storage, or direct
Docker-only startup, follow [Getting started](docs/guides/getting-started.md#local-development), including
[PostgreSQL credentials/setup](docs/guides/getting-started.md#postgresql-runtime-credentials)
and [advanced direct Compose](docs/guides/getting-started.md#advanced-direct-docker-compose).

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
- MemoryStore, PostgreSQL/pgvector or RedisStore storage;
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

### Dashboard endpoints and operations

| Service | Address |
|---|---|
| Frontend | <http://localhost:4173> |
| Backend | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness | <http://localhost:8000/ready> |
| Runtime metrics | <http://localhost:8000/api/v1/metrics> |
| Runtime diagnostics | <http://localhost:8000/api/v1/diagnostics> |
| PostgreSQL from the host (persistent profile only) | `127.0.0.1:5433` |

Submit a unique Monitor prompt twice: expect a miss followed by a confirmed hit.
Mock responses are deterministic examples, not hosted model output.

Useful commands:

```bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml down
```

`down` keeps named volumes. Adding `--volumes` deletes the local PostgreSQL
data.

#### Optional: PostgreSQL persistence

For persistent cache entries and saved evaluation datasets, keep the mock-provider
settings above and change these values in `apps/server/.env`. Replace the URL
placeholders with the separate runtime login provisioned below; URL-encode its
credentials when necessary. Keep the existing volume and back up any existing
database before setup.

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix_runtime:replace-runtime-password@postgres:5432/semantix
DATABASE_MIGRATION_MODE=external
EVALUATION_DATASET_STORAGE=postgres
EVALUATION_DATASET_DEFAULT_RETENTION_DAYS=30
```

For a fresh launcher-managed volume, generate/configure the runtime password as
explained in [PostgreSQL credentials](docs/guides/getting-started.md#postgresql-runtime-credentials),
then run `python scripts/dev.py up`. It provisions the missing restricted login
with that password and runs separate setup; existing roles/data are never repaired
or overwritten. No external provider supplies this password.

**Advanced direct Compose setup:** the remaining steps require explicit operator
authority. Start only PostgreSQL and wait for its health check:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up -d --wait --wait-timeout 60 postgres
```

The development database creates only the local bootstrap role `semantix`.
Do not use that privileged role in the backend's `DATABASE_URL`. Securely load
these operator variables into your shell, without putting migration credentials
in `apps/server/.env`, tracked files, shell history, or logs:

- `DATABASE_RUNTIME_ROLE`: the restricted login name from `DATABASE_URL`;
- `MIGRATION_DATABASE_URL`: the bootstrap/migration connection for this development
  database, with authority to enable pgvector, initialize schemas, and grant access.

Inside containers, both URLs use `postgres:5432/semantix`. A host tool instead
uses `127.0.0.1:5433` by default (`POSTGRES_PORT` can change the published port).
For an existing volume, use its actual credentials and back it up before setup.

For a genuinely missing runtime role, open psql using local bootstrap authority:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector exec postgres psql -X --set ON_ERROR_STOP=1 --username semantix --dbname semantix
```

Inside psql, create the restricted role and enter the password from `DATABASE_URL`
at the hidden `\password` prompts. If the role already exists, stop and verify
its privileges and credentials separately; do not reset its password.

```sql
CREATE ROLE semantix_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE semantix TO semantix_runtime;
\password semantix_runtime
\q
```

The password prompt avoids plaintext password SQL and process arguments. The
migration command grants schema/table access; it does not create the login.
In PowerShell, supply migration authority through a masked prompt:

```powershell
$env:DATABASE_RUNTIME_ROLE = 'semantix_runtime'
$env:MIGRATION_DATABASE_URL = [pscredential]::new(
    'migration', (Read-Host 'Migration database URL' -AsSecureString)
).GetNetworkCredential().Password
```

In other shells, securely load the same two operator variables without putting
their secret values in shell history or arguments.

Run explicit setup in a one-shot backend container and continue only if it exits
successfully:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector run --rm --no-deps --build -e DATABASE_MIGRATION_MODE=external -e MIGRATION_DATABASE_URL -e DATABASE_RUNTIME_ROLE backend python -m app.infrastructure.migrate
```

The backend image supplies Python, dependencies, and `/apps/server` as its working
directory. It inherits cache schema/prefix and evaluation settings from
`apps/server/.env`; keep them identical to runtime. The `-e` flags pass operator
variables from your shell only to this job. Clear the operator variables afterward.

Ordinary cache startup validates the official schema and never initializes it.
`DATABASE_MIGRATION_MODE=auto` applies only to other enabled PostgreSQL features,
including evaluation storage. Development Compose reads the mode from
`apps/server/.env`; keep it `external` when using the restricted runtime role.
After successful setup, start the persistent stack with one command on either OS:

```bash
docker compose -f docker-compose.dev.yml --profile pgvector up --build -d --wait --wait-timeout 120 postgres backend frontend
```

This starts the React frontend with Vite hot reload and FastAPI with Uvicorn
reload after explicit database setup. Check that `/ready` returns HTTP 200, then
submit a unique Monitor prompt twice: expect a miss followed by a hit and a
readable Cache Inspector entry. Empty official cache tables immediately after
setup are valid; setup does not copy preserved legacy cache rows. See
[server storage setup](docs/guides/platform-storage.md) for ownership and schema
validation. This procedure remains for trusted local development; use
[hardened deployment](docs/operations/deployment.md) before sharing with untrusted users.

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
| **Development** | One trusted local developer | Hot reload, loopback ports, disabled authentication, explicit setup for persistent cache |
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
| [Embedded providers](docs/embedded/providers.md) | Maintained adapters and custom embedding/generation |
| [Context identity and migration](docs/embedded/context-identity-and-migration.md) | Explicit scopes, embedding revisions and safe migration |
| [Embedded storage](docs/embedded/storage.md) | Memory, SQLite, MySQL, PostgreSQL, Redis, Valkey and user-owned databases |
| [Examples](packages/cache/examples/) | Application-controlled generation and stores |
| [Reviewed reuse quality](packages/cache/benchmarks/reuse_quality/README.md) | Semantic baseline, lexical controls, calibration/held-out split and evidence limitations |
| [Benchmark methodology](packages/cache/benchmarks/README.md) | Reproducible local runtime workloads and limitations |
| [Server getting started](docs/guides/getting-started.md) | Optional server environment files and Docker workflows |
| [HTTP client guide](packages/client/README.md) | Typed client for an already-running compatible server |
| [Server architecture](docs/reference/architecture.md) | Feature ownership and request flow |
| [Hardened deployment](docs/operations/deployment.md) | Server auth, TLS, database roles and validation |

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md), [cache contributor checks](packages/cache/README.md#contributor-checks)
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
[embedded provider](docs/embedded/providers.md) and [storage](docs/embedded/storage.md)
guides for caller-owned resource and database responsibilities.

## 📄 License

Licensed under the [MIT License](LICENSE).
