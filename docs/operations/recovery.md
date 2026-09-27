# Operations and recovery

This runbook covers the hardened two-replica Compose deployment. Test every
procedure against an isolated project and disposable volume before using it for
a shared environment.

## Ownership and data policy

Semantix treats pgvector cache entries and namespace counters as disposable
derived data. Provider responses remain the source of truth. Deleting the cache
does not delete provider-side data, authentication configuration, or application
configuration.

Persisted evaluation datasets are different: they can contain sensitive,
operator-supplied prompts and notes that may not exist elsewhere. When
`EVALUATION_DATASET_STORAGE=postgres`, the deployment owner must choose whether
these records are recoverable or intentionally disposable and apply that policy
to backups, access, retention, and deletion.

Durable evaluation run history is also an explicit retention decision. It is
aggregate-only, but can contain dataset identity, categories, timestamps,
configuration fingerprints, terminal failure metadata, and measured
aggregates. Include it in backup, retention, access, and deletion policy when
`EVALUATION_RUN_HISTORY_STORAGE=postgres`.

A cold cache has operational consequences:

- the first eligible request for each semantic group calls the provider;
- latency and provider cost rise while the cache warms;
- cache entries, hit counters, and miss counters start from zero;
- historical cache-inspector data is lost.

Take a backup when preserving warm-cache state, persisted evaluation datasets,
or retained aggregate run history is worth the security and recovery cost. A backup can retain dataset
content after application expiry or explicit deletion, so backup retention and
secure erasure are separate operator responsibilities. The operator performing
a deployment owns backup, rotation, rollback, and verification. Provider owners
must be informed before a destructive rebuild that can increase provider
traffic or cost.

## Safety rules

- Never practice against a production volume.
- Keep the current and replacement credentials until verification succeeds.
- Load credentials from a secret manager into environment variables; do not put
  passwords in tracked files, shell history, command arguments, or logs.
- Stop query traffic before rotating database roles.
- Never edit `semantix.schema_migrations` manually.
- Restore into a fresh volume rather than overwriting the only available copy.

The commands below assume `.env.production` and `docker-compose.prod.yml`.

## Rotate migration and runtime passwords

Changing `.env.production` alone does not rotate an existing PostgreSQL role.
Docker's initialization directory runs only when the data directory is new.
Use the current migration credential to change both roles transactionally, then
recreate services with the replacement credentials.

### 1. Prepare secrets

Load these values from a secret manager:

- `POSTGRES_DB`
- `POSTGRES_MIGRATION_USER`
- `POSTGRES_RUNTIME_USER`
- `CURRENT_POSTGRES_MIGRATION_PASSWORD`
- `NEW_POSTGRES_MIGRATION_PASSWORD`
- `NEW_POSTGRES_RUNTIME_PASSWORD`

Linux or macOS:

```bash
export PGPASSWORD="$CURRENT_POSTGRES_MIGRATION_PASSWORD"
export SEMANTIX_MIGRATION_USER="$POSTGRES_MIGRATION_USER"
export SEMANTIX_MIGRATION_PASSWORD="$NEW_POSTGRES_MIGRATION_PASSWORD"
export SEMANTIX_RUNTIME_USER="$POSTGRES_RUNTIME_USER"
export SEMANTIX_RUNTIME_PASSWORD="$NEW_POSTGRES_RUNTIME_PASSWORD"
```

Windows PowerShell:

```powershell
$env:PGPASSWORD = $env:CURRENT_POSTGRES_MIGRATION_PASSWORD
$env:SEMANTIX_MIGRATION_USER = $env:POSTGRES_MIGRATION_USER
$env:SEMANTIX_MIGRATION_PASSWORD = $env:NEW_POSTGRES_MIGRATION_PASSWORD
$env:SEMANTIX_RUNTIME_USER = $env:POSTGRES_RUNTIME_USER
$env:SEMANTIX_RUNTIME_PASSWORD = $env:NEW_POSTGRES_RUNTIME_PASSWORD
```

### 2. Stop traffic and rotate both roles

Stop the gateway and backend, but leave PostgreSQL running:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop frontend backend-a backend-b
```

Linux or macOS:

```bash
postgres_container=$(docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres)
test -n "$postgres_container"
docker cp ops/postgres/rotate-role-passwords.sql "$postgres_container:/tmp/rotate-role-passwords.sql"
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD -e SEMANTIX_MIGRATION_USER -e SEMANTIX_MIGRATION_PASSWORD -e SEMANTIX_RUNTIME_USER -e SEMANTIX_RUNTIME_PASSWORD postgres psql --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --file /tmp/rotate-role-passwords.sql
```

Windows PowerShell:

```powershell
$PostgresContainer = docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres
if (-not $PostgresContainer) { throw "The production PostgreSQL container is not running." }
docker cp ops/postgres/rotate-role-passwords.sql "${PostgresContainer}:/tmp/rotate-role-passwords.sql"
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD -e SEMANTIX_MIGRATION_USER -e SEMANTIX_MIGRATION_PASSWORD -e SEMANTIX_RUNTIME_USER -e SEMANTIX_RUNTIME_PASSWORD postgres psql --host 127.0.0.1 --username $env:POSTGRES_MIGRATION_USER --dbname $env:POSTGRES_DB --file /tmp/rotate-role-passwords.sql
```

The SQL fails before changing either role when a role is missing or either new
password is empty. Both password changes commit together.

### 3. Update configuration and recreate services

Update both password values in the deployment secret store or
`.env.production`, then recreate the services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate postgres
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate migrate backend-a backend-b frontend
```

The migration job must exit successfully before the backend becomes healthy.
Afterward, remove the temporary SQL file and clear the temporary secret
variables from the operator shell.

### 4. Verify

Check service state and readiness:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl --fail http://127.0.0.1:8080/ready
```

Submit a unique prompt through the Monitor or `POST /api/v1/query`, then submit
the same prompt again. The first request must be a miss and the second must be a
hit. Confirm the cache inspector can read the new entry.

### Rotation rollback

If role rotation commits but the recreated stack fails:

1. Keep traffic stopped.
2. Connect using `NEW_POSTGRES_MIGRATION_PASSWORD`.
3. Run the same SQL file with the previous migration and runtime passwords as
   the target values.
4. Restore the previous deployment secret version.
5. Recreate PostgreSQL, migrate, backend, and frontend again.
6. Repeat readiness and cache-round-trip verification.

Do not restore only the environment file after the database roles changed; that
creates the same credential mismatch in reverse.

## Back up PostgreSQL data

Create a custom-format dump without ownership or access-control statements:

```bash
mkdir -p backups
postgres_container=$(docker compose --env-file .env.production -f docker-compose.prod.yml ps -q postgres)
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD postgres pg_dump --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --format custom --no-owner --no-acl --file /tmp/semantix.dump
docker cp "$postgres_container:/tmp/semantix.dump" backups/semantix.dump
```

In PowerShell, create the directory with `New-Item -ItemType Directory -Force
backups` and use `"${PostgresContainer}:/tmp/semantix.dump"` as the `docker cp`
source.

Record the application commit, migration list, embedding provider/model,
embedding dimensions, evaluation-dataset storage/retention settings,
run-history storage/retention/capacity settings, database name, and dump
checksum beside the backup. Treat the dump as sensitive because
it can contain cached provider responses plus persisted dataset prompts and
notes. A backup made for one embedding space is not automatically useful after
changing the embedding model or dimensions.

## Restore a backup

Restore only into an empty, isolated volume:

1. Stop the stack.
2. Move the old volume aside or create a separate Compose project.
3. Start only PostgreSQL so initialization creates both database roles.
4. Copy `semantix.dump` into the new PostgreSQL container.
5. Restore as the migration role:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e PGPASSWORD postgres pg_restore --host 127.0.0.1 --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" --exit-on-error --no-owner --no-acl /tmp/semantix.dump
docker compose --env-file .env.production -f docker-compose.prod.yml up --force-recreate migrate
```

The migration job verifies migration checksums and restores runtime grants.
Verify the extension, schema, and row counts:

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT version, checksum FROM semantix.schema_migrations ORDER BY version;
SELECT COUNT(*) FROM semantix.cache_entries;
SELECT COUNT(*) FROM semantix.cache_namespace_counters;
SELECT COUNT(*) FROM semantix.evaluation_datasets;
SELECT COUNT(*) FROM semantix.evaluation_dataset_cases;
SELECT COUNT(*) FROM semantix.evaluation_runs;
SELECT COUNT(*) FROM semantix.evaluation_run_thresholds;
```

Then start the backend and frontend, check `/ready`, execute a cache round trip,
and verify a namespace-authorized dataset list/detail request when persistence
is enabled. Expired dataset rows restored from an older backup remain hidden
and are purged opportunistically. Keep the old volume and backup until
verification completes.

## Discard and rebuild the cache

This is the default recovery path only when cache preservation is unnecessary
and all PostgreSQL-backed evaluation data that matters, including persisted
datasets and durable run history, is disabled, separately backed up, or
intentionally disposable. Double-check the volume label before deletion:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
docker volume inspect semantix-prod_pgvector_data
docker volume rm semantix-prod_pgvector_data
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
```

Do not substitute a wildcard or delete every Docker volume. The next startup
creates the roles, runs migrations, and starts with empty cache tables and
counters. It also permanently removes the volume's persisted evaluation
datasets and retained aggregate run history. Plan for cold-cache latency and provider usage while entries warm.

## Migration rollback

Each migration and its version record are applied in one transaction. A failed
migration rolls back without recording that version. Applied migrations are
forward-only and checksum protected.

For an application regression without destructive schema changes, redeploy the
previous application image and leave the database intact. For an incompatible
schema regression:

- discard and rebuild the volume only when cache, persisted dataset data, and
  retained run history are disposable; or
- restore the pre-deployment dump into a fresh volume when it must be retained.

Never rewrite an applied migration, remove its checksum row, or improvise a
down-migration during an incident.

## Incident checklist

1. Stop frontend and backend traffic.
2. Record the time, deployed commit, Compose state, readiness response, and
   sanitized logs.
3. Decide whether the incident is credential mismatch, migration failure,
   storage failure, or application regression.
4. Preserve the volume or take a dump when evidence or warm-cache state matters.
5. Use rotation rollback, application rollback, fresh restore, or destructive
   rebuild as documented above.
6. Verify role connectivity, migration checksums, `/ready`, and a cache round
   trip.
7. Reopen traffic and monitor provider calls, latency, cache misses, and errors
   during warm-up.
8. Rotate any credential that may have been exposed and document the incident
   owner, decisions, and follow-up work.
