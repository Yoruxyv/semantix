"""Official optional Semantix FastAPI server: contributor navigation.

The server exposes semantic-cache queries, cache inspection/administration,
controlled evaluations and operational health/observability APIs for the web
workbench and HTTP clients. The separate ``semantix_cache`` library supplies the
authoritative MemoryStore, PgVectorStore and RedisStore. The server composes those
stores and owns HTTP contracts, authentication, namespace authorization, telemetry
and request orchestration while reusing shared private semantic primitives. The
embedded library does not provide server authentication.

Composition and resource ownership
----------------------------------
``app.main`` exposes the ASGI application. ``app.factory.create_app`` composes
settings, provider selection, middleware, error handlers and the feature router;
``app.api.router`` assembles routes and ``app.api.deps`` resolves shared services.
Importing the ``app`` package itself does not construct the application.

``app.lifecycle.create_lifespan`` owns startup/shutdown composition: it creates
the provider HTTP client, optional shared PostgreSQL pool and selected cache
backend, then places services on application state. Services/adapters borrow
those shared resources. Nested lifespan contexts close owned resources on exit;
request routes should not create a replacement client or pool for each call.

Subsystem map
-------------
``query``
    Public query schemas/routes, cache policies, prompt normalization,
    per-process request coalescing and lookup/generation orchestration.
``cache``
    Semantic lookup, keys/namespaces, threshold behavior, inspection/mutation
    routes, backend protocols, official-store adapters, request telemetry and
    explicit storage setup. Cache entries and store-specific persistence belong
    to ``semantix_cache``; legacy server cache SQL remains here.
``providers`` and ``embedding``
    Provider protocols, explicit configuration/selection and external HTTP
    adapters; embedding validation before cache use. Provider-specific wire
    formats belong in ``providers.adapters`` and transport helpers in
    ``providers.shared``.
``benchmark``
    Controlled evaluation execution, dataset validation/catalog, projections
    and optional persisted datasets/run history. Runs use an isolated memory
    cache, separate from live cache state.
``security`` and ``middleware``
    Token principals, roles and concrete namespace authorization; request body
    limits, trusted client-address handling and rate limiting.
``infrastructure`` and ``core``
    Shared PostgreSQL pool/migration/coordination facilities; settings,
    application errors, logging and common limits. Feature-specific SQL remains
    with the owning feature's infrastructure package.
``observability``
    Process-local metrics and diagnostics assembled from safe allowlists.

Following a request
-------------------
For ``POST /api/v1/query``, middleware/dependencies and Pydantic schemas establish
transport bounds, validated input, authentication and an authorized namespace.
QueryService interprets policy and coalesces compatible in-flight work.
SemanticCache obtains a validated embedding and searches compatible, unexpired
entries in that namespace. A threshold-eligible hit skips generation; otherwise
the generation provider runs and valid output is stored only when policy permits.
The HTTP response carries cache and provider-call evidence.

Persistence and configuration boundaries
---------------------------------------
``cache.infrastructure.factory.cache_backend_lifespan`` selects memory, pgvector
or Redis. Memory and pgvector constructors extend OfficialStoreBackend; RedisStore
is wrapped directly. Stores own entries, revisions, expiry and LRU; the server
adapter translates inspection results and maintains separate request counters.
PgVectorStore borrows the lifespan's shared PostgreSQL pool, also used by enabled
evaluation and coordination features. RedisStore.connect owns its client/pool;
cache lifespan closes the selected store before shared resources exit.

Persistent cache setup is explicit. Ordinary startup validates PostgreSQL/Redis
bindings rather than creating or adopting them. PgVectorStore owns its marked
schema/prefix and package migration ledger; server migration history and telemetry
remain separate. Legacy ``semantix.cache_entries`` rows stay preserved and are
neither served nor converted. Development ``auto`` migrations apply only to other
enabled PostgreSQL features. Hardened setup uses separate migration/runtime roles.
Routes do not own DDL. Consult the infrastructure lifecycle and migration runner
before changing setup; store-specific transaction and cancellation contracts
remain with the owning store.

``core.config.Settings`` and the application factory define configuration and
startup selection. ``security`` enforces authorization on the server; UI checks
and namespace strings alone are insufficient. Keep credentials, private payloads
and raw settings out of errors/logs/diagnostics, and preserve the public safe error
shape when adding failures.

Where changes belong
--------------------
Within query/cache/benchmark features, put HTTP routes and schemas in ``api``,
business orchestration in ``application``, feature rules/models/ports in ``domain``,
and concrete persistence in ``infrastructure``. Composition wires these layers;
feature application code consumes provider/storage protocols. Start with a
feature's router and service, then its domain contract, adapter and matching tests.
For embedding and small cross-cutting features, follow their existing flatter
layout rather than introducing new layers.

Repository navigation: ``ARCHITECTURE.md``, ``apps/server/AGENTS.md``,
``docs/reference/api.md`` and ``docs/guides/development.md``. Deployment/resource
ownership details live in ``docs/operations/deployment.md`` and
``docs/guides/platform-storage.md``; embedded store contracts live in
``docs/embedded-storage.md`` and ``docs/embedded-redis.md``.
"""
