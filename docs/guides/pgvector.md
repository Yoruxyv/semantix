# Persistent pgvector cache

Semantix uses the in-memory cache by default. The optional pgvector backend
implements the same cache port and preserves entries, namespace counters, hit
counts, and access timestamps across backend restarts. Use it for larger or
persistent production cache workloads; the process-local memory backend is
intentionally limited to `5,000` entries to preserve server responsiveness.

## Configuration

Set these values in `backend/.env`:

```env
CACHE_BACKEND=pgvector
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
DATABASE_POOL_MIN_SIZE=1
DATABASE_POOL_MAX_SIZE=5
DATABASE_CONNECT_TIMEOUT_SECONDS=10
DATABASE_COMMAND_TIMEOUT_SECONDS=30
```

`DATABASE_URL` is required when `CACHE_BACKEND=pgvector` or
`EVALUATION_DATASET_STORAGE=postgres`. A memory live cache does not use
PostgreSQL for cache operations, but it can share the database lifecycle with
the persistent evaluation catalog. When both settings remain
`memory`/`session`, the backend opens no pool even if a database URL is present.
The minimum pool size cannot exceed the maximum. The connection timeout bounds
pool connection establishment; the command timeout independently bounds SQL
statements after a connection is available. Increase the command timeout for
measured long-running migrations or cache operations without weakening
connection-failure detection.

The supplied Docker profile uses `semantix` as both the PostgreSQL database and
the application schema. A different database name may be used in
`DATABASE_URL`; the application tables still live in the `semantix` schema.

## Docker setup

Build and start PostgreSQL, the backend, and the frontend together:

```powershell
docker compose --profile pgvector up --build -d
```

Compose waits for PostgreSQL's health check before starting the backend. The
backend then applies pending migrations before FastAPI becomes ready.

The profile publishes PostgreSQL on host port `5433` by default and forwards it
to port `5432` inside the container:

```text
localhost:5433 -> postgres:5432
```

This avoids conflicting with a PostgreSQL installation already using the
standard host port. Override the host port when needed:

```powershell
$env:POSTGRES_PORT = "55432"
docker compose --profile pgvector up -d --wait postgres
```

The containerized backend must continue using the internal service address:

```env
DATABASE_URL=postgresql://semantix:semantix@postgres:5432/semantix
```

Tools running on the host, including pgAdmin and integration tests, connect to:

```text
Host: localhost
Port: 5433
Database: semantix
Username: semantix
Password: semantix
```

When the backend itself runs outside Docker, use `localhost` and the published
host port in `DATABASE_URL`. Changing the host port does not change the
container port or the containerized backend URL.

## Verify the database

After starting the pgvector profile, confirm all services are healthy:

```powershell
docker compose --profile pgvector ps
```

Confirm PostgreSQL accepts connections and that startup migrations created the
schema, extension, and tables:

```powershell
docker compose exec postgres psql -U semantix -d semantix -c `
  "SELECT extname FROM pg_extension WHERE extname = 'vector';"

docker compose exec postgres psql -U semantix -d semantix -c `
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'semantix' ORDER BY table_name;"
```

Then submit two semantically similar prompts through the application. The first
request should populate PostgreSQL and a sufficiently similar second request
should be eligible for a cache hit. Restart the backend and confirm the cache
entry remains available:

```powershell
docker compose restart backend
```

pgAdmin is optional and is only needed for visual inspection. Fresh Docker
volumes are initialized automatically from the Compose credentials. Existing
volumes keep their original credentials even if the Compose values later
change.

## Automatic migrations and startup behavior

The backend obtains a PostgreSQL advisory lock and runs pending migrations for
the configured cache and evaluation-storage features during FastAPI startup.
The shared bootstrap creates the `semantix` schema and migration-history table.
Cache version `0001`:

1. enables the `vector` extension;
2. creates cache entries and namespace counters;
3. creates indexes for scope, expiry, and recency filtering.

Evaluation version `0002` creates persistent dataset metadata, ordered cases,
foreign-key constraints, and catalog indexes without adding run-history tables.

The configured database role therefore needs permission to create the pgvector
extension and the `semantix` schema on first startup. Migrations finish before
the application lifespan becomes ready. If `DATABASE_URL` is missing, invalid,
or unreachable, or a migration fails, the backend does not start.

Applied versions are recorded in `semantix.schema_migrations`. Cache SQL stays
under `app/cache/infrastructure/migrations`; evaluation SQL stays under
`app/benchmark/infrastructure/migrations`.

## Storage behavior

The persistent backend stores:

- namespace and cache key;
- prompt and response;
- embedding and its exact dimensions;
- embedding provider/model identity;
- creation and expiration timestamps;
- hit count and last-accessed timestamp;
- per-namespace hit and miss counters.

Cosine nearest-neighbor lookup uses pgvector's `<=>` operator. Expired entries
are deleted before cache operations. Insertion enforces the configured global
maximum for the active embedding space by evicting the least-recently-used
entry. Namespace filtering, targeted clearing, individual deletion, inspector
sorting, and pagination use the same public cache interface as memory storage.

## Embedding compatibility

Rows are partitioned by embedding provider, model, and dimension. Changing any
of those settings starts a new logical embedding space, so incompatible vectors
are never compared. Old rows remain in PostgreSQL but are invisible to the
newly configured space. The cache API clears only the active embedding space.

After confirming that an old model will not be restored, its rows and counters
may be removed manually by matching `embedding_space` in the two
`semantix` tables.

## Integration tests

Integration tests never use `DATABASE_URL` implicitly. Point the dedicated test
variable at a disposable pgvector database:

```powershell
$env:PGVECTOR_TEST_DATABASE_URL = `
  "postgresql://semantix:semantix@localhost:5433/semantix"

cd backend
.\.venv\Scripts\python.exe -m pytest -m pgvector
```

The tests use unique embedding-space identities and clear their rows and
counters afterward. Without `PGVECTOR_TEST_DATABASE_URL`, pgvector parameters
are skipped while the complete memory suite still runs.

## Current limitations

- Nearest-neighbor search is exact. pgvector's approximate indexes require a
  fixed-dimensional indexed expression; Semantix deliberately allows different
  embedding models and dimensions in one table.
- Migration execution occurs at application startup; there is no separate
  migration CLI.
- The cache-management endpoints are unauthenticated and remain intended for
  local development.
- The Docker credentials are development defaults. Replace them outside a
  local machine and never commit production credentials.
