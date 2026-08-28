# Semantix Python client

`semantix-client` is the typed Python client for the public Semantix HTTP API.
It provides synchronous and asynchronous query clients, explicit cache policies,
immutable result models, bounded timeouts, and safe typed errors.

> The SDK does not implement semantic caching locally. It communicates with a
> Semantix server over its public HTTP API.

It does not install or import FastAPI, database drivers, pgvector, NumPy,
provider adapters, server settings, or other Semantix backend internals.

## Requirements and compatibility

- Python 3.11 through 3.14.
- A Semantix server exposing the current `/api/v1/query`, `/health`, and `/ready`
  contracts.
- `httpx` is the only runtime dependency.

Version `0.1.x` tolerates additive JSON response fields. Missing required fields,
wrong types, or violated query-evidence invariants raise `SemantixResponseError`.
Changing an exported client signature, model field, policy meaning, or exception
contract is considered a breaking SDK change while the package matures toward
1.0.

## Installation

Install a locally built wheel:

```bash
pip install dist/semantix_client-0.1.0-py3-none-any.whl
```

Before package-index publication, install directly from Git:

```bash
pip install "semantix-client @ git+https://github.com/Yoruxyv/semantix.git@main#subdirectory=sdk/python"
```

For local SDK development:

```bash
cd sdk/python
uv sync --locked --extra dev
```

The package is not published to PyPI by Phase 10.

## Synchronous quick start

```python
from semantix import CachePolicy, SemantixClient

with SemantixClient(
    base_url="http://localhost:8000",
    token="token-value",
) as client:
    result = client.query(
        "How do I reset my password?",
        namespace="support",
        policy=CachePolicy.NORMAL,
    )

print(result.response)
print(result.cache_hit)
print(result.similarity_score)
```

## Asynchronous quick start

```python
import asyncio

from semantix import AsyncSemantixClient, CachePolicy


async def main() -> None:
    async with AsyncSemantixClient(
        base_url="http://localhost:8000",
        token="token-value",
    ) as client:
        result = await client.query(
            "How do I reset my password?",
            namespace="support",
            policy=CachePolicy.NORMAL,
        )
        print(result.response)


asyncio.run(main())
```

Use `close()` for explicit synchronous cleanup and `await aclose()` for explicit
asynchronous cleanup. Both operations are safe to repeat.

## Base URL and authentication

`base_url` is required. HTTP is supported for explicit local development and
HTTPS for deployments. Trailing slashes are normalized, and configured path
prefixes are preserved. URLs with unsupported schemes, credentials, query
strings, fragments, or malformed ports are rejected. The SDK never downgrades
HTTPS and has no embedded production host.

Pass a bearer token explicitly with `token="..."`. The SDK sends it as the
`Authorization` header, never writes it to disk, and redacts it from translated
server errors. It does not discover credentials from files or environment
variables. The Semantix server remains authoritative for authentication, roles,
and namespace authorization.

## Namespaces and cache policies

Each query sends one concrete namespace. The default is `default`; deployments
with other namespace scopes should always pass the intended value. The SDK does
not infer roles or decide whether a namespace is authorized.

| Policy | Read | Write | Private |
|---|:---:|:---:|:---:|
| `CachePolicy.NORMAL` | Yes | Yes | No |
| `CachePolicy.READ_ONLY` | Yes | No | No |
| `CachePolicy.REFRESH` | No | Yes | No |
| `CachePolicy.BYPASS` | No | No | No |
| `CachePolicy.PRIVATE` | No | No | Yes |

These values map to the existing server request flags; they do not create new
cache behavior. Private requests remain subject to the server's private-request
handling and are not protected by client-side trust logic.

## Query results

`query()` returns an immutable `QueryResult` with:

- `response`;
- `cache_hit`;
- `similarity_score`;
- `similarity_threshold`;
- `matched_prompt` and `matched_cache_key` for hits;
- `cache_entry_created_at` and `cache_entry_age_seconds` for hits;
- `generation_skipped` and `provider_called`;
- `latency_ms`.

`cache_entry_created_at` is decoded as a timezone-aware `datetime`. Raw
embeddings are never returned.

## Errors

All SDK-owned errors inherit from `SemantixError`:

| Error | Meaning |
|---|---|
| `SemantixConfigurationError` | Invalid base URL, token header value, or timeout |
| `SemantixTransportError` | Connection or other HTTP transport failure |
| `SemantixTimeoutError` | Configured timeout elapsed |
| `SemantixResponseError` | Malformed or contract-invalid successful response |
| `SemantixAuthenticationError` | HTTP 401 |
| `SemantixAuthorizationError` | HTTP 403 |
| `SemantixValidationError` | HTTP 422 |
| `SemantixRateLimitError` | HTTP 429; `retry_after_seconds` when supplied |
| `SemantixServerError` | HTTP 5xx |
| `SemantixAPIError` | Other non-success HTTP status |

```python
from semantix import SemantixError, SemantixRateLimitError

try:
    result = client.query("Question", namespace="support")
except SemantixRateLimitError as error:
    print(error.retry_after_seconds)
except SemantixError:
    print("The query did not complete.")
```

Server error codes and bounded safe details remain available as `error_code`,
`detail`, and `status_code`. Raw HTML and arbitrary complete response bodies are
not included in exception strings.

## Timeouts and retries

The default timeout is 30 seconds. Set another finite positive value with
`timeout=...`:

```python
client = SemantixClient(base_url="https://semantix.example", timeout=60.0)
```

Query POST requests are never retried automatically. A request can trigger
provider generation and cache writes, and the current server contract has no
idempotency key. Applications may make an explicit retry decision after
considering that risk.

## Health and readiness

`health()` returns `HealthStatus` for public process/provider liveness.
`ready()` returns `ReadinessStatus` for active cache and evaluation-dataset
storage. A not-ready response raises `SemantixServerError`.

## Security notes

- TLS verification uses the secure `httpx` default and cannot be disabled by
  this SDK API.
- Tokens are held only for request authentication and are never persisted or
  included in result models.
- Authorization and namespace checks are always server-side.
- Responses are bounded before JSON decoding.
- The SDK exposes no raw embeddings, provider credentials, private endpoints,
  or diagnostics surface.
- Phase 09 cache-integrity and poisoning boundaries remain server-owned.

## Development checks

```bash
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy src tests
uv run --no-sync pytest -m "not integration" --cov=semantix
python -m build
python -m twine check dist/*
```

Live integration tests require a real loopback Semantix server configured with
deterministic mock embedding and generation providers. Set
`SEMANTIX_INTEGRATION_URL` and `SEMANTIX_INTEGRATION_TOKEN`, then run:

```bash
uv run --no-sync pytest -m integration
```
