# MySQL storage

`from semantix_cache.stores.mysql import MySQLStore` adds dedicated-database
persistence to the embedded package. It implements the unchanged `CacheStore`
contract with exact float64 cosine scoring. It does not add a server/dashboard
backend, inspector, `clear_all`, native vector search or an approximate index.

## Install and connect

**0.1.0 is unpublished.** Build a [local wheel](../../packages/cache/README.md#use-in-another-python-project),
then install its optional extra in your application's environment:

```text
python -m pip install './dist/semantix_cache-0.1.0-py3-none-any.whl[mysql]'
```

Adjust the path for your consumer project. This adds **PyMySQL 1.2.3**, an MIT
licensed synchronous driver, without changing the NumPy/Pydantic core. Root
imports do not load PyMySQL. No global asyncio loop-policy change is needed.
Windows default Proactor and Linux default-loop clients on Python 3.11–3.14
have been exercised against MySQL Community **8.4.12/InnoDB**. The new workflow
targets Linux; hosted execution is pending. Local Windows evidence does not
establish hosted Windows/MySQL coverage. Tests used x86-64 clients; other CPU
architectures and free-threaded builds are unverified.
macOS, MariaDB, Aurora, TiDB, HeatWave, replicas, failover, IPv6 and DNS dialing
are outside the verified boundary. Other 8.4 patches pass the major/minor check
but require their own evidence; they are not certified by the 8.4.12 tests.

Use a canonical numeric IPv4 `address` and a separately verified
`tls_hostname` from the server certificate. Supply a trusted CA file. CA and
hostname verification, TLS >=1.2 and secure server transport cannot be disabled.
Credentials are separate arguments, not a DSN. Store them in your application's
secret handling; never put production credentials in examples or logs.

After the operator setup below, inject the store into your existing facade:

```python
import os
from semantix_cache import AsyncSemanticCache
from semantix_cache.stores.mysql import MySQLStore

# embedder and generate are your existing application-owned integrations.
async def use_cache(embedder, generate):
    async with (
        await MySQLStore.connect(
            address=os.environ["MYSQL_ADDRESS"],
            tls_hostname=os.environ["MYSQL_TLS_HOSTNAME"],
            ca_file=os.environ["MYSQL_CA_FILE"],
            user=os.environ["MYSQL_RUNTIME_USER"],
            password=os.environ["MYSQL_RUNTIME_PASSWORD"],
            database="semantix_cache_app",
            embedding_space=embedder.embedding_space,
        ) as store,
        AsyncSemanticCache(embedder=embedder, store=store) as cache,
    ):
        return await cache.resolve("application prompt", generate=generate)
```

Reuse the store across requests. The facade borrows it and does not close it.
Each store owns one connection and one dedicated worker in its creating process
and event loop. There is no borrowed-connection or pool option. Independent
stores/processes coordinate through InnoDB, not shared Python state.

## Explicit operator setup

Provision a **dedicated empty database**. MySQL names must be lowercase ASCII,
start with a letter and contain only letters, digits or underscores, <=64
characters. System databases are refused. Use a single writable primary with
`require_secure_transport=ON`, `innodb_flush_log_at_trx_commit=1`, and
`max_allowed_packet >=4 MiB`. If binary logging is enabled, require
`sync_binlog=1` and `binlog_format=ROW`. The adapter verifies those settings and
sets strict UTF-8, UTC, isolation and bounded session timeouts.

An account administrator creates the database/accounts and direct grants.
Replace password placeholders through a secure provisioning mechanism and
restrict account host patterns to your deployment. These are privilege sketches,
not a script to paste with the placeholder passwords:

```sql
CREATE DATABASE semantix_cache_app CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'semantix_schema_verifier'@'localhost' ACCOUNT LOCK;
GRANT SELECT, TRIGGER, EXECUTE, EVENT ON semantix_cache_app.*
  TO 'semantix_schema_verifier'@'localhost';

CREATE USER 'cache_setup'@'%' IDENTIFIED BY '<setup-secret>' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, REFERENCES,
  CREATE ROUTINE, EXECUTE, TRIGGER, EVENT ON semantix_cache_app.*
  TO 'cache_setup'@'%';
GRANT SET_ANY_DEFINER ON *.* TO 'cache_setup'@'%';

CREATE USER 'cache_runtime'@'%' IDENTIFIED BY '<runtime-secret>' REQUIRE SSL;
```

Run `await MySQLStore.initialize_schema(...)` once with the setup principal and
the same endpoint, TLS, database, embedding-space, capacity and default-TTL
arguments used for runtime. Defaults are capacity 500 and TTL 3,600 seconds;
pass `default_ttl_seconds=None` explicitly for unlimited default retention.
Setup registers that exact identity/dimension/policy binding. Register additional
bindings explicitly; runtime cannot invent them or change policy.

After successful setup, grant only:

```sql
GRANT SELECT ON semantix_cache_app.semantix_schema_migrations TO 'cache_runtime'@'%';
GRANT SELECT, UPDATE ON semantix_cache_app.semantix_bindings TO 'cache_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON semantix_cache_app.semantix_entries TO 'cache_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON semantix_cache_app.semantix_payloads TO 'cache_runtime'@'%';
GRANT EXECUTE ON PROCEDURE semantix_cache_app.semantix_verify TO 'cache_runtime'@'%';
REVOKE SET_ANY_DEFINER ON *.* FROM 'cache_setup'@'%';
```

Runtime needs no TRIGGER, CREATE, ALTER, DROP, broad database SELECT or foreign
table privilege. These grants do not revoke preexisting privileges: use a fresh
restricted account. Namespace partitioning is not authentication or authorization;
any account with these DML grants is trusted to write cache data.

MySQL DDL is not one rollbackable transaction. Setup uses a finite database-wide
lock and leaves `INITIALIZING` until exact verification succeeds. Failure can leave
partial owned objects; preserve and inspect them. Repeated setup/runtime refuses
partial, foreign or version-1-only schemas rather than repairing or adopting them.
Do not automatically repeat setup after an uncertain DDL outcome. SQL migrations,
the canonical shape JSON and verifier are immutable packaged resources; readiness
requires exactly versions 1 and 2 with the expected owner, checksums and codec.

## Authoritative schema verifier and maintenance

Runtime catalogs are privilege-filtered: a hidden table or trigger cannot be
detected by counting runtime-visible objects. A static no-argument
`SQL SECURITY DEFINER` procedure verifies the complete relevant catalog as the
locked `semantix_schema_verifier@localhost` account. It checks the four owned
tables, complete column/index/constraint descriptors, zero extra tables/triggers/
events/routines, migration identity, direct definer grants, and its own fixed
routine descriptors. Python checks the packaged body digest independently.
Its fixed result contains only version, validity and definition digest, not schema
data, arbitrary SQL or caller-selected identifiers. Connection and operation
checks fail closed on drift, revocation or missing/changed verifier.

The definer has no DML or global data grants. TRIGGER and EVENT nevertheless
confer creation capability: **keep its login locked** and its reviewed SELECT
body unchanged. `READS SQL DATA` alone is advisory, not a read-only sandbox.
One fixed account can receive direct grants on multiple dedicated databases;
keep it alive while any verifier references it.

Drain all stores before privileged schema, routine, account or grant maintenance.
MySQL 8.4 guards DROP/RENAME of referenced definers for ordinary administrators;
an administrator with `ALLOW_NONEXISTENT_DEFINER` can override that guard. An
orphan verifier fails when invoked. Removal requires ALTER ROUTINE authority:
remove the procedures, revoke their grants, then remove the account when no
references remain. Authorized replacement requires trusted provisioning of the
exact definition/migration identity and regranting routine EXECUTE after DROP.
The adapter never performs account maintenance or automatic upgrades.

Verification is a check, not an atomic lock over subsequent DDL. An existing
repeatable-read transaction can retain an earlier catalog view; operations begun
after committed drift and newly connected stores reject it. A privileged
administrator can maliciously replace both schema and verifier. This mechanism
does not protect against that administrator or remove every TOCTOU race.

## Operations, cancellation and uncertain outcomes

At most 32 admitted operations serialize on the owned worker. Admission, SQL,
transactions and completion share finite deadlines: connect defaults to 10 s,
operation and close to 30 s; accepted positive finite values are <=86,400 s.
Network connect has an independent 2 s bound. Ordinary socket reads/writes
have an immutable **0.5 s** stall bound; initialization alone uses a finite
**2 s read** bound for durable DDL. Initialization writes stay at 0.5 s. Session lock waits are 1 s and SELECT execution
1,000 ms. A larger operation budget does not relax these bounds. Slow network,
DDL/fsync or an overloaded host can therefore fail sooner than the total budget.
Real I/O-contention diagnostics reproduced successful server DDL taking longer
than the former 0.5 s read budget. The setup-only budget was adjusted after
controlled server-delay and cancellation/ambiguity tests. This does not identify
the unique cause of every historical timeout or guarantee success under arbitrary
load. When duplicate-socket interruption fails, initialization can retain its
bounded cleanup owner until the finite read ends; inspect recovery status rather
than treating cancellation as physical disposal.

Cancellation cannot force a Python thread to stop. The owned duplicate socket
interrupts I/O with shutdown; actual resource disposal remains on the owner
thread. Completion ownership survives caller cancellation. Interrupted proven
reads retire their session; a later independent call can open and validate a new
session. The cancelled operation is never replayed. Uncertain mutations, COMMIT
or cleanup fault the store. A timeout does not prove rollback or non-commit:
reconcile the business outcome before any application-requested retry. There is
no automatic cache-operation replay or ambiguous-transaction retry.

Drain admitted work before `aclose()`; busy close raises `CacheBusyError`.
Repeated successful close is harmless. A constructed store remains caller-owned
after close failure; correct the cause and explicitly call `aclose()` again.
Public driver-close failure is distinct from physical socket disposal, and
errors are still reported when independently retiring the OS resources succeeds.

Failed construction has no returned store. Inspect
`MySQLStore.failed_cleanups()` for immutable sanitized `MySQLCleanupStatus`
records; use `await MySQLStore.retry_cleanup(status.cleanup_id)` for **one**
explicit disposal-only attempt. It never repeats SQL. Pending attempts coalesce
and survive cancellation/original-loop exit; recovery can use another loop in
the same process while disposing on the original thread. States distinguish
`pending`, `retained`, `retired` and `escalation-required`; no credentials or
driver tracebacks are exposed.

Eight process-local construction/retained-owner slots are reserved before worker
allocation. This also limits simultaneous construction; it is not a limit on
successfully opened stores. A ninth reservation raises `CacheBusyError`.
Each owner retains at most five resource-object slots and one worker. Eight
separate terminal receipts retain no executor/configuration and expire by ring
eviction. Inspection/recovery reaps completed ownership after physical retirement
and worker exit. There is no unlimited background cleanup registry.

Stop new construction, drain ordinary stores and inspect/retry retained cleanup
before shutdown. A permanently failing physical close or blocked worker remains
bounded and accountable; the library cannot promise forced retirement. If a
failed close invalidates its handle, the receipt preserves uncertainty and
refuses descriptor reuse. Arrange an **operator-controlled process restart** if
explicit recovery cannot retire ownership. No daemon-thread substitution, GC
disposal, automatic process exit or infinite retry is used.

## Exact search, retention and measured costs

Capacity is 1–5,000, dimensions 1–16,000 and
`capacity * dimensions * 8 <=64 MiB`. These are admission bounds, not a latency
or RSS guarantee. Each lookup validates the binding, transfers all eligible
vectors in 64-row pages, builds a complete float64 matrix, scores off the event
loop, then revalidates and loads the winning payload. The facade confirms its
revision/expiry atomically before returning a hit. There is no threshold filter
inside the store. Payloads are bounded to 1,230,000 encoded bytes, statements to
less than 4 MiB. Vectors use a versioned little-endian float64 codec.

In a local Windows 3.14 client/Docker Desktop 8.4.12 run with 1 KiB responses,
five lookups per workload measured median **32 ms (32×2), 59 ms (500×128),
354 ms (5,000×2), 2.81 s (5,000×1,536), 0.81 s (512×16,000)**. The two large
workloads transferred about 63.1/65.8 MB per lookup and peaked at 193/205 MB
client RSS; the matrix budget is not total memory. A 5 ms heartbeat recorded
maximum lag up to 25.9 ms. Eight concurrent reads serialized, reaching only
0.42/s at 5,000×1,536. These short measurements include real verification,
snapshot retrieval and scoring; they are not hosted-network, production-load
or percentile guarantees. Fixture bulk seeding was excluded from public-write
throughput. Small-cache workloads suit this implementation better than repeated
large exact scans.

Confirmed hits write under the binding-wide InnoDB writer lock. LRU is shared
across namespaces of a binding. Monotonic revisions survive clear/delete and
independent-process writes. TTL uses server UTC microseconds, does not slide on
hits and can be extended by server clock rollback. Database durability/backup,
encryption at rest, clock discipline and topology are operator responsibilities.
Restoring an earlier backup requires a new embedding-space generation to avoid
historical revision reuse; do not reuse stale candidates from before restore.

## Disposable verification

From `packages/cache`, with Docker and an installed OpenSSL CLI:

```text
uv sync --locked --extra dev
uv run --no-sync python ../../ops/ci/mysql_fixture.py -- uv run --no-sync pytest -m mysql
```

The helper uses the digest-pinned MySQL Community **8.4.12** artifact, generated
credentials and CA/valid/expired certificates. It verifies fixture identity,
executes mandatory conformance/security/lifecycle tests, then stops only its
labelled containers and preserves their volumes/private evidence for diagnosis.
Do not point tests at a developer or production database, publish private fixture
receipts/keys, or prune Docker globally. Readiness retries are bounded probes;
business operations and tests are not automatically retried. Full package
coverage also requires the separate disposable PostgreSQL and Redis fixtures.
