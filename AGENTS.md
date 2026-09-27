# Repository agent instructions

These instructions apply to all agent work in this repository unless the task
prompt provides stricter requirements.

## Repository purpose

Semantix is a local-first semantic-cache laboratory for inspecting and
evaluating:

- semantic cache decisions;
- similarity and threshold behavior;
- cache hits and misses;
- false positives and false negatives;
- provider-call avoidance;
- latency, token, and cost trade-offs;
- cache contents and lifecycle;
- bounded evaluation runs;
- operational health and metrics.

Preserve Semantix's current identity and architectural boundaries. Do not
silently turn the repository into a generic chatbot, generic LLM evaluation
platform, provider marketplace, tenant-management system, billing platform, or
distributed observability system.

## Sources of truth

When repository information conflicts, use this priority:

1. Current source code and committed configuration.
2. Current automated tests.
3. Current API schemas, migration behavior, and runtime contracts.
4. Current repository documentation.
5. Approved planning documents and task descriptions.
6. Graphify output.

Planning documents describe intended work. Current source remains authoritative
for existing behavior.

When a plan and the repository differ:

- verify the discrepancy directly;
- preserve the intended product direction where practical;
- adapt the implementation to the current architecture;
- document the discrepancy in the final report;
- do not silently invent missing architecture, APIs, storage, or dependencies.

## Graphify navigation

This repository uses a local, code-only Graphify knowledge graph for codebase
navigation. Run Graphify commands from the repository root.

### Use Graphify before broad source browsing

Before broad source searches or repository-wide source browsing, use the
existing graph to identify relevant:

- files;
- symbols;
- imports;
- callers;
- dependencies;
- inheritance relationships;
- module boundaries;
- route composition;
- execution paths.

Use:

```powershell
graphify query "<question>" --graph graphify-out/graph.json
graphify path "<A>" "<B>" --graph graphify-out/graph.json
graphify explain "<symbol>" --graph graphify-out/graph.json
```

Examples:

```powershell
graphify query "How are benchmark runs created and executed?" `
  --graph graphify-out/graph.json

graphify query "Which frontend modules own navigation and route accessibility?" `
  --graph graphify-out/graph.json

graphify path "BenchmarkDashboard" "BenchmarkService" `
  --graph graphify-out/graph.json

graphify explain "SemanticCache" `
  --graph graphify-out/graph.json
```

Use Graphify to narrow the inspection area before broad recursive searches.

A targeted source search is still appropriate when:

- the exact file is already known;
- the task references a concrete symbol or path;
- Graphify cannot represent the required text relationship;
- searching documentation, SQL, YAML, configuration, or generated metadata;
- verifying Graphify findings against current source.

### Verify Graphify findings

Graphify is a navigation aid, not an authority.

Before drawing conclusions or making changes:

1. inspect the relevant current source files;
2. inspect tests that define the behavior;
3. inspect API schemas, configuration, and migrations when applicable;
4. confirm that the graph is not stale.

Do not implement a change based only on a graph node, edge, cluster, report, or
visualization.

### graph.html usage

`graphify-out/graph.html` is the human-facing graph visualization.

Do not parse or read the entire HTML file as the primary source of repository
context. Use Graphify commands against:

```text
graphify-out/graph.json
```

The HTML file must remain up to date after meaningful code-relationship
changes so the maintainer can inspect it visually.

### Initial graph creation

If the graph does not exist locally, create it with:

```powershell
graphify extract . --code-only
```

Confirm the expected files exist:

```powershell
Get-Item `
  .\graphify-out\graph.json, `
  .\graphify-out\graph.html |
    Select-Object Name, Length, LastWriteTime
```

Do not create a documentation-inclusive graph unless explicitly requested.

### Graph refresh

After a task is implemented and validated, run:

```powershell
graphify update .
```

Refresh the graph when a task:

- adds source-code files;
- removes source-code files;
- moves or renames source-code files;
- adds, removes, or renames important symbols;
- changes imports or exports;
- changes calls between functions, methods, services, or modules;
- changes inheritance, protocols, or dependency injection;
- changes route composition;
- changes module ownership;
- performs a structural refactor;
- otherwise changes relationships represented by the code graph.

After updating, verify the generated graph and visualization:

```powershell
Get-Item `
  .\graphify-out\graph.json, `
  .\graphify-out\graph.html |
    Select-Object Name, Length, LastWriteTime
```

If extraction succeeded but clustering or visualization is missing or clearly
stale, run:

```powershell
graphify cluster-only .
```

Then verify the timestamps again.

Do not refresh the graph before relevant application validation has passed.

### Graph refresh exclusions

Skip graph refreshes for changes that cannot affect code relationships,
including:

- documentation-only changes;
- translation-only changes;
- formatting-only changes;
- comment-only changes;
- spelling corrections;
- Markdown link corrections;
- issue and pull-request templates;
- repository housekeeping;
- configuration-value changes that do not alter source relationships.

When uncertain, refresh only when the changed source can affect symbols,
modules, imports, calls, routes, inheritance, or dependency wiring.

### Graphify repository hygiene

Keep Graphify output and machine-specific hooks local.

Do not stage or commit:

```text
.codex/
graphify-out/
```

unless the repository explicitly adopts tracked Graphify artifacts through a
separate reviewed change.

Before committing, verify:

```powershell
git status --short
git diff --cached --name-only
```

Generated Graphify files must not appear in the staged change.

## Task preparation

Before editing:

1. Read the complete task prompt.
2. Inspect `git status --short`.
3. Confirm the current branch.
4. Confirm the branch is based on the latest intended base.
5. Identify applicable repository instructions.
6. Read relevant planning documents.
7. Use Graphify when broad code navigation is required.
8. Inspect affected source, tests, schemas, configuration, and documentation.
9. Establish current behavior before changing it.
10. Identify validation commands before implementation.

Do not begin implementation while important scope or repository-state
assumptions remain unverified.

Do not discard or overwrite unrelated local changes.

## Planning documents

Implementation plans live under:

```text
docs/plans/
```

When a task references a planning document:

- read the program `README.md`;
- read the complete active planning document;
- treat its objective, scope, exclusions, dependencies, acceptance criteria,
  validation, rollback, and definition of done as the implementation contract;
- verify every current-state claim against the latest source;
- implement only the requested scope;
- do not silently begin later planned work;
- leave the repository valid and working at the end of the task.

Use planning documents that actually exist in the current checkout; do not
assume older plan paths are still present.

Do not combine separate planned tasks into one implementation pull request unless the
maintainer explicitly requests it.

Optional work must remain optional and must not be pulled into the MVP
silently.

## Scope discipline

Keep every task focused on one concern.

Do not:

- perform unrelated refactoring;
- rename broad feature trees for cosmetic consistency;
- replace working architecture without a demonstrated requirement;
- introduce speculative infrastructure;
- change public contracts without compatibility handling;
- add dependencies merely to reduce a small amount of local code;
- modify unrelated tests;
- reformat unrelated files;
- resolve unrelated TODOs;
- combine optional follow-up work with required implementation;
- implement later planned work early;
- create a fifth top-level navigation item merely to fill visual space.

When a separate issue is discovered:

- record it in the final report;
- fix it only if it blocks the active task or creates an immediate correctness
  or security problem;
- otherwise leave it for a separate branch or issue.

## Architecture expectations

Semantix follows feature-first ownership.

Preserve these principles:

- query behavior belongs to the query feature;
- cache behavior belongs to the cache feature;
- benchmark and evaluation behavior belongs to the benchmark/evaluation
  feature;
- observability behavior belongs to the observability feature;
- provider-specific HTTP behavior belongs to provider adapters;
- storage-specific behavior belongs to infrastructure adapters;
- frontend pages, components, hooks, types, decoders, API adapters, and routes
  remain with the feature that owns them;
- migrations remain with the owning feature or explicitly reviewed shared
  database infrastructure;
- application code depends on established protocols and contracts rather than
  concrete adapters where the repository already follows that pattern;
- small cohesive features should remain flat instead of gaining unnecessary
  architectural layers.

Do not spread provider or cache backend selection logic across routes and
services.

Do not add an architectural layer unless it owns a distinct responsibility.

Do not move evaluation persistence under cache ownership merely because the
current PostgreSQL pool or migration runner is located there. Any shared
database lifecycle must be explicitly designed and narrowly scoped.

## Product invariants

Unless an approved task explicitly changes them, preserve these invariants:

- the product has four top-level workspaces;
- the intended visible workspaces are Monitor, Cache, Evaluations, and
  Observability;
- provider configuration is startup-owned;
- browser clients do not edit provider credentials;
- server-side authorization is authoritative;
- namespace authorization is enforced on the backend;
- evaluation execution is isolated from the live cache;
- evaluation cache keys are not treated as live-cache entries;
- global threshold changes remain human-controlled;
- thresholds are not applied automatically;
- per-namespace thresholds are not introduced accidentally;
- provider-backed work requires existing authorization and disclosure;
- raw embeddings are not exposed as a primary interface;
- credentials, tokens, private endpoints, private prompts, and full sensitive
  responses are not exposed through telemetry or diagnostics;
- persistence and retention are explicit and bounded;
- synchronous bounded execution remains the default;
- workers, polling, SSE, WebSockets, or distributed coordination require a
  demonstrated need and separately reviewed design;
- Semantix does not become a generic chatbot;
- Semantix does not become a generic multi-provider comparison platform;
- Semantix does not add billing or tenant administration without an approved
  product redesign.

## Backend requirements

Maintain:

- strict type hints;
- Pydantic validation;
- stable error contracts;
- server-side authorization;
- namespace isolation;
- bounded request and response behavior;
- deterministic offline provider tests;
- migration checksum and ordering guarantees;
- compatibility with the supported Python range;
- current application factory and dependency-injection boundaries;
- stable cancellation, timeout, and cleanup semantics where defined.

Do not:

- use `Any` merely to bypass typing;
- log credentials, secrets, authorization headers, or private provider URLs;
- log private prompt or response content;
- call real paid providers from tests;
- truncate or pad incompatible embeddings;
- compare embeddings from incompatible spaces;
- leak whether a foreign-namespace resource exists;
- serialize the complete settings object into an API response;
- expose database URLs or private provider base URLs;
- weaken request-size, rate-limit, proxy, authentication, or authorization
  boundaries;
- introduce unbounded in-memory or persistent collections;
- silently change provider-call behavior;
- silently change cache-isolation behavior.

When changing an API contract:

1. update the backend schema;
2. update route and application behavior;
3. update frontend types;
4. update frontend decoders;
5. update backend and frontend tests;
6. update API documentation;
7. preserve backward compatibility or document the migration explicitly.

## Frontend requirements

Maintain:

- strict TypeScript;
- strict runtime response decoding;
- feature-owned routing and components;
- accessible semantic HTML;
- keyboard support;
- visible focus;
- correct route focus behavior;
- loading, empty, error, and success states;
- responsive behavior without accidental document-level overflow;
- server authorization as the actual security boundary.

Do not:

- use frontend role checks as a replacement for backend enforcement;
- expose secrets through `VITE_*`;
- render imported prompt text as executable HTML;
- rely on color alone for meaning;
- add inaccessible custom controls when a native control is suitable;
- hide dense content through clipping;
- add a top-level navigation item solely for visual balance;
- create a generic chatbot workflow unless explicitly approved;
- introduce browser persistence for sensitive datasets without explicit scope;
- silently discard query, hash, filter, or route state during compatibility
  redirects.

When changing navigation or layout, verify representative widths:

```text
320 px
744 px
768 px
820 px
834 px
1024 px
1280 px
```

Also verify:

- representative landscape widths;
- 200% browser zoom;
- keyboard navigation;
- focus visibility;
- touch-comfortable controls;
- no unintended page-level horizontal overflow.

## Accessibility

Accessibility is part of implementation, not a final cleanup task.

For affected functionality:

- use semantic headings and landmarks;
- connect labels to controls;
- provide accessible names for icon-only actions;
- preserve visible focus;
- announce meaningful asynchronous status changes;
- restore focus appropriately after dialogs or compact-menu closure;
- do not steal focus after normal route navigation;
- provide text or tabular equivalents for charts;
- provide non-color status labels;
- ensure content remains usable at increased text size;
- keep touch targets comfortable;
- test keyboard-only operation;
- ensure dense tables have a usable alternative on narrow viewports;
- keep page-level overflow at zero unless the active requirement explicitly
  permits a local scroll region.

Update:

```text
docs/reference/accessibility.md
```

when an accessibility contract or verification procedure changes.

## Security and privacy

Treat prompts, responses, imported datasets, provider configuration, tokens,
database credentials, cache entries, run evidence, and namespace-scoped
resources as potentially sensitive.

Never commit:

- `.env` files containing real values;
- API keys;
- access tokens;
- database passwords;
- authorization headers;
- private prompts or responses;
- private provider URLs;
- personal data;
- production logs;
- generated artifacts containing sensitive content.

When handling private requests or datasets:

- minimize retention;
- avoid browser persistence unless explicitly required;
- avoid logging content;
- do not include full content in error messages;
- do not expose content through aggregate telemetry;
- use positive allowlists for diagnostics;
- keep deletion and retention behavior explicit;
- preserve namespace authorization;
- ensure exports are deliberate user actions.

Frontend permission checks may hide unavailable actions, but backend
authorization remains mandatory.

Use non-disclosing behavior for missing or foreign-namespace resources when the
existing security model requires it.

## Evaluation-specific rules

Evaluation work must preserve:

- isolated run-local or explicitly bounded evaluation cache behavior;
- no reads from or writes to the live cache;
- mandatory provider-call acknowledgement where required;
- bounded cases, repetitions, thresholds, request size, and wall-clock time;
- honest measured, estimated, and projected terminology;
- frozen-candidate threshold projections unless a separate task explicitly
  introduces ordered replay;
- complete confusion-matrix accounting;
- explicit false-positive and false-negative semantics;
- human-controlled threshold decisions;
- no automatic threshold application;
- no claims that one threshold is universally optimal or safe;
- safe reproducibility metadata without credentials or private endpoints;
- deterministic ordering;
- cleanup after completion, failure, timeout, or cancellation.

Evaluation keys from isolated runs are evidence only. Do not link them to the
live Cache workspace.

## Dataset import rules

For imported evaluation datasets:

- use strict versioned schemas;
- reject unknown fields where the contract requires strictness;
- validate on the server even after client-side validation;
- bound case count, prompt length, metadata length, decoded bytes, and total
  workload;
- reject duplicate IDs and invalid references;
- do not call providers during validation or preview;
- do not echo complete sensitive prompts in validation errors;
- keep session-local data in component memory unless persistence is explicitly
  in scope;
- do not use localStorage, sessionStorage, IndexedDB, or service-worker caching
  unless an approved task requires it;
- render imported text as escaped plain text;
- neutralize spreadsheet formula prefixes in CSV exports;
- keep JSON exports structurally faithful.

## Persistence and migrations

Do not introduce persistence before the active task requires it.

When persistence is in scope:

- use PostgreSQL and existing asyncpg patterns;
- do not introduce SQLite unless explicitly approved;
- preserve migration ordering, checksums, advisory locking, and concurrency
  guarantees;
- keep migration ownership explicit;
- use least-privilege runtime roles;
- define retention, expiry, deletion, and cascade behavior;
- keep retention objectively bounded;
- avoid background workers unless separately approved;
- use opportunistic bounded cleanup where the task requires it;
- support intended memory-cache and pgvector-cache combinations;
- avoid opening duplicate pools when one reviewed shared pool is appropriate;
- never use display names as the sole authorization key;
- test migrations, compatibility, rollback, and recovery.

Any schema migration must include:

- forward migration behavior;
- compatibility expectations;
- migration tests;
- rollback or recovery guidance;
- documentation updates;
- deployment implications.

## Observability and diagnostics

Observability must remain:

- aggregate;
- process-scoped where that is the current architecture;
- free of prompts and full responses;
- free of credentials and private endpoints;
- role-protected where required;
- explicit about single-process limitations.

Diagnostics responses must be constructed from a positive allowlist.

Never serialize `Settings` and then remove fields afterward.

Do not expose:

- API keys or token hashes;
- database URLs;
- provider base URLs;
- private hosts;
- unapproved model identifiers;
- prompts, responses, dataset names, namespaces, or run IDs;
- raw environment dumps.

## Documentation

Documentation must match implemented behavior.

Update relevant documentation when changing:

- environment variables;
- provider support;
- cache policies;
- API contracts;
- authorization;
- namespace behavior;
- evaluation behavior;
- threshold semantics;
- import schemas;
- persistence or retention;
- migrations;
- Docker or deployment behavior;
- recovery procedures;
- CI requirements;
- known limitations;
- accessibility verification.

Do not claim performance improvements without reproducible evidence.

Performance or benchmark claims must record relevant context such as:

- provider;
- model or safe configuration fingerprint;
- dataset and version;
- threshold;
- repetitions;
- cache state;
- hardware;
- runtime conditions;
- date;
- measured versus estimated fields.

Do not update translated documentation by mechanically translating changed
English text without review.

Preserve the repository's current translation directory convention. Do not
rename the translation tree in an unrelated task.

For documentation-only changes:

- validate Markdown structure;
- validate internal relative links;
- avoid root-relative repository links unless intentionally targeting a site
  root;
- preserve commands, paths, identifiers, and code examples;
- skip Graphify refresh.

## Testing strategy

Test the smallest relevant surface first, then run the broader required gate.

### Backend

From the repository root:

```powershell
cd backend
uv sync --locked --extra dev
.\.venv\Scripts\Activate.ps1
. .\scripts\windows\enable_cache.ps1
```

Focused tests:

```powershell
uv run --locked pytest <relevant-test-path>
```

Main backend checks:

```powershell
uv run --locked pytest -m "not pgvector" --cov=app
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

When the current repository or active task does not require coverage, use the
exact established pytest command from `CONTRIBUTING.md`,
`.github/workflows/quality.yml`, or `backend/pyproject.toml`. Do not invent a
different quality gate.

Pgvector integration tests are opt-in and require a disposable database:

```powershell
$env:PGVECTOR_TEST_DATABASE_URL = `
  "postgresql://semantix:semantix@localhost:5433/semantix"

cd backend
.\.venv\Scripts\python.exe -m pytest -m pgvector
```

Do not run integration tests against production data.

### Frontend

From the repository root:

```powershell
cd frontend
npm ci
```

Focused tests:

```powershell
npm run test -- <relevant-test-path>
```

Main frontend checks:

```powershell
npm run lint
npm run imports:check
npm run test:coverage
npm run build
```

Use the exact scripts present in `frontend/package.json`. If a referenced script
does not exist, inspect the current package scripts and report the discrepancy
instead of inventing it.

Run Playwright for routing, responsive, browser, or accessibility work using the
repository's current E2E command and configuration.

### Docker Compose

From the repository root:

```powershell
docker compose config --quiet
docker compose -f docker-compose.dev.yml --profile pgvector config --quiet
docker compose --env-file .env.production.example `
  -f docker-compose.prod.yml config --quiet
```

Run only the Compose validations relevant to the changed configuration.

### Documentation links

For documentation work:

- run the repository's current Markdown or broken-link workflow when present;
- verify changed relative links manually;
- ensure language-switcher targets exist;
- avoid treating transient external-site failures as proof of a broken internal
  path;
- add ignore rules only for known automation-blocking external sites, not for
  genuine broken links.

### Validation honesty

Never claim a command passed unless it was run successfully.

When a command cannot run:

- explain why;
- include the exact attempted command;
- include the relevant error;
- distinguish environment limitations from implementation failures;
- do not mark the task complete when a mandatory gate remains unverified.

## Git workflow

Before creating a branch:

```powershell
git status --short
git branch --show-current
git fetch origin
```

Create a focused branch from the intended updated base.

Recommended branch prefixes:

```text
feat/
fix/
docs/
refactor/
perf/
test/
chore/
ci/
build/
```

Keep one concern per branch.

Do not:

- rewrite unrelated history;
- force-push without explicit need;
- discard another person's work;
- commit generated Graphify output;
- commit caches or machine-specific files;
- create a pull request unless explicitly requested;
- merge a pull request unless explicitly requested.

Use `--force-with-lease` rather than `--force` when rewriting an explicitly
approved branch.

## Commit messages

Use Conventional Commits:

```text
<type>(<optional-scope>): <imperative description>
```

Examples:

```text
feat(evaluations): add bounded threshold sweep controls
fix(cache): preserve namespace isolation for entry detail
docs(plans): add evaluation planning documents
ci(docs): validate documentation links
refactor(frontend): consolidate evaluation result filters
```

Choose the type that describes the actual change:

- `feat` for new user-visible behavior;
- `fix` for a defect;
- `docs` for documentation only;
- `style` for formatting-only changes;
- `refactor` for internal restructuring without behavior change;
- `perf` for measured performance improvement;
- `test` for test-only work;
- `chore` for maintenance;
- `ci` for workflow changes;
- `build` for build or dependency-system changes.

Do not use `feat(docs)` for documentation-only changes. Prefer a documentation
type and useful scope, such as:

```text
docs(i18n): add Indonesian translations
```

## Pull requests

A pull request must remain focused and explain:

- the problem or intended behavior;
- the implementation approach;
- affected areas;
- API, configuration, migration, and compatibility impact;
- validation commands and results;
- screenshots for visible UI changes;
- security and privacy considerations;
- limitations and follow-up work.

Use the repository pull-request template accurately.

Do not check boxes for commands that were not run.

Do not claim that runtime tests are required for documentation-only changes when
they are not.

When the repository uses squash merges, prepare a clean final PR title suitable
for the resulting commit.

Do not create or merge the PR unless the user explicitly asks.

## AI-assisted changes

AI assistance is allowed, but the author remains responsible for the result.

Before finalizing AI-assisted work:

- review and understand every changed line;
- verify architecture and behavior against current source;
- verify licenses and attribution;
- remove fabricated claims and unverified commands;
- run relevant tests;
- ensure generated documentation matches implementation;
- check for credentials, private prompts, responses, and personal data;
- ensure no unrelated generated files are staged.

Generated code that has not been reviewed and validated is not complete.

## Final review before commit

Before committing:

1. Inspect `git status --short`.
2. Inspect the full diff.
3. Confirm no unrelated files changed.
4. Confirm no secrets or private data are present.
5. Confirm tests and checks relevant to the change passed.
6. Confirm documentation matches behavior.
7. Confirm compatibility and rollback concerns are handled.
8. Refresh Graphify when required.
9. Confirm `.codex/` and `graphify-out/` are not staged.
10. Use an accurate Conventional Commit message.

Useful commands:

```powershell
git status --short
git diff --check
git diff
git diff --cached
git diff --cached --name-only
```

## Required final report

At the end of an implementation task, report:

- branch name;
- task implemented;
- files changed;
- concise implementation summary;
- important repository or plan discrepancies;
- validation commands and results;
- manual verification performed;
- security, privacy, migration, and compatibility notes;
- Graphify refresh result or the reason it was skipped;
- commit hash and message, when committed;
- push result, when pushed;
- PR title and complete PR description, when requested;
- remaining risks, blockers, or follow-up work.

Clearly distinguish:

- completed work;
- validation that passed;
- validation that was not run;
- known limitations;
- optional later work.

Do not claim completion while required acceptance criteria remain unmet.
