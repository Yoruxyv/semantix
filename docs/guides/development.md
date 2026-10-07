# Development

Use local toolchains for IDE integration, hot reload, and quality checks. The
Docker workflow is documented in [Getting started](getting-started.md).

## Embedded cache contributors

Work on `semantix-cache` independently of the optional server/web products. From
the repository root, prepare the existing locked development environment:

```text
cd packages/cache
uv sync --locked --extra dev
```

Use the [cache contributor checks](../../packages/cache/README.md#contributor-checks)
for Ruff, formatting, mypy, pytest/coverage, examples and artifact inspection.
The [Quality workflow](../../.github/workflows/quality.yml) records the full
Python 3.11-3.14 CI matrix and analysis targets. PostgreSQL cases require an
explicitly disposable `PGVECTOR_TEST_DATABASE_URL`; without it they skip.
Normal provider tests are deterministic and offline.

- Store authors: [CacheStore conformance](../cache-store-conformance.md).
- Provider contributors: [live-verification tooling](../provider-live-verification.md).
  Live requests/cost require separate authorization; ordinary tests need no keys.
- Evidence maintainers: [reuse-quality methodology and replacement workflow](../../packages/cache/benchmarks/reuse_quality/README.md#automatic-validation-and-explicit-evidence-replacement).

From `packages/cache`, validate existing reviewed evidence without model downloads
or file writes:

```text
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark validate
```

Pre-commit selects relevant staged evidence inputs; CI validates the resulting
state. Neither regenerates receipts or approves labels. Elapsed time, a different
HEAD and unrelated commits do not stale evidence: relevant input/config/corpus
hash changes do. Follow the linked explicit review/clean-source replacement
workflow after an intentional relevant change; never regenerate just to pass CI.

## Backend

The supported interpreter range is Python 3.11 through 3.14. The backend image
uses Python 3.14, the full quality suite runs on 3.14, and the compatibility
suite also runs on 3.11, 3.12, and 3.13 in CI.

Windows PowerShell:

```powershell
cd apps/server
uv sync --locked --extra dev
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

macOS or Linux:

```bash
cd apps/server
uv sync --locked --extra dev
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before
using the local backend workflow. `pyproject.toml` declares supported version
ranges while `uv.lock` records the exact cross-platform resolution used by CI
and the backend images.

The backend reads `apps/server/.env`. With `CACHE_BACKEND=pgvector`, a reachable
database is required before application startup completes. Memory and mock
providers are the lowest-dependency development configuration.

## Frontend

Use Node.js 24.0.0 or newer within the Node 24 release line. This matches the
frontend images and CI, and satisfies the runtime requirements of the current
frontend dependencies:

```bash
cd apps/web
npm ci
npm run dev
```

The Vite server runs at <http://localhost:5173>. Configure
`VITE_API_BASE_URL=http://localhost:8000` in `apps/web/.env`.

## Repository helper reports

The root `scripts/` directory contains developer-facing repository reports with
matching PowerShell and Bash entry points.

Count lines across Git-tracked and unignored text files:

Windows PowerShell:

```powershell
.\scripts\windows\get_total_lines.ps1
```

Linux:

```bash
bash scripts/linux/get_total_lines.sh
```

The report shows total files and lines, totals for every extension, the
extension with the most lines, and a file-by-file table within each extension.
Binary files, `package.json`, and `package-lock.json` files are skipped.

Find production and configuration files that are not referenced by exact
repository-relative path in any Markdown document:

Windows PowerShell:

```powershell
.\scripts\windows\find_undocumented_files.ps1
```

Linux:

```bash
bash scripts/linux/find_undocumented_files.sh
```

The documentation report intentionally excludes tests, Python package markers,
package manifests, dependency lockfiles, ignored files, installed dependencies,
and build output. It is an informational maintenance report rather than a CI
gate: a reported file may be adequately explained through its owning feature or
package even when its exact path is not mentioned.

## Quality checks

Backend:

```bash
cd apps/server
uv run --locked pytest -m "not pgvector" --cov=app
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

Frontend:

```bash
cd apps/web
npm run lint
npm run imports:check
npm run test:coverage
npm run build
npm run bundle:check
```

`npm run build` includes strict TypeScript validation through `tsc --noEmit`.
The bundle check reports the largest emitted JavaScript chunk against the
current raw and gzip budgets. Exceeding a budget emits a CI warning so growth
is visible without blocking a build.
The checked-in coverage floors are deliberately below the measured baseline,
so a small refactor does not make the gate brittle while large regressions
still fail CI. Browser accessibility and authenticated reverse-proxy coverage
run through `npm run test:e2e` against the hardened Compose stack.
Normal provider tests use `httpx.MockTransport` and must not call external
services.

Pgvector integration tests are opt-in and use
`PGVECTOR_TEST_DATABASE_URL`; see [pgvector](pgvector.md). Load testing has
separate safety acknowledgements; see
[Load testing](../operations/load-testing.md).

## Architecture rules

- Keep feature behavior with its owning feature.
- Add `api`, `application`, `domain`, or `infrastructure` layers only when the
  feature has that distinct responsibility.
- Keep small cohesive features flat.
- Depend on provider and cache ports from application code.
- Keep concrete external API and storage behavior inside adapters.
- Mirror production feature ownership in tests.
- Prefer straightforward composition over registries or dependency-injection
  frameworks.
- Preserve strict typing; do not use `Any` to bypass contracts.

See [Architecture](../reference/architecture.md) for current ownership
boundaries.

## Contributing

1. Create a focused branch:

   ```bash
   git switch -c feat/short-description
   ```

2. Keep the change within one clear concern.
3. Add or update relevant tests and documentation.
4. Run the backend and frontend checks affected by the change.
5. Validate Docker configuration:

   ```bash
   docker compose config --quiet
   docker compose build
   ```

6. Open a pull request describing behavior, validation, and configuration
   changes.

Do not commit `.env` files, provider credentials, local databases, virtual
environments, dependencies, test caches, or build output.
