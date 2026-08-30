# Semantix Python client

`semantix-client` is the typed Python client for the public Semantix HTTP API.
The distribution is named `semantix-client`; Python code imports
`semantix_client`.

The package provides synchronous and asynchronous clients, explicit cache
policies, immutable result models, finite timeouts, and typed errors. It does
not run a cache or an AI provider locally: every request goes to a running
Semantix server.

`httpx` is the only runtime dependency. Installing the SDK does not install or
import FastAPI, database drivers, pgvector, provider adapters, or other Semantix
backend internals.

## Quick start

### Requirements

- Python 3.11, 3.12, 3.13, or 3.14.
- A reachable Semantix server exposing `/api/v1/query`, `/health`, and `/ready`.
- A bearer token and authorized namespace when the server requires
  authentication.

For a local server, follow [Getting started](../docs/guides/getting-started.md).
Use the network-free mock providers for a first request if you do not want to
configure a hosted provider. Shared or public servers must follow the
[hardened deployment guide](../docs/operations/deployment.md).

Verify the server before using the SDK:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

`/health` may succeed while a required storage dependency is unavailable, so
check `/ready` as well.

### Installation

The package is not currently published to PyPI. Do not assume that
`pip install semantix-client` can resolve it from the public index.

#### Build and install a wheel

Build the current package from a Semantix checkout:

```bash
cd sdk
uv sync --locked --extra dev
uv run --no-sync python -m build --wheel
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before
using this locked build workflow.

Then install the wheel into the consuming project's virtual environment. Use
the actual checkout path on your machine:

```bash
python -m pip install /path/to/semantix/sdk/dist/semantix_client-0.1.0-py3-none-any.whl
```

You can also install the package directly from the repository:

```bash
python -m pip install "semantix-client @ git+https://github.com/Yoruxyv/semantix.git@main#subdirectory=sdk"
```

Confirm the distribution/import naming after installation:

```bash
python -c "import semantix_client; print(semantix_client.SemantixClient)"
```

### Configure a client

Both clients accept the same constructor options:

| Option     | Meaning                                                                                              |
| ---------- | ---------------------------------------------------------------------------------------------------- |
| `base_url` | Required HTTP(S) origin, optionally with a path prefix. Use HTTP only for trusted local development. |
| `token`    | Optional bearer token. It is required when the server has token authentication enabled.              |
| `timeout`  | Finite positive timeout in seconds for each HTTP request. The default is `30.0`.                     |

Each query also accepts a concrete `namespace`; it defaults to `default`. The
server decides whether the token can use that namespace. The SDK does not read
configuration from the environment automatically, but your application can:

```python
import os

from semantix_client import SemantixClient


client = SemantixClient(
    base_url=os.getenv("SEMANTIX_BASE_URL", "http://localhost:8000"),
    token=os.getenv("SEMANTIX_TOKEN"),
    timeout=30.0,
)
```

Do not pass `*` as a query namespace. It is an authorization marker for some
server principals, not a concrete namespace.

### First synchronous request

```python
from semantix_client import SemantixClient


with SemantixClient(
    base_url="http://localhost:8000",
    token=None,  # Set a token when authentication is enabled.
) as client:
    result = client.query(
        "How do I reset my password?",
        namespace="support",
    )

print(result.response)
print(f"cache_hit={result.cache_hit}")
print(f"provider_called={result.provider_called}")
```

Use an authorized namespace. A token-authenticated deployment usually needs an
Operator or Admin token for provider-backed queries.

## First asynchronous request

```python
import asyncio

from semantix_client import AsyncSemantixClient


async def main() -> None:
    async with AsyncSemantixClient(
        base_url="http://localhost:8000",
        token=None,
    ) as client:
        result = await client.query(
            "How do I reset my password?",
            namespace="support",
        )
        print(result.response)


asyncio.run(main())
```

## Client lifecycle

Prefer context managers so the owned HTTP connection pool is always closed:

```python
with SemantixClient(base_url="http://localhost:8000") as client:
    result = client.query("Question")

async with AsyncSemantixClient(base_url="http://localhost:8000") as client:
    result = await client.query("Question")
```

For a longer-lived client, call `client.close()` or `await client.aclose()`
when the application shuts down. Closing either client more than once is safe.

## Query results

`query()` returns an immutable `QueryResult`:

| Field                     | Meaning                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `response`                | The generated or cached response text.                                                                                                      |
| `cache_hit`               | `True` only when Semantix returned an eligible cache entry.                                                                                 |
| `similarity_score`        | Similarity for a hit, or the nearest below-threshold candidate on some misses. It is `None` when no scored lookup evidence exists.          |
| `similarity_threshold`    | The server threshold used for the decision.                                                                                                 |
| `matched_prompt`          | The stored prompt that matched. Present only on a hit.                                                                                      |
| `matched_cache_key`       | The matched entry's opaque namespace-scoped key. Present only on a hit; it is not an embedding.                                             |
| `cache_entry_created_at`  | Timezone-aware creation time for the matched entry. Present only on a hit.                                                                  |
| `cache_entry_age_seconds` | Age of the matched entry when returned. Present only on a hit.                                                                              |
| `generation_skipped`      | The current request did not perform generation. This is true for a hit and for a concurrent follower that awaited identical in-flight work. |
| `provider_called`         | This request led the generation-provider call. A concurrent follower can be a miss with `provider_called=False`.                            |
| `latency_ms`              | Server-reported query processing latency in milliseconds.                                                                                   |

`provider_called` refers to the generation provider. A cache lookup may still
use the configured embedding provider. Raw embeddings are never returned.

On every hit, `generation_skipped` is true, `provider_called` is false, and the
matched-entry evidence is present. A miss either calls the generation provider
or awaits identical in-flight work; it never contains matched-entry evidence.

## HIT and MISS behavior

With a fresh namespace, an empty cache, and no identical concurrent request,
the first normal query is a miss and calls the generation provider:

```python
from semantix_client import SemantixClient


with SemantixClient(base_url="http://localhost:8000") as client:
    first = client.query("Explain semantic caching", namespace="sdk-example")
    second = client.query("Explain semantic caching", namespace="sdk-example")

print(first.cache_hit, first.provider_called)  # expected: False, True
print(second.cache_hit, second.generation_skipped)  # possible: True, True
```

The repeat is not an unconditional promise of a hit. The entry must still
exist, belong to the same namespace and embedding space, and meet the active
similarity threshold. Expiry, eviction, restart of a memory-backed server,
configuration changes, or a different prompt can produce another miss. See
[Cache policies](../docs/guides/cache-policies.md) for the server rules.

## Cache policies

Pass a `CachePolicy` to `query()` instead of recreating request flags:

```python
from semantix_client import CachePolicy

result = client.query(
    "Regenerate this answer",
    namespace="support",
    policy=CachePolicy.REFRESH,
)
```

| Policy                  | Cache reads |   Cache writes    | Generation-provider work | Intended use                                                                     |
| ----------------------- | :---------: | :---------------: | ------------------------ | -------------------------------------------------------------------------------- |
| `CachePolicy.NORMAL`    |     Yes     | Yes, after a miss | On a miss                | Normal semantic reuse.                                                           |
| `CachePolicy.READ_ONLY` |     Yes     |        No         | On a miss                | Reuse existing entries without seeding new ones.                                 |
| `CachePolicy.REFRESH`   |     No      |        Yes        | Yes                      | Force fresh generation and store the result.                                     |
| `CachePolicy.BYPASS`    |     No      |        No         | Yes                      | Avoid reading or changing shared cache state.                                    |
| `CachePolicy.PRIVATE`   |     No      |        No         | Yes                      | Sensitive requests that must not enter cache or the server's normal query trace. |

Concurrent requests with the same prompt, namespace, and effective policy may
share one in-flight resolution. A follower then reports
`provider_called=False` even for a policy that requires fresh generation; the
leader performed the provider work.

`PRIVATE` is an explicit caller decision. Semantix does not attempt to detect
secrets automatically. `BYPASS` and `PRIVATE` have the same cache read/write
behavior, but only `PRIVATE` requests receive the server's private trace
minimization.

## Health and readiness

The clients expose two public probes. `health()` returns an immutable
`HealthStatus`; `ready()` returns an immutable `ReadinessStatus`:

```python
health = client.health()
print(health.status)
print(health.embedding_provider, health.generation_provider)

readiness = client.ready()
print(readiness.status)
print(readiness.cache_backend, readiness.evaluation_dataset_storage)
```

- `health()` calls `/health`. It confirms process liveness and returns the
  configured provider categories; it does not prove storage is available.
- `ready()` calls `/ready`. It checks the active cache and configured evaluation
  storage dependencies. A not-ready server returns HTTP 503, exposed as
  `SemantixServerError` with server error code `not_ready`.

Neither probe calls a hosted generation or embedding provider. The async client
provides `await client.health()` and `await client.ready()` with the same result
models.

## Error handling

All SDK-owned exceptions inherit from `SemantixError`:

```text
SemantixError
├── SemantixConfigurationError
├── SemantixTransportError
│   └── SemantixTimeoutError
├── SemantixResponseError
└── SemantixAPIError
    ├── SemantixAuthenticationError   (HTTP 401)
    ├── SemantixAuthorizationError    (HTTP 403)
    ├── SemantixValidationError       (HTTP 422)
    ├── SemantixRateLimitError        (HTTP 429)
    └── SemantixServerError           (HTTP 5xx)
```

`SemantixAPIError` represents other non-success HTTP statuses as well. It
exposes `status_code`, `error_code`, bounded `detail`, and
`retry_after_seconds` when the server supplies a positive `Retry-After` value.

Catch subclasses before their base classes:

```python
from semantix_client import (
    SemantixAPIError,
    SemantixAuthenticationError,
    SemantixAuthorizationError,
    SemantixRateLimitError,
    SemantixResponseError,
    SemantixServerError,
    SemantixTimeoutError,
    SemantixTransportError,
    SemantixValidationError,
)

try:
    result = client.query("Question", namespace="support")
except SemantixAuthenticationError:
    print("The bearer token is missing or invalid.")
except SemantixAuthorizationError:
    print("This token cannot query that namespace.")
except SemantixValidationError as error:
    print(f"The request was rejected: {error.detail}")
except SemantixRateLimitError as error:
    print(f"Rate limited; retry-after={error.retry_after_seconds!r}")
except SemantixServerError as error:
    print(f"Semantix failed: {error.error_code}")
except SemantixAPIError as error:
    print(f"Unexpected API rejection: HTTP {error.status_code}")
except SemantixTimeoutError:
    print("The finite request timeout elapsed; outcome may be unknown.")
except SemantixTransportError:
    print("The server could not be reached.")
except SemantixResponseError:
    print("The server response did not match the public SDK contract.")
```

The SDK does not expose arbitrary raw response bodies or private transport
details through these exceptions.

## Timeouts and retries

The default timeout is 30 seconds. Configure another finite positive value on
either client:

```python
client = SemantixClient(
    base_url="https://semantix.example",
    token="token-value",
    timeout=60.0,
)
```

Invalid, non-positive, infinite, or NaN timeouts raise
`SemantixConfigurationError` during client construction.

Query POST operations are **not automatically retried**. A query may invoke
provider work and/or write to the cache, and the current API has no idempotency
key. After a timeout or transport failure, the server may still have completed
the request. Do not blindly retry a query; decide whether duplication is safe
for the application and policy.

## Response safety

The SDK accepts JSON responses only, requests identity encoding, and enforces a
1 MiB raw-response limit before decoding. It rejects unexpected encoding,
malformed JSON, oversized bodies, missing required fields, invalid field types,
and inconsistent hit/miss evidence with `SemantixResponseError`. Successful
responses may add future fields without breaking the current client.

## Security guidance

- Keep bearer tokens in server-side application configuration, environment
  variables, or a secret manager.
- Do not embed privileged Semantix tokens in public browser JavaScript or ship
  them in a frontend bundle.
- Use only namespaces authorized for the caller and separate workloads with
  different trust boundaries.
- SDK authentication sends credentials; it does not replace server-side role
  and namespace authorization.
- Use HTTPS outside trusted local development. TLS verification uses the secure
  `httpx` default and cannot be disabled through the public SDK API.
- Use `CachePolicy.PRIVATE` for sensitive requests that must not be cached or
  enter the normal query trace.

## Complete minimal application

Save this as `app.py`, set environment variables as required by your server,
and run `python app.py`:

```python
import os

from semantix_client import SemantixClient, SemantixError


def main() -> None:
    base_url = os.getenv("SEMANTIX_BASE_URL", "http://localhost:8000")
    token = os.getenv("SEMANTIX_TOKEN")
    namespace = os.getenv("SEMANTIX_NAMESPACE", "default")

    try:
        with SemantixClient(
            base_url=base_url,
            token=token,
            timeout=30.0,
        ) as client:
            client.ready()
            result = client.query(
                "Explain semantic caching in one sentence.",
                namespace=namespace,
            )
    except SemantixError as error:
        raise SystemExit(f"Semantix request failed: {error}") from error

    print(result.response)
    print(
        f"cache_hit={result.cache_hit} "
        f"provider_called={result.provider_called} "
        f"latency_ms={result.latency_ms:.2f}"
    )


if __name__ == "__main__":
    main()
```

For a local server with `AUTH_MODE=disabled`, leave `SEMANTIX_TOKEN` unset. For
an authenticated server, set `SEMANTIX_TOKEN` to the original bearer token and
`SEMANTIX_NAMESPACE` to one of its authorized concrete namespaces.

## Troubleshooting

### Import resolution: editor analysis versus runtime

When the repository root is open in VS Code, the committed
[`pyrightconfig.json`](../pyrightconfig.json) adds `backend` and `sdk/src` as
analysis roots. Pylance can therefore resolve `semantix_client` into
`sdk/src/semantix_client` for navigation without changing Python imports.

That editor analysis does not install the SDK. For SDK development, run
`uv sync --locked --extra dev` from `sdk` and select
`sdk/.venv/Scripts/python.exe` on Windows (or `sdk/.venv/bin/python` on Linux
and macOS) as the active interpreter. Select `backend/.venv` instead when
working on the backend. If Pylance still shows a stale unresolved import after
selecting the intended environment, restart its language server or reload the
VS Code window.

| Symptom                                            | Likely cause and action                                                                                                                           |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pylance cannot resolve `semantix_client`           | Open the repository root so `pyrightconfig.json` is discovered, then reload Pylance. This is editor analysis only.                                |
| `SemantixTransportError` or connection refused     | The server is stopped, unreachable, or listening on another address. Check the base URL and `/health`.                                            |
| `SemantixConfigurationError` at construction       | The base URL is missing `http://` or `https://`, contains credentials/query/fragment data, has a malformed port, or the timeout/token is invalid. |
| `SemantixAuthenticationError`                      | The token is missing, invalid, or not the original token corresponding to the configured server digest.                                           |
| `SemantixAuthorizationError`                       | The authenticated principal lacks the query role or requested namespace. Use an authorized concrete namespace.                                    |
| `SemantixValidationError`                          | The prompt or namespace violates the public request contract. Inspect the bounded `detail` and correct the input.                                 |
| `SemantixTimeoutError`                             | The finite timeout elapsed. Investigate server/provider latency before deciding whether a query retry is safe.                                    |
| `client.health()` works but `client.ready()` fails | The process is live but a required cache or evaluation-storage dependency is unavailable. Check server storage configuration and logs.            |
| `ModuleNotFoundError: semantix_client`             | Install the `semantix-client` distribution into the active environment; the distribution uses a hyphen while the import uses an underscore.       |

## Maintainer dogfooding checklist

Perform this manually after the documentation PR is merged. The goal is to
experience the SDK as an external developer, so after building the wheel do not
inspect Semantix source to complete the exercise.

- [ ] Start a disposable, network-free Semantix server with mock embedding and
      generation providers.
- [ ] For authentication checks, enable token mode with one Operator token
      scoped to a disposable namespace and keep a second namespace unauthorized.
      Follow the [hardened authentication instructions](../docs/operations/deployment.md#access-tokens);
      do not place plaintext tokens in repository files.
- [ ] Build the wheel using only the installation instructions above.
- [ ] Create a fresh project **outside** the Semantix repository, create and
      activate a virtual environment, and install that wheel.
- [ ] Confirm `import semantix_client` works and that no Semantix backend package
      was installed into the project.
- [ ] Follow only this README to configure `base_url`, token, namespace, and a
      finite timeout.
- [ ] Call `health()` and `ready()` and inspect their typed fields.
- [ ] In a fresh namespace, send a unique `CachePolicy.NORMAL` query. Confirm a
      miss with `provider_called=True`, then repeat it and record whether it becomes
      a hit. If it does not, inspect documented threshold/cache conditions rather
      than treating a hit as guaranteed.
- [ ] Exercise every policy with unique prompts: Normal reads/writes, Read only
      does not seed a miss, Refresh skips reads and writes the generated result,
      Bypass neither reads nor writes, and Private neither caches nor enters the
      normal server trace.
- [ ] Use an invalid token once and confirm `SemantixAuthenticationError`.
- [ ] Use the valid token with the unauthorized namespace and confirm
      `SemantixAuthorizationError`.
- [ ] Submit an empty prompt and confirm `SemantixValidationError`.
- [ ] Stop the server and confirm a request raises `SemantixTransportError`.
- [ ] Under a controlled local delay or test proxy, use a small positive timeout
      and confirm `SemantixTimeoutError`. Do not induce this against production and
      do not blindly retry the query.
- [ ] Repeat a query through `AsyncSemantixClient` and verify `async with`
      cleanup; also verify explicit `close()` and `aclose()` in a separate lifecycle
      check.
- [ ] Record every point where the README was insufficient or actual behavior
      differed. That friction is the output of the maintainer-run dogfood pass.

Do not treat the checklist as proof of universal cache-hit behavior or semantic
cache safety. It is an onboarding and API-contract exercise.

## SDK development checks

From `sdk`:

```bash
uv sync --locked --extra dev
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy src tests
uv run --no-sync pytest -m "not integration" --cov=semantix_client
uv run --no-sync python -m build
uv run --no-sync python -m twine check dist/*
```

Live integration tests require a real loopback Semantix server configured with
deterministic mock embedding and generation providers. Set
`SEMANTIX_INTEGRATION_URL` and `SEMANTIX_INTEGRATION_TOKEN`, then run:

```bash
uv run --no-sync pytest -m integration
```
