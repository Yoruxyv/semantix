# semantix-cache source layout

This directory contains the `semantix_cache` import package for the
`semantix-cache` distribution. It runs semantic caching inside an async Python
application; no Semantix FastAPI server is required. The separate
`packages/client` component supplies the optional/reference remote HTTP client.

| Source | Responsibility |
| --- | --- |
| [`semantix_cache/__init__.py`](semantix_cache/__init__.py) | Minimal public exports, package orientation and quick start |
| [`engine.py`](semantix_cache/engine.py) | `AsyncSemanticCache` lookup/resolve/set/delete/clear orchestration |
| [`protocols.py`](semantix_cache/protocols.py) | Structural `EmbeddingAdapter`, `GenerationCallable`, `CacheStore` contracts |
| [`models.py`](semantix_cache/models.py) | Immutable embedding metadata, entries, matches and public results |
| [`policies.py`](semantix_cache/policies.py), [`errors.py`](semantix_cache/errors.py) | Cache policies and typed errors |
| [`memory.py`](semantix_cache/memory.py) | Bounded, process-local, non-durable `MemoryStore` |
| [`_semantics.py`](semantix_cache/_semantics.py) | Pure canonicalization, keys, namespaces, vectors, TTL and decision rules shared with the server |
| [`_lifecycle.py`](semantix_cache/_lifecycle.py) | Synchronous operation admission, busy-close and closed-state checks |
| [`observability.py`](semantix_cache/observability.py) | Immutable numeric coalescing snapshot |
| [`_coalescing.py`](semantix_cache/_coalescing.py) | Bounded completion gates, synchronization and isolated collection |
| [`_coalescing_metrics.py`](semantix_cache/_coalescing_metrics.py) | Fixed numeric lifetime ledger; no payloads |
| [`adapters/`](semantix_cache/adapters/__init__.py) | Maintained provider adapters, imported explicitly with optional HTTP dependencies |
| [`stores/pgvector.py`](semantix_cache/stores/pgvector.py) | Optional application-database PostgreSQL/pgvector persistence |
| [`stores/migrations/`](semantix_cache/stores/migrations/0001_cache.sql) | Packaged, checksum-tracked SQL template applied only by explicit initialization |
| [`py.typed`](semantix_cache/py.typed) | Installed-package typing marker |

Root imports use only NumPy/Pydantic and the standard library. They do not import
HTTPX, asyncpg, FastAPI, provider SDKs, adapter modules or storage modules. Import
`PgVectorStore` from `semantix_cache.stores.pgvector` with the `[pgvector]` extra.
There is no server/remote mode in `AsyncSemanticCache`.

Applications own injected embedders, generation callables and stores. The facade
borrows them; its context manager closes only the facade. MemoryStore owns its
state/workers. PgVectorStore borrows `pool=` and owns the pool it creates through
`connect()`. Explicit migration pools remain caller-owned. Normal cache use never
creates database schemas, installs extensions, or adopts existing tables.

Start with the [package README](../README.md), then the
[provider guide](../../../docs/embedded-providers.md) and
[storage/custom database guide](../../../docs/embedded-storage.md).
Working examples are in [`../examples`](../examples/custom_integration.py), including
[`custom_store.py`](../examples/custom_store.py) and
[`persistent_support.py`](../examples/persistent_support.py).

From `packages/cache`, contributor checks are:

```text
uv sync --locked --extra dev
uv run --no-sync ruff check --config ../../ruff.toml .
uv run --no-sync ruff format --config ../../ruff.toml --check .
uv run --no-sync mypy src tests examples
uv run --no-sync pytest --cov=semantix_cache
```

mypy enables deprecation diagnostics. Supply `PGVECTOR_TEST_DATABASE_URL` only for
a disposable database to execute all storage integration cases; without it those
cases skip. The internal store-conformance suite lives in `../tests` and is reusable
by custom adapter authors without introducing pytest into the runtime package.
