# Valkey official application validation

The existing RedisStore, `CACHE_BACKEND=redis`, Python HTTP SDK and React dashboard
were validated against a bounded Valkey deployment. There is no ValkeyStore,
alternate client or dashboard-specific storage algorithm; `valkey` is not a valid
`CACHE_BACKEND` selector.
Keep the [package contract](../embedded/redis.md#valkey-912) and
[operator setup procedure](../guides/platform-storage.md#redis-setup-permissions-and-recovery).

## Tested profile and implementation boundary

| Property | Recorded profile |
| --- | --- |
| Service | Valkey **9.1.2 GA**, Linux AMD64 container |
| Immutable image | `valkey/valkey:9.1.2@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd` |
| Application/client host | Windows, CPython **3.14.6**, Docker Desktop Linux engine **29.6.2** |
| Driver | redis-py **8.1.0**, binary RESP2, finite deadlines, zero automatic driver retries |
| Topology | Direct standalone writable primary, cluster disabled, `noeviction`; task-local loopback plaintext transport |
| Persistence tested | AOF enabled, `appendfsync always`, controlled same-product restart |
| Providers | Deterministic mock and genuinely registered custom providers; no paid inference |
| Application source | Initial HTTP/browser and historical fault records: `50662ab7af43c903a1e95b8c97cdfe12dc7d0fe6`; corrected custom-provider/fault continuation: `dca605450180f239d6d466b396eb4e55c53532e6` |

The standalone-primary/noeviction, client-policy and binding constraints are
implementation requirements. AOF/always, Docker, loopback transport and fixture
resource limits are test choices, not universal deployment settings. Operators own
persistence, backups, transport security, credentials and isolation. These results
do not justify plaintext over an untrusted network or certify Valkey TLS.

Initialization verifies INFO product/version, primary role, standalone mode,
noeviction and required commands. Valkey's `redis_version=7.2.4` is a compatibility
field, not its product version. Normal server startup connects to and validates an
existing binding; it neither initializes storage nor repeats every setup probe.
Custom providers require the deployment's registry-aware programmatic operator
bootstrap; the existing CLI resolves built-ins only. Setup and runtime authority
remain separate.

Current code defines the [store admission and binding checks](../../packages/cache/src/semantix_cache/stores/redis.py),
[operator setup](../../apps/server/app/cache/infrastructure/setup.py),
[server ownership](../../apps/server/app/cache/infrastructure/factory.py) and
[readiness probe](../../apps/server/app/api/health.py). Package CI selection lives in
the [Quality workflow](../../.github/workflows/quality.yml); the local application
records below are separate evidence.

## What the retained evidence establishes

| Layer | Result and limits |
| --- | --- |
| Package interoperability | Qualified exact identity/commands, ACL restrictions, binding and namespace isolation; reuse of existing RedisStore semantics rather than a new backend |
| Official application | Real installed FastAPI HTTP and production-built React/Playwright flows, without mocking the main API; query miss/persisted hit, Inspector/admin, role/namespace restrictions, diagnostics and SDK decoding |
| Initial application evidence | 71 recorded HTTP observations, 34 selected backend test passes and three browser modes; observations and browser modes are not additional pytest totals |
| Persistence/outage | Earlier passing controlled AOF restart, absolute TTL/revision/recency and real HTTP outage/recovery evidence; not a crash or power-loss guarantee |
| Corrected lifecycle | Three real-Valkey custom-provider cases pass: all callers cancel, retained scoring drains, and explicit terminal busy-close failure; one additional sdist lifecycle repeat passes |
| Application lost replies | Two actual HTTP cases pass: the selected upstream put/hit executes once and its successful reply is withheld; HTTP reports sanitized 500 while stored effects remain visible, without replay |
| Remaining faults | Assertion-based OOM/noeviction, replica/read-only, eviction-policy and binding-drift controls; reported separately from pytest counts |
| Installed distribution | Fresh server/cache wheels and sdists built from the corrected source, installed outside the repository; module origins/bytes checked, no source fallback. A separate cache-only environment has no FastAPI/server installation |

The continuation recorded **six live pytest passes** across five scenario identities
(one sdist repeat), plus **eight controller-unit passes**. Its completed selections
had zero failures/errors/skips; two other lifecycle variants were intentionally
deselected in the sdist repeat. Historical native fault evidence has **21 package
passes**, while the earlier server selection has **23 passes and five failures**.
Those historical results remain unchanged and are not added to a new aggregate or
presented as freshly rerun CI. The continuation supplies separate successful evidence
for the five previously blocked scenarios.

The HTTP reply-loss controller ran outside the product, forwarded the exact selected
mutation once, observed its actual upstream response and withheld only that reply.
Ordinary runtime ACLs still denied `CLIENT REPLY`; no extra runtime privilege was
granted. This tests one precisely controlled transport fault, not arbitrary networks.
Private worker/pool observations and event barriers were test instrumentation, not
new public interfaces or production behavior.

## Operational limits

- **Readiness:** `/ready` and diagnostics observe read-only cache statistics, not
  continuous writable-primary/noeviction admission. Real OOM and replica mode left
  them green while writes and hit confirmation failed. Policy drift was rejected by
  operator setup but not continuously detected by runtime readiness.
- **Mutation uncertainty:** HTTP 500 or cancellation after dispatch does not imply
  rollback. The lost-put case persisted the entry; the lost-hit case incremented its
  hit count once. No automatic replay or distributed exactly-once guarantee follows.
- **Binding failures:** dirty status or mismatched capacity produced ready 503,
  diagnostics unavailable and query failure, without automatic repair. Restoring a
  precisely known injected field is not a recovery recipe for an uncertain mutation.
- **Browser permissions:** non-admin list delete/clear controls remained visible in
  the recorded UI; the server correctly rejected unauthorized mutations. UI visibility
  is not the authorization boundary.
- **Shutdown:** graceful draining succeeded when retained work settled. An active
  scoring worker at the terminal close boundary produced explicit cleanup failure;
  Redis physical disposal had not succeeded. That test used zero query grace to reach
  the boundary, not to change the production grace. Later explicit fixture cleanup
  after worker release is not automatic application recovery or guaranteed termination.
- **Outside certification:** other Valkey versions, application host operating systems,
  CPU architectures, driver combinations, TLS, managed services, HA/failover, production
  load, arbitrary network faults, crash/power-loss durability and Redis/Valkey data-file
  migration. Separate package CI evidence does not certify those application profiles.

## Provenance, interruptions and preservation

The following bundles are retained outside the repository. Names and SHA-256 values
identify their `final-receipt.json`; they are not downloadable CI artifacts or a
substitute for independent reproduction.

| Retained bundle | Original result | Receipt SHA-256 |
| --- | --- | --- |
| `valkey-v1-20261022/controlled-resumption-4` | Fixture qualification PASS under the approved preservation criterion | `a5ae757e6aba21560e48818ef007fb513ca1f055db96fa2f1343049ced0eab2d` |
| `valkey-v2-20261022` | Bounded application PASS / KEEP | `a28cef814466897d4ef7c72579e76828fab9a1b21ace6ab7285461c0539a6ec6` |
| `valkey-v3-20261022-run2` | NOT VERIFIED / BLOCKED; passing observations reused, five failures preserved | `fa4882438626cb4d0c089f2108a66ac54b7a5863da616a4f42156cad5c782189` |
| `valkey-v3-continuation-20261022` | Bounded PASS / KEEP; executed 2026-10-23 | `edc772c8953e654c7cb049091e6c4014e253b4a15cd09f228ef7fba5883a668d` |

The continuation's `artifact-identities.json`, frozen protocol, exact JUnit node
records, fault ledgers, per-attempt logs, cleanup receipts and checksum manifest
retain the detailed evidence. The original fixture preservation failure and first
interrupted restart remain NOT VERIFIED. Two continuation harness interruptions
(ACL-response parsing and a reused nonempty sdist binding) also remain recorded;
they were not silently reclassified as product passes.

Docker preservation prospectively allowed only built-in default-bridge ID/Created
changes when all other configuration and endpoints matched. Their cause remains
unexplained; this exception does not permit changed user-owned resources. Cleanup
receipts verify removal of task-created containers, volumes, networks and ACL files,
closed application/controller ports, settled successful pools and exited processes.
Original user containers were stopped, so no running user-workload connectivity
claim follows. None of this retroactively passes the historical preservation stop.

The continuation reused earlier passing AOF/native-fault evidence under its original
source and execution identity; it did not rerun the full CI matrix, package coverage,
browser or SDK suite. This documentation finalization runs no infrastructure or
new product experiments and does not claim fresh runtime certification.
