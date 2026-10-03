# SDK source layout

This directory contains the implementation of the independently installable
`semantix-client` package.

User-facing installation and API documentation lives in
[`../README.md`](../README.md). This document is for contributors working on
the SDK implementation and describes the boundaries the source should preserve.

## Package structure

```text
src/
`-- semantix_client/
    |-- __init__.py
    |-- _transport.py
    |-- async_client.py
    |-- client.py
    |-- errors.py
    |-- models.py
    |-- policies.py
    `-- py.typed
```

| Module | Responsibility |
|---|---|
| `__init__.py` | Defines the supported public import surface |
| `client.py` | Synchronous `SemantixClient` |
| `async_client.py` | Asynchronous `AsyncSemantixClient` |
| `models.py` | Immutable public response models and response-contract validation |
| `policies.py` | Public `CachePolicy` values and internal request-field mapping |
| `errors.py` | Public SDK exception hierarchy |
| `_transport.py` | Private HTTP transport, configuration validation, response limits, and error translation |
| `py.typed` | Marks the installed package as typed for downstream type checkers |

## Public API boundary

Applications should import supported types from the package root:

```python
from semantix_client import (
    AsyncSemantixClient,
    CachePolicy,
    QueryResult,
    SemantixClient,
    SemantixError,
)
```

The exports in `semantix_client.__all__` define the intended public surface.

Names beginning with `_`, including `_transport`, response decoders, and policy
mapping helpers, are implementation details rather than public API.

## Request flow

```text
SemantixClient / AsyncSemantixClient
        |
        v
CachePolicy -> request fields
        |
        v
_SyncTransport / _AsyncTransport
        |
        v
public Semantix HTTP API
        |
        v
transport response validation
        |
        v
model contract decoder
        |
        v
immutable QueryResult
```

The synchronous and asynchronous clients intentionally expose equivalent public
behavior. Changes to one should normally be checked against the other.

## Responsibility boundaries

The SDK is an HTTP client, not a second Semantix server implementation.

It must not:

- import backend application modules;
- execute embedding or generation providers locally;
- access PostgreSQL or pgvector directly;
- reproduce server authorization or cache-decision logic;
- expose raw embeddings.

The server remains authoritative for authentication, authorization, namespace
access, cache policy validation, provider execution, storage, and cache decisions.

The SDK is responsible for:

- validating client configuration;
- constructing documented public requests;
- enforcing finite HTTP timeouts;
- bounding and validating HTTP responses;
- converting transport and API failures into typed SDK exceptions;
- validating successful responses against the public contract;
- exposing immutable typed result models.

## Response validation

`models.py` validates both JSON shape and semantic consistency.

For example, a cache hit must contain matched-entry evidence, must report that
generation was skipped, and must not report a generation-provider call.
Contradictory successful responses raise `SemantixResponseError`.

Keep these checks aligned with the public backend contract rather than silently
accepting inconsistent server responses.

## Transport safety

`_transport.py` contains the private synchronous and asynchronous HTTP transport
implementations. Their responsibilities include:

- HTTP/HTTPS base-URL normalization;
- bearer-token header validation;
- finite `httpx` timeouts;
- bounded response bodies;
- JSON content-type validation;
- rejection of unexpected content encoding;
- bounded and token-redacted API error details;
- `Retry-After` parsing;
- typed authentication, authorization, validation, rate-limit, server, timeout,
  and transport errors.

Transport classes are implementation details and should not become part of the
public import surface.

## Typing

`py.typed` is distributed with the package so downstream type checkers treat
`semantix_client` as typed.

Public signatures and models should remain type-checker friendly and are covered
by the SDK mypy gate.

## Tests

SDK behavior is covered under [`../tests`](../tests). Important areas include:

- synchronous and asynchronous client behavior;
- public response-contract validation;
- error mapping and malformed responses;
- cache-policy serialization;
- concurrency and cancellation;
- backend OpenAPI compatibility;
- real-HTTP integration;
- wheel and source-distribution contents.

When changing the public contract, update the implementation, tests, and the
user-facing [`../README.md`](../README.md) together.
