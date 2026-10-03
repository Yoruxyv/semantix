# Python SDK agent instructions

Read [root instructions](../../AGENTS.md) and the [architecture](../../ARCHITECTURE.md).
semantix-client is an independently installable public
HTTP client, even while its release remains unpublished.

## Public boundary

- Call only the Semantix public HTTP API. Never import backend app modules, cache
  implementation, FastAPI schemas, database code, or backend-only dependencies.
- A new backend feature does not automatically need SDK exposure.
- Any change to a backend public HTTP contract used by the SDK requires SDK
  compatibility review. Review query, health, readiness, policy, error, and field
  semantics against backend schemas and integration tests.
- Treat exported names, sync/async method signatures, immutable model fields, enum
  values, exceptions, and documented behavior as compatibility contracts. Plan breaking
  changes explicitly; do not silently reinterpret namespaces, cache modes, private
  requests, or TTL.
- Keep runtime dependencies minimal. The current package depends on httpx only and must
  install without backend dependencies.

## Transport and lifecycle

- Keep synchronous and asynchronous query, health, readiness, serialization, response
  validation, and error behavior in parity. Test both when shared transport behavior
  changes.
- Use finite validated HTTP timeouts. Keep connection pooling through one owned
  httpx.Client or AsyncClient per SDK instance; close with close()/aclose() and
  context-manager exit.
- Bound response bytes before parsing. Check content type and encoding, parse JSON
  strictly, and decode typed public models. Do not expose raw upstream bodies, bearer
  tokens, or private transport details in exceptions.
- Preserve typed status errors, including HTTP 429 and parsed positive Retry-After
  seconds. Do not add unsafe automatic POST retries without a documented server
  idempotency contract.
- Preserve safe handling of network failures and cancellation. Close response streams on
  both success and error.

## Packaging and checks

- Keep src/semantix_client self-contained and py.typed in wheel and sdist. Preserve the
  declared Python >=3.11,<3.15 range and the supported compatibility checks.
- Add focused unit checks with httpx.MockTransport and a real-HTTP integration check
  when a public boundary changes. Check sync/async parity, bounds, lifecycle, safe
  errors, and no unintended retry.
- Run focused pytest from packages/client, then the relevant Ruff, mypy, and unit gates in
  [quality.yml](../../.github/workflows/quality.yml). For package changes, build
  wheel/sdist, run twine check, inspect contents, and verify clean installation without
  backend packages. Live integration tests require a disposable Semantix server.
