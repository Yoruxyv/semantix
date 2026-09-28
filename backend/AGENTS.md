# Backend agent instructions

Read [root instructions](../AGENTS.md), [current architecture](../ARCHITECTURE.md), and
[product principles](../DESIGN.md) first. These rules cover backend/app, backend/tests,
and backend scripts.

## Ownership and contracts

- Put query policy, normalization, coalescing, and generation orchestration in
  app/query. Put cache matching, keys, namespace behavior, threshold operations, and
  backend ports in app/cache. Keep evaluation execution, dataset catalog, projections,
  and history in app/benchmark.
- Keep provider-specific HTTP in app/providers/adapters and shared provider transport in
  app/providers/shared. Keep memory and pgvector details in their infrastructure
  adapters; use established protocols from application code. app/api and lifespan
  compose features, rather than owning their behavior. Do not scatter provider or cache
  backend selection across routes and services.
- Keep observability aggregate and process-scoped. Diagnostics must be assembled from an
  explicit allowlist; never serialize Settings and remove fields afterward.
- FastAPI routes validate external payloads with the existing strict Pydantic models,
  resolve dependencies through app/api/deps or the established lifespan state, and
  return the stable public error shape. A public contract change requires review of
  backend schemas, frontend types/decoders, SDK models if used, tests, and API docs.
- Preserve strict mypy typing. Do not add Any, type: ignore, noqa, or a lint suppression
  solely to hide a defect. Narrow necessary suppressions and explain non-obvious reasons
  nearby.

## Security and correctness

- Authenticate and authorize on the server for every protected route. Resolve a concrete
  authorized namespace before query work; enforce scope again in storage operations that
  accept identifiers. Never use a display name alone as an authorization key. Do not
  reveal whether a foreign-namespace entry exists.
- Keep request bodies, prompts, provider responses, vectors, dataset imports,
  evaluations, and retained collections within their existing bounds. Reject
  incompatible embedding dimensions or spaces; do not pad or truncate vectors.
  Dataset imports use their strict versioned schema; reject unknown fields where the
  schema requires it, duplicate IDs, and invalid references. Validation and preview
  must not call providers.
- Preserve cache policy semantics: private/bypass do not read or write; read-only does
  not write; refresh does not read. Evaluation runs never touch the live cache.
  Preserve complete confusion-matrix accounting and frozen-candidate projections.
  Threshold changes remain explicit global-admin actions; do not add per-namespace
  thresholds without an explicit product and contract change.
- Do not log tokens, credentials, authorization headers, private endpoints, prompts,
  full responses, imported private data, model identifiers, or raw settings. Public
  errors must not echo
  such content.
- Validate external provider output before cache writes. Convert expected external
  failures to existing safe error types; do not catch broad exceptions and turn all
  failures into success.

## Resources and persistence

- Newly introduced network or database waits need finite timeouts. Do not put blocking
  I/O on async request paths. Propagate cancellation unless this layer deliberately maps
  it to a documented terminal outcome.
- Own and close pools, HTTP clients, transactions, tasks, and temporary state on success
  and failure. Preserve the lifespan-owned provider client and single shared PostgreSQL
  pool where enabled.
- Keep SQL migrations with the owning cache, benchmark, or shared coordination
  infrastructure. Preserve the advisory lock, packaged ordering, checksums,
  transactional application, and runtime/migration role split. Define bounded retention,
  expiry, deletion, and cascade behavior for persisted data. A schema
  change needs migration tests, compatibility, recovery, and deployment documentation.
- Do not add a worker, new database, distributed lock, or extra pool merely because a
  feature stores data. First establish the required ownership and consistency boundary.
  Bounded synchronous evaluation is the default; polling, SSE, or WebSockets need an
  evidenced design.

## Tests and validation

- Add a regression test for behavior-changing bug fixes when practical; document why if
  impractical. Use deterministic mock providers or httpx.MockTransport, never real paid
  providers in routine tests.
- Exercise route/schema and application behavior at the layer being changed. Cover
  namespace and private-data boundaries when affected. PostgreSQL integration tests use
  only a disposable database.
- From backend, run focused uv run --locked pytest paths first. Relevant main gates are
  uv run --locked pytest -m "not pgvector" --cov=app, uv run --locked ruff check ., uv
  run --locked ruff format --check ., and uv run --locked mypy app tests scripts. Use
  the current [quality workflow](../.github/workflows/quality.yml) for exact CI gates.
