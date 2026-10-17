# Redis storage for embedded Python caching

RedisStore is an optional structural CacheStore. It shares the existing
AsyncSemanticCache policy, threshold, namespace and revision contract.

Install `semantix-cache[redis]` when the package is published. Before publication,
install a built local wheel with its `[redis]` extra:

```bash
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[redis]'
```

Import `RedisStore` from `semantix_cache.stores.redis`. Root imports and unrelated
stores require no Redis driver. The extra adds direct redis-py
`>=7.4.1,<8.2,!=8.0.0`; it requires no hiredis, RedisVL, RedisJSON or provider framework.
Runtime accepts exactly **7.4.1**, **8.0.1**, and canonical stable **8.1.x** patch
versions. Development locks and the optional server keep the 8.1.x baseline
(resolved to 8.1.0). Normal installation selects that newer baseline.

The dependency interval cannot express the disjoint runtime policy. It explicitly
excludes 8.0.0; other unverified 7.x/8.0.x releases and prerelease, development,
post-release, vendor/local or malformed version strings fail runtime admission.
The interval is not a claim that every intermediate or future release is supported.
Pin an alternate explicitly in the same resolver transaction:

```bash
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[redis]' 'redis==7.4.1'
# Or use redis==8.0.1. No --no-deps override is needed.
```

The package certifies Semantix's direct standalone Redis usage. [Upstream 8.0](https://github.com/redis/redis-py/releases/tag/v8.0.0)
changed protocol, retry and response defaults; Semantix continues to require
explicit binary RESP2, async Retry(NoBackoff(), 0), standard pools/parsers and
finite socket deadlines on all admitted drivers. The older releases retain
verified TLS defaults and the earlier connection-pool credential-repr fix.
[Upstream 8.0.1](https://github.com/redis/redis-py/releases/tag/v8.0.1) fixes Pipeline.reset cancellation cleanup; Semantix does not use
pipelines, PubSub, Cluster or MultiDB, so this compatibility evidence does not
certify those driver features. Prefer the current 8.1.x baseline and review
security updates; no upstream long-term backport guarantee was found.

## Supported deployment and work limits

The supported deployment is a directly addressed writable standalone primary using
**noeviction**. Operators configure that policy; Semantix never changes server
configuration. Cluster, Sentinel, automatic failover, replica reads, active-active,
Valkey and universal managed-provider compatibility remain outside this boundary.

### Supported versions

Server admission accepts only the release families and conservative patch floors
below. The server matrix uses **redis-py 8.1.0**; driver certification is listed separately.
The required [Quality workflow](../../.github/workflows/quality.yml) checks the
actual Redis identity and exact version before counting test results.

| Redis family and minimum | Exact CI server | CI execution | Prior experimental server |
| --- | --- | --- | --- |
| 7.4.x, >=7.4.11 | 7.4.11 | Full embedded suite: Python 3.11; Redis suite/faults/wheel: 3.14 | 7.4.11 |
| 8.2.x, >=8.2.10 | 8.2.10 | Full embedded suite and wheel: Python 3.12 | 8.2.10 |
| 8.4.x, >=8.4.7 | 8.4.7 | Redis suite/faults/wheel: Python 3.14 | 8.4.7 |
| 8.6.x, >=8.6.7 | 8.6.7 | Full embedded suite and wheel: Python 3.13 | 8.6.7 |
| 8.8.x, >=8.8.3 | 8.8.3 | Redis suite/faults/wheel: Python 3.14 | 8.8.3 |
| 8.10.x, >=8.10.2 | 8.10.2 | Full embedded suite, wheel and real faults: Python 3.14 | 8.10.2 |

Each CI image has an immutable digest. Redis suites include shared conformance,
layout, inspection, concurrency, cancellation and fault tests, with collection-bound
JUnit verification and no skipped cases. Real fault runs cover graceful AOF restart,
out-of-memory refusal and read-only replica refusal. Full embedded jobs retain their
package coverage gate and the four explicitly permitted optional conformance skips.

The prior experiments used isolated server-admission changes for the five added
targets. They support the choice of targets; the CI table above tests the shipped
implementation. These are Linux service containers with standard CPython clients,
not certification of every Python/server/platform permutation.

Floors are the tested patch baselines, not a claim that every earlier patch is broken.
Later patches within these six families are admitted but remain unverified until
tested; intermediate families and future major/minor versions are not admitted.
Recommend current security-patched releases and validate your exact deployment.
As of 2026-10-16 these families appear in the upstream
[security-supported version list](https://github.com/redis/redis/security/policy).
Maintainers must review that list and update pins, tests and floors as support changes.

Redis 7.2 and earlier lack the native hash-field expiration required here.
Initialization checks `EVAL`, `EVAL_RO`, `HPEXPIREAT` and `HPEXPIRETIME` explicitly;
the [hash-field expiration commands](https://redis.io/docs/latest/commands/hpexpireat/)
were introduced in Redis 7.4. A compatible-looking version cannot replace those
checks. Redis 8.0 is intentionally excluded from the policy and the upstream
security-supported list. Other unlisted families, malformed/vendor-suffixed
versions and identified Redis forks are rejected. Driver versions 7.4.1/8.0.1
do not imply Redis 8.0 server support. Valkey, managed failover and clustered
deployments require separate compatibility work.

### Verified driver combinations

| Client OS / CPython | Redis server | redis-py | Evidence |
| --- | --- | --- | --- |
| Linux / 3.11–3.14 | The six server targets above, with their listed Python coverage | 8.1.0 | Existing required jobs |
| Linux / 3.14 | 8.10.2 | 7.4.1 | Required full Redis suite, AOF/OOM/read-only controls and independent wheel |
| Linux / 3.14 | 8.10.2 | 8.0.1 | Required full Redis suite, AOF/OOM/read-only controls and independent wheel |
| Windows default Proactor / 3.14 | 8.10.2 | 7.4.1, 8.0.1, 8.1.0 | Local disposable-server suite, faults and wheels |
| Windows default Proactor / 3.11 | 7.4.11 | 7.4.1 | Local disposable-server suite, faults and wheel |

These are x86-64 clients and Linux service containers, not a Cartesian
server/driver/Python certification. Accepted later 8.1.x patches and other
combinations require their own evidence. macOS, other CPU architectures,
free-threaded Python and hosted Windows Redis jobs remain unverified.
These runs use loopback redis:// connections. TLS defaults were inspected, but
this is not a real TLS server/CA/hostname certification; validate the exact
rediss:// deployment separately. Existing deployment limits remain unchanged.

### Exact search and work limits

Search transfers all eligible vectors in the requested namespace and performs an
exact NumPy float64 cosine scan. It preserves negative similarities and orders
equal scores by revision, then cache key. There is no Redis Search, ANN, HNSW or
vector-set dependency. RedisStore returns the nearest candidate even below the
threshold; the engine decides threshold acceptance.

Default capacity is 500 entries across the entire binding, including all
namespaces. Maximum capacity is 5,000, maximum dimensions are 16,000, and
`max_size * dimensions * 8` must not exceed 64 MiB. These bounds limit a vector
projection, not process RSS, server memory or payload sizes. A 500 by 1,536 scan
transfers exactly 6,144,000 vector bytes (5.86 MiB), plus protocol/metadata overhead.
Lookup snapshots exclude all other prompts/responses; only the winner payload is
fetched. Candidate sets are never truncated. Measure your workload and provision a
dedicated primary when script blocking or transfer costs matter.

## Explicit setup and ownership

Construction and `connect()` do not create or adopt storage. Call
`initialize_schema(initialization_client=...)` explicitly during authorized
deployment. It verifies server version/mode/role, noeviction and required commands,
then atomically creates a fresh descriptor or validates an identical ready layout.
An unmarked partial layout, wrong type, checksum/space/policy mismatch or dirty
binding is an error. Repeated and concurrent identical initialization is safe.

Supply your existing embedding adapter. This example borrows both clients and
closes them explicitly in the application:

```python
import os

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from semantix_cache import AsyncSemanticCache, EmbeddingAdapter
from semantix_cache.stores.redis import RedisStore


def redis_client(url: str) -> Redis:
    return Redis.from_url(
        url,
        protocol=2,
        decode_responses=False,
        retry=Retry(NoBackoff(), 0),
        socket_connect_timeout=10,
        socket_timeout=30,
        max_connections=5,
    )


async def run(embedder: EmbeddingAdapter) -> None:
    runtime = redis_client(os.environ["SEMANTIX_REDIS_URL"])
    initializer = redis_client(os.environ["SEMANTIX_REDIS_INITIALIZATION_URL"])
    try:
        store = RedisStore(
            client=runtime,
            embedding_space=embedder.embedding_space,
            key_prefix="support_cache",
        )
        # Deployment step; ordinary application startup only validates.
        await store.initialize_schema(initialization_client=initializer)
        async with store:
            await store.validate_schema()
            async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
                await cache.set(
                    "approved answer", "Application-approved response",
                    namespace="support:tenant123",
                )
                hit = await cache.get("approved answer", namespace="support:tenant123")
                assert hit is not None
    finally:
        await initializer.aclose()
        await runtime.aclose()
```

`RedisStore(client=...)` never closes or mutates the supplied client/pool.
Use an ordinary `redis.asyncio.Redis` and `ConnectionPool`, binary responses,
RESP2, the asynchronous zero-retry policy, and positive finite socket deadlines.
Custom subclasses/pools, RESP3 and decoded responses are unsupported. Keep the
validated client policy stable. Standard pool exhaustion is a typed store error;
choose enough connections for your application's admitted concurrency.

For owned resources use:

```python
async with await RedisStore.connect(
    url=os.environ["SEMANTIX_REDIS_URL"],
    embedding_space=embedder.embedding_space,
    key_prefix="support_cache",
) as store:
    await store.validate_schema()
    # Reuse this store across requests.
```

Owned connection defaults are five connections and a ten-second startup deadline.
Operation and close deadlines default to 30 seconds, with a positive finite
86,400-second ceiling. Owned URLs accept redis/rediss credentials, endpoint and
database path, but reject query parameters/fragments that could override policy.
Use a supported borrowed TLS client for advanced TLS settings.

The engine borrows its store. Drain operations before store close: active
operations and retained numerical workers cause CacheBusyError without sealing
admission. Owned close seals once and shares one bounded cleanup task across
repeated/concurrent calls. Caller cancellation propagates while shielded cleanup
continues; repeated close observes its result. Borrowed close only seals the store.
Closing never deletes persisted cache data.

## Binding, entry state and permissions

Three keys share one hash tag:

```text
<key_prefix>:{<binding_digest>}:meta
<key_prefix>:{<binding_digest>}:entries
<key_prefix>:{<binding_digest>}:lru
```

The digest binds the exact EmbeddingSpace identity and dimension. Metadata checks
the full identity as well as layout checksum, capacity and default TTL policy.
Endpoint/database and prefix also determine the storage authority. Different
spaces/dimensions have different bindings. Conflicting capacity/TTL configurations
on an existing binding are rejected.

The permanent meta hash retains the revision/access counters and ready status.
The entries hash stores six fields per namespace/key member: strict UTF-8 JSON
payload, packed little-endian float64 vector, decimal revision microseconds,
absolute expiry microseconds, hit count and last-access microseconds. The LRU
sorted set stores unique access ranks. Prompts and completed responses are persisted;
apply your application's access, encryption, backup and retention policy.

Namespaces isolate cache operations; they do not authorize callers. Redis ACLs
protect keys and commands, not separate fields in the metadata hash. Restrict the
runtime role to the owned three-key patterns and prevent out-of-band writes.

Runtime commands include EVAL/EVAL_RO, TIME, TYPE, PTTL, EXISTS, HGET/HMGET,
HEXISTS, HSTRLEN, HLEN/HKEYS, HSET/HINCRBY/HDEL, ZCARD/ZSCORE/ZRANGE/ZADD/ZREM
and HPEXPIREAT. Explicit initialization additionally uses INFO, CONFIG GET and
COMMAND INFO. No FLUSH, broad key scan, CONFIG SET, SCRIPT LOAD, Functions
deployment or automatic schema migration is used. Setup authority is a deployment
rule; it is not a claim that a runtime ACL cannot modify metadata fields.

## Revisions, confirmation, expiry and capacity

The first revision is the caller's created_at. Later puts use the greater of the
requested timestamp and the last binding revision plus one microsecond. Exact
decimal/integer arithmetic preserves pre-1970 and far-future values. Overflow is
an error before mutation. Delete, clear and entry expiry preserve binding revision
history; persistence of that history is the operator's responsibility.

Lookup validates every eligible vector, scores an authoritative bounded snapshot,
then fetches only the winner under its expected revision. A winner replaced,
deleted or expired before that fetch produces None without a rescan. Corrupt
eligible data produces CacheStoreError.

Fixed Lua EVAL atomically confirms the exact revision and logical live deadline.
A rejected confirmation changes nothing. A successful confirmation increments hit
count once, records server last-access time and refreshes LRU without changing
revision or expiry. This is the authoritative hit point; later writes can still
replace the entry before the client receives the acknowledgement.

TTL defaults to 3,600 seconds. None inherits a finite default; explicit requests
are capped by it. With default None, a None request is immortal. TTL starts at
Redis TIME inside the write, independent of created_at. Positive TTL is rounded
down to whole microseconds; a submicrosecond duration expires immediately.

Logical expiry is inclusive and authoritative. Native HPEXPIREAT schedules each
entry field at the ceiling of the same absolute deadline in milliseconds.
Physical cleanup can lag; it never permits an expired hit. Successful hits restore
that same physical deadline when overwriting last-access and never slide TTL.
Replacement resets hit metadata and all field expiry, including finite/immortal
transitions. Redis wall-clock changes can affect retention; use stable server time.

Only put/replacement and successful confirmation refresh access rank. Search and
rejected confirmation do not. Puts purge expired/native-expiry tombstones before
enforcing binding-wide capacity and evict the least recently used live member.
Ranks are resequenced atomically before the ZSET exact-integer limit. Scoped delete
returns whether the entry was live; clear removes one namespace and counts only
live entries. Both preserve other namespaces and revision history.

## Failure, cancellation and recovery

The operation deadline includes worker admission, pool/I/O, decoding/scoring and
winner retrieval or mutation acknowledgement. Cancellation propagates; a retained
numerical thread keeps its slot until it finishes. Native client I/O cancellation
disconnects affected transports. Expected network, authentication, ACL, loading,
read-only, OOM and response failures become typed Semantix errors; messages, repr,
cause/context and formatted traceback exclude raw driver/payload details.
Programming errors are not broadly converted.

There are no hidden business retries, script-load recovery or automatic fallback.
If an acknowledgement is lost, or a caller cancels after dispatch, the mutation may
already have completed. A later explicit read can establish state; blindly retrying
a write or hit can change revision/count again.

Mutation scripts preflight predictable failures, set ready to mutating before
business writes, and restore ready last. A failure after writing leaves mutating;
later operations fail closed. Inspect and preserve required data, then recover
through reviewed operator tooling or a fresh prefix. There is no automatic repair,
marker reset or dirty-state-as-empty behavior.

Configure Redis persistence and backups for the required durability. A graceful
disposable AOF restart is covered by integration tests for entries, revision
history, hit metadata, LRU and absolute TTL accounting for downtime. That evidence
does not certify crash rollback, failover, restored old backups or distributed
exactly-once behavior.

## Contributor validation

From `packages/cache`, set REDIS_TEST_URL only to a disposable server from the
tested matrix, then run the complete Redis selection with its no-skip guard:

```text
python ../../ops/ci/required_tests.py redis .cache/redis.xml -- tests/test_redis.py tests/test_redis_faults.py tests/test_redis_layout.py tests/test_redis_scripts.py tests/test_inspection.py -k redis
```

The required CI matrix also rejects skipped Redis cases. The Docker restart/fault
harness additionally requires REDIS_TEST_CONTAINER naming a labelled
`semantix-redis-...` disposable container; it verifies ownership before restarting
or deleting its own resources. Set REDIS_TEST_VERSION to the exact expected
server version; `--verify-version` checks it without restarting the container.
The restart harness requires a digest-pinned Redis image and uses that same image
for its OOM/read-only containers. No database-wide flush is used.

`tests/redis_benchmark_smoke.py` measures synthetic 500 by 1,536 and 2,000 by 1,536
bindings and saves process/server/latency evidence under ignored .cache/.
For package verification, run the installed-wheel Redis smoke against disposable
Redis after installing the wheel's redis extra.
