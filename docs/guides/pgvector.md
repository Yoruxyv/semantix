# PostgreSQL cache setup

[Bahasa Indonesia](../translation/id/guides/pgvector.md)

The server delegates persistent cache operations to the official `PgVectorStore`.
It shares the lifespan-owned PostgreSQL pool with other enabled database features.
The store borrows that pool and never closes it. See [server storage configuration](platform-storage.md)
for all selectable stores, setup variables, Inspector behavior and the legacy transition.

## Configuration

Set `CACHE_BACKEND=pgvector` and supply `DATABASE_URL` securely. Defaults are
`CACHE_PGVECTOR_SCHEMA=semantix_cache` and `CACHE_PGVECTOR_TABLE_PREFIX=workbench_`.
An illustrative nonworking URL is:

```env
DATABASE_URL=postgresql://replace-user:replace-password@postgres.example.invalid:5432/replace-database
```

Credentials stay server-side. `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE`,
`DATABASE_CONNECT_TIMEOUT_SECONDS` and `DATABASE_COMMAND_TIMEOUT_SECONDS` retain
their existing bounds. Do not give the runtime role migration authority.

## Explicit setup

Back up existing data first. From `apps/server`, configure operator-only
`MIGRATION_DATABASE_URL`, `DATABASE_RUNTIME_ROLE`, `CACHE_BACKEND=pgvector` and
the same schema/prefix, then run:

```bash
python -m app.infrastructure.migrate
```

The job installs pgvector, verifies migration ownership/checksums and grants the
runtime role the required cache and telemetry access. Normal startup validates
cache tables and never migrates them, including in development `auto` mode.
Hardened Compose runs the explicit job before its backends.

In development Docker, first start `postgres` with the `pgvector` profile. Supply
the local container URL through `.env` and the operator variables separately,
run the command in a one-shot backend container, then start backend/frontend.
Host tools use the published port (5433 by default); containers use the internal
service port 5432. Existing volumes retain their original credentials.

## Existing installations

Legacy `semantix.cache_entries` rows are preserved and never automatically adopted.
The package-owned `semantix_cache.workbench_cache_entries` binding starts empty;
requests regenerate and repopulate it. The layouts, revision and capacity ownership
differ, so copying/renaming old tables is unsupported. Keep the old database backup
and tables for rollback, and check answer freshness before using older binaries.
Missing or unmarked tables and checksum mismatches fail startup safely.

## Behavior and verification

Namespace and embedding-space/dimension isolation, finite TTL, LRU, bounded capacity
and atomic revision/expiry confirmation are owned by PgVectorStore. Inspector reads
these same entries; request hit/miss counters are separate telemetry. Nearest-neighbor
lookup remains exact pgvector cosine search. There is no new similarity algorithm.

Check `/ready`, then repeat a prompt through Monitor and inspect/delete/clear the
active entry. Changing embedding identity/dimensions hides incompatible old vectors.
Use only a disposable database for `PGVECTOR_TEST_DATABASE_URL`; required CI tests
fail if PostgreSQL cases unexpectedly skip. See [embedded storage](../embedded-storage.md)
for the package schema and resource contract, and [deployment](../operations/deployment.md)
for the supported two-replica production boundary.
