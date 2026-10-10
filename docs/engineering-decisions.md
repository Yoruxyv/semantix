# Engineering decisions, trade-offs and limits

This is a present-day explanation of the implementation reviewed at
[`0fa24a1`](https://github.com/Yoruxyv/semantix/commit/0fa24a190cd511a079daf5e27f0d456c5c6a1f80),
whose executable contracts are unchanged from `b35246a`.
It does not reconstruct an author's unrecorded intent. Read
[architecture](../ARCHITECTURE.md) for wiring and
[product principles](../PRODUCT_PRINCIPLES.md) for durable goals. Recheck the
linked contracts when implementation changes.

**Implemented** means present in the reviewed source. **Evaluated and not
adopted** requires a recorded experiment; the verifier below is one such case.
Other **alternatives** are comparisons for maintainers, not claims that they
were prototyped or rejected. **KEEP** means retain the current boundary without
new machinery. A **trade-off** names a cost of that boundary; a **limitation**
bounds a guarantee; **not verified** means evidence is absent, not success or
failure. Explanations of why a design fits are inferred from its contracts and
stated principles unless an existing decision record is cited.

The evidence boundary is source inspection and the linked existing records.
Test pointers identify inspected assertions, not a claim that those tests were
executed for this review. This page provides no whole-repository semantic,
security or production certification. Sequences labelled **illustrative** explain
source-derived consequences, not new measurements or reproduced incidents.

## Decision map

| Decision | Benefit | Accepted cost | Applicability / evidence |
| --- | --- | --- | --- |
| [Embedded core](#an-embedded-core-with-optional-http-products) | Reuse stores without server policy | Caller-owned generation and lifetimes | Implemented; orchestration parity is bounded |
| [Local coalescing](#local-coalescing-with-distinct-caller-contracts) | Share work without distributed leases | Cross-replica duplicates; distinct cancellation | Implemented; server/embedded contracts differ |
| [Identity and policy](#explicit-context-policy-and-authorization-boundaries) | Separate compatibility, scope and permissions | Scope management reduces reuse | Implemented checks; trusted context is application-owned |
| [Storage](#storage-selection-and-persistent-ownership) | One port, explicit backends | Precision, clocks, setup and recovery differ | Implemented stores; deployment guarantees are conditional |
| [Similarity and verification](#similarity-reuse-without-a-production-answer-verifier) | Avoid treating proximity as correctness | False hits and retrieval misses remain possible | Implemented retrieval; bounded experiment explains verifier non-adoption |
| [Thresholds and evaluation](#human-controlled-thresholds-and-isolated-evaluation) | Inspect trade-offs outside live entries | Frozen projections cannot replay evolving state | Implemented; estimates are not bills |
| [Replica authorities](#shared-replica-authorities-with-local-execution) | Consistent abuse controls and threshold | Shared database availability is consequential | Supported two-backend Compose boundary; broader HA unverified |
| [Metric provenance](#observability-accounting-and-evidence-provenance) | Explain event populations honestly | Several counters cannot be directly reconciled | Implemented; process and browser scopes differ |

## An embedded core with optional HTTP products

Implemented: `semantix-cache` can run without the server.
Embedding and storage use structural ports; generation is an application-owned
async callable. The optional server delegates authoritative entries, revisions,
TTL and LRU to the package stores and shares semantic ordering helpers, while
owning HTTP orchestration, authorization and telemetry. `semantix-client` is a
separate HTTP client, not another cache engine.

Applications can reuse their generation flow without adopting
FastAPI or a workbench. A shared store implementation keeps entry semantics in
one owner without making embedded callers adopt server administration contracts.

An application that already owns a generation flow otherwise has to deploy HTTP
infrastructure merely to reuse an answer, or reproduce storage semantics itself.
The embedding adapter owns vector production and declared space; the store owns
current-entry confirmation; the caller owns trusted context and generation.
The server additionally owns principal resolution and its public schema. Shared
store behavior is intended parity, but identical result fields and cancellation
are not. Integrators must review both public contracts rather than substitute
one result type for the other.

KEEP these boundaries; require the entire server for every
consumer; or make the facade own provider selection and generation workflows.
Bundling would centralize setup but couple lightweight consumers to more policy
and dependencies.

Applications own credentials, context and
resource lifetimes. The facade closes itself, not borrowed dependencies. Server
and embedded orchestration/results still differ and need compatibility review.
Generation followed by a failed cache write raises instead of returning a
successful resolution; external generation effects cannot be rolled back.
There is no transaction across provider work and persistence or safe automatic
replay guarantee after an uncertain remote write.

**Illustrative write-failure sequence:** a NORMAL request misses; the caller's
generator returns a valid answer; the store write raises. No successful resolution
is returned with an implied write, but generation already happened. A rejected SQL
transaction can leave storage unchanged; a lost commit acknowledgement can leave
its outcome uncertain. An application wanting best-effort persistence needs an
explicit response/recovery policy. A retry may generate or write again; cancelling
the await does not refund a provider call. A shared borrowed pool must stay alive
until its owner's users drain; closing the facade does not close that pool.

Revisit when repeated consumer integration failures demonstrate a missing
shared contract, or a public API change needs a coordinated compatibility plan.
Similar-looking orchestration alone is insufficient evidence to merge owners.
A change would need package compatibility review, server/embedded parity cases
and explicit lifetime/failure tests before existing consumers migrate.

Evidence: [Public extension/ownership contract](../packages/cache/README.md#extension-and-ownership),
[server path dependency](../apps/server/pyproject.toml),
[store delegation](../apps/server/app/cache/infrastructure/backends/official.py),
[backend/package parity tests](../apps/server/tests/cache/infrastructure/backends/test_platform_parity.py),
and [generation/write failure boundary](context-identity-and-migration.md#generation-succeeds-but-persistence-fails).

## Local coalescing with distinct caller contracts

Implemented: in-flight sharing is local to an instance and
event loop, not a distributed exactly-once provider-call guarantee. Embedded
coalescing is opt-in for eligible NORMAL cold misses with an explicit context
key. Server `QueryService` chooses its own namespace/prompt/effective-policy key,
including for bypass work; it does not use the embedded facade's admission rules.

Concurrent equivalent misses can repeat generation. Local
sharing avoids a distributed ownership/lease protocol and keeps ordinary
embedded hits outside the registry.

Embedded flight identity includes relevant vector, policy/configuration and
callable identities, not just prompt text. Admission bounds retained coordination
state, not all generation concurrency. Independent fallback avoids making a full
registry a mandatory queue, at the cost of duplicate work under sharing pressure.

KEEP local sharing; leave embedded coalescing disabled for
independent samples or side effects; or introduce distributed coordination.
The latter requires explicit lease expiry, ownership and failure-recovery rules,
not just a shared cache database.

Embedded callers still embed separately.
Followers await the leader, then acquire their own confirmed hit; expiry or
replacement can require their own generation. Admission overflow falls back to
independent work. Follower cancellation affects that follower; leader
cancellation fails the flight, with no promotion or detached generation task.

The server instead shields its shared task from caller cancellation, so work can
continue after an awaiting caller leaves. A server follower receiving generated
text can report `cache_hit=false` and `provider_called=false`: following work is
not a cache hit. Sharing failures does not make provider or write effects atomic.
Separate replicas can still generate the same cold answer.

**Illustrative embedded sequence:** A and B independently embed and miss with
compatible flight identity. A leads and B waits. Cancelling B leaves A running.
Cancelling A before successful resolution publishes failure to attached followers;
B is not promoted. If A succeeds instead, B rechecks the store. Replacement or
expiry can make B generate for itself. The flight gate says preceding work ended,
not that a response remains reusable or that B holds a lease on A's entry.

**Illustrative server sequence:** A creates the task and B joins; A's caller
cancels its await. The shielded operation continues and may write after all callers
leave. If B remains and receives generated text, its result is a miss with no
provider invocation attributed to B. Shared-operation failure reaches awaiters;
cleanup permits future work without undoing external effects. Caller cancellation
and operation cancellation therefore have different ownership consequences.

Revisit when measured cross-replica duplicate work or required side-effect
semantics justify the extra coordination, with a defined failure and ownership
contract. Reduced call counts alone do not establish latency or correctness gains.
A distributed replacement would require lease expiry, fencing, recovery after
leader loss, retained-response rules, multi-process partition/cancellation tests
and a mixed-version rollout plan. A common database supplies no such orchestration
by itself.

Evidence: [Embedded eligibility and cancellation](../packages/cache/README.md#optional-cold-miss-coalescing),
[embedded implementation](../packages/cache/src/semantix_cache/engine.py),
[embedded cancellation tests](../packages/cache/tests/test_coalescing.py),
[server coalescer](../apps/server/app/query/application/coalescing.py),
[server accounting tests](../apps/server/tests/query/application/test_service.py),
and [two-replica evidence](operations/multi-replica-readiness.md#two-replica-verification).

## Explicit context, policy and authorization boundaries

Implemented: namespaces partition reusable answers;
`EmbeddingSpace` identifies comparable vectors. Applications must declare relevant
generation/knowledge/permission revisions in trusted scope configuration.
BYPASS and PRIVATE skip cache reads/writes; READ_ONLY can still reuse an answer.
The embedded package does not authenticate callers; server namespace and role
authorization belongs at its HTTP boundary.

The identities address different invariants. `EmbeddingSpace` establishes vector
comparability through trusted identity and dimensions. Namespace partitions
eligible answers. The persisted key addresses an entry; its `created_at` revision
lets a store reject a replaced candidate. That revision is not a knowledge revision
and does not discover changed generation instructions. A coalescing key addresses
concurrent work and does not partition persisted answers. Applications must rotate
the appropriate answer scope or vector space when trusted context changes.

Equal prompt text or equal vector dimensions do not establish
equivalent context. Explicit identity prevents accidental comparisons across
incompatible spaces while keeping application-specific context outside the cache.

KEEP explicit scopes; maximize reuse in a common namespace;
or let the cache infer context changes from prompts and callables. Shared scopes
reduce configuration work but remove isolation; implicit inference cannot establish
trusted permissions or detect every external change.

More scopes reduce reuse and require deliberate
rotation/migration. A coalescing key does not partition persisted answers. TTL
bounds residence, not factual freshness. The facade rejects mismatched/changed
embedding metadata and requires store revision/expiry confirmation before a hit;
those checks do not authorize a caller or understand arbitrary external facts.
PRIVATE does not prevent a generation provider receiving the prompt or control
application logging. Browser controls are usability, not authorization.

| Embedded policy | Cache read | Cache write | Consequence |
| --- | --- | --- | --- |
| NORMAL | Yes | On generation | Can reuse an existing answer |
| READ_ONLY | Yes | No | Can still reuse an incompatible answer |
| REFRESH | No | Yes | Generated output may replace an entry |
| BYPASS / PRIVATE | No | No | Generation can still receive the request |

The HTTP API expresses these choices through read/write/private flags rather
than these enum members. Policy selection is not an authentication mechanism.

**Illustrative stale-context sequence:** the knowledge revision changes but the
application retains its old namespace. A same-space candidate is live, clears the
threshold and confirms its storage revision. Returning obsolete knowledge can be
conformant cache behavior. Changing only the flight key does not fix persisted
reuse. A restricted HTTP principal also cannot gain another tenant's answers by
selecting its namespace: server authorization must precede query or inspection.
Changing vector identity requires compatible data, not padding old vectors.

Revisit when an application cannot reliably express its changing context;
prefer bypass or application-owned exact/context keys until an evaluated contract
can preserve the required isolation.
Migration needs explicit invalidation, restricted-principal and cross-space cases,
and rollback freshness review. Isolation cannot prove compatibility within a scope.

Evidence: [Identity responsibilities](context-identity-and-migration.md#choose-the-two-identities),
[policy contract](../packages/cache/README.md#contract),
[lookup validation/confirmation](../packages/cache/src/semantix_cache/engine.py),
[isolation tests](../packages/cache/tests/test_engine.py),
and [server namespace resolution](../apps/server/app/security/auth.py).

## Storage selection and persistent ownership

A structural `CacheStore` makes orchestration replaceable without making backends
operationally interchangeable. Search proposes a detached candidate; the facade
owns threshold acceptance; `record_hit` must confirm the expected live revision
before a successful hit. A custom store must preserve that invariant rather than
merely expose similarly named methods.

| Concern | MemoryStore | PgVectorStore | RedisStore |
| --- | --- | --- | --- |
| Search / numbers | Bounded exact float64 cosine in process | Exact SQL cosine winner over eligible float32 vectors; threshold-edge scores can differ | Bounded exact client-side float64 scan; eligible vectors cross the network |
| Authority / retention | Instance lock, monotonic expiry, confirmed-hit LRU | PostgreSQL clock; locked transactional confirmation/write/LRU | Redis server clock; fixed Lua revision/expiry/LRU mutations |
| Setup / ownership | Empty local state and owned numerical workers | Explicit marked schema/migrations; borrows `pool=`, owns pool from `connect()` | Explicit marked binding; borrows `client=`, owns client/pool from `connect()` |
| Accepted cost | Non-durable; entry count is not a byte budget | Database availability, permissions and binding-lock contention | Transfer/script cost; standalone-primary support and operator-owned persistence |

Capacity spans namespaces within a binding; namespace is not an independent
capacity budget. Hits do not slide TTL. Persistent binding revision history
survives deletion/clear, preventing an old candidate from becoming current merely
because its key is reinserted. A cancelled MemoryStore await can leave its
numerical worker running and retaining admission; busy close is an error, not
proof that cancellation stopped computation. MemoryStore operations have no
internal deadline; the facade or caller supplies one.

Explicit initialization separates deployment authority from runtime use.
PgVectorStore has its own marked schema/prefix and checksum-tracked migrations;
ordinary operations run no DDL and do not adopt legacy server cache rows. Redis
validates a marked binding and fails closed on a dirty mutation marker. Its
scripts do not provide SQL rollback semantics. Operators own persistence, backup
and recovery; a Redis endpoint alone is no durability promise. Version, capacity
and connection bounds remain in the owning guides.

**Illustrative race/acknowledgement sequence:** search finds revision R; another
writer replaces it; confirmation of R returns false, preventing a stale hit
increment/return. A later confirmation can execute remotely and lose its reply:
the caller receives an error while the hit counter has advanced. Blind replay
could count again. Writes likewise have uncertain effects after dispatch. In
contrast, the inspected PostgreSQL rejected-write test asserts unchanged entries
and revision state after rollback. These are distinct failure boundaries.

Keeping explicit store choices fits different dependency and retention needs. One mandatory
database simplifies selection but burdens ephemeral consumers. A universal wrapper
or approximate-search replacement still needs backend-specific confirmation and
precision rules. Revisit after measured transfer/lock/search pressure or a new
durability requirement. Migration needs threshold-edge and stale-revision cases,
trusted space/context handling, capacity/expiry validation and recovery planning;
port conformance alone cannot establish workload or availability equivalence.

Evidence: [storage mechanics](embedded-storage.md), [Redis support/recovery](embedded-redis.md),
[conformance limits](cache-store-conformance.md),
[MemoryStore](../packages/cache/src/semantix_cache/memory.py),
[PgVectorStore](../packages/cache/src/semantix_cache/stores/pgvector.py),
[RedisStore](../packages/cache/src/semantix_cache/stores/redis.py),
[revision/worker assertions](../packages/cache/tests/test_memory.py),
[rollback assertions](../packages/cache/tests/test_pgvector.py),
and [lost-acknowledgement assertions](../packages/cache/tests/test_redis_faults.py).

## Similarity reuse without a production answer verifier

Implemented: reuse depends on an eligible similarity score
and authoritative store confirmation. Production LLM answer-compatibility
verification was evaluated and not adopted in the documented exploratory work.
Neither semantic nor exact matching proves factual truth.

Nearby embeddings can represent requests requiring different
answers. Revision, expiry and structural response validation establish cache
behavior, not answer compatibility. Keeping this distinction visible makes
false-hit risk a workload decision rather than an implicit correctness promise.

**Illustrative false-hit sequence:** retrieval proposes an answer about checking
whether a file exists for a request requiring safe exclusive file creation.
Threshold and revision checks can pass without validating the required operation's
semantics. Raising the threshold may reject this candidate and useful paraphrases
together. A miss regenerates an answer; the new answer is not thereby proven true.
The application owns the consequences and any necessary domain verification.

KEEP conservative semantic reuse where evidence supports it;
use application-owned canonical exact matching with relevant context; bypass
reuse; or evaluate an answer verifier. A verifier adds data transfer, latency,
cost and acceptance errors, and can assess only retrieved candidates.
Exact/context matching sacrifices paraphrase recall and still requires invalidation.
Bypass pays generation cost and retains generator risks. Semantic reuse earns its
extra acceptance risk only through workload evidence of useful correct reuse;
raw hit rate alone is an insufficient comparison objective.

The frozen exploratory comparison covered
11 requests and four cached answers. Guarded retrieval recovered no additional
correct reuse over exact caching; compatible paraphrases missed retrieval before
verification. Reference decisions were AI-assisted, human adjudication was
incomplete, and this was not a representative production sample. Those results
explain non-adoption in that experiment, not universal verifier ineffectiveness.
A high score or threshold of 1 is not an exact-text or correctness certificate.

Revisit when fresh representative, independently reviewed evidence shows
useful correct reuse and acceptable incorrect reuse, including retrieval misses,
uncertain labels, latency, privacy and cost. Do not relabel a consumed exploratory
split as untouched confirmation.

Evidence: [Recorded findings and limits](semantic-accuracy-limitations.md),
[implemented threshold/ordering](../packages/cache/src/semantix_cache/_semantics.py),
and [separate static benchmark limits](../packages/cache/benchmarks/reuse_quality/README.md#interpretation-limits).
The exploratory summary does not claim public access to its underlying run.
A changed retriever/verifier would require new candidate-selection and failure
tests, an explicit provider/data boundary and fresh validation; separate static
benchmark results do not supply the missing confirmation for this study.

## Human-controlled thresholds and isolated evaluation

Implemented: the server's live threshold is global and
requires a wildcard/global Admin to change. Preview does not apply it. Evaluation
creates fresh bounded memory state and never seeds the live cache; alternate
thresholds reclassify one measured candidate set without additional provider calls.
A hit-rate optimizer could reward wrong reuse or silently change another
namespace's behavior, so automatic tuning would need an explicit quality objective
and scope contract beyond this control.
These server controls do not add automatic tuning to the embedded facade.

Hit rate alone can reward wrong reuse. Isolation lets operators
inspect quality/latency trade-offs without changing interactive entries. Frozen
projections make comparisons cheaper than rerunning every threshold.

KEEP applying thresholds explicitly after review; automatically tune from
hit rate; replay real ordered runs at each threshold; or evaluate against the live
cache. Reruns provide new candidate evolution but cost provider work and require
controlled conditions. Live-cache evaluation couples experiments to user state.

Projection candidates do not evolve with the
alternate threshold. Even the row labelled measured uses score reclassification
and need not equal actual confirmed-hit aggregates. Execution serialization is
instance-local; its cooperative timeout includes lock waiting/execution, not all
source-resolution or history work, and cancellation does not prove remote work
stopped. Optional history retains terminal aggregates, not per-query answers;
retention failure can coexist with a successful measured result. Estimates are
not provider billing or guarantees of future savings.

**Illustrative projection sequence, following an inspected deterministic
counterexample:** start empty at threshold 0.95. A misses and is stored. B scores
0.93 against A, misses and is stored. C scores 0.96 against B and hits. A frozen
projection at 0.90 marks B and C as hits. In an ordered replay at 0.90, B hits A
and is never stored; C's score against A is only 0.80, so C misses. Two projected
hits become one replay hit. These scores are illustrative test inputs, not model
quality or measured savings. Live entries, concurrent writes, TTL or another
store's precision can introduce further differences at the same nominal threshold.

History persistence is a separate outcome, not an atomic part of measured
execution. Changing this boundary would require replay/cancellation/history
failure cases, quality-labelled datasets, schema/decoder compatibility and an
explicit migration for global threshold scope and retained evidence.

Revisit when representative replay evidence shows projections mislead the
intended decisions, or users require different threshold scope. Evaluate public
contracts, authorization and reproducibility before changing either boundary.

Evidence: [Threshold permissions](../apps/server/app/cache/api/router.py),
[isolated executor](../apps/server/app/benchmark/application/run_executor.py),
[projection formula](../apps/server/app/benchmark/domain/metrics.py),
[projection/replay counterexample](../apps/server/tests/benchmark/domain/test_metrics.py),
[isolation tests](../apps/server/tests/benchmark/application/test_service.py),
[benchmark interpretation](guides/benchmarking.md#metric-interpretation),
and [history limits](guides/evaluation-history.md#what-becomes-durable).

## Shared replica authorities with local execution

A second backend exposes which state represents a deployment promise. Splitting
rate buckets or session lockouts lets alternating clients evade the intended
shared budget; splitting a mutable global threshold produces replica-dependent
decisions. Hardened Compose therefore shares PostgreSQL authority for rate
buckets, progressive session lockouts and the global threshold, alongside
pgvector entries and enabled persistent evaluation data. The lifespan borrows
its runtime pool for those features.

Coalescing, runtime counters, provider connections and the evaluation execution
lock remain local. Settings also load per process: replicas need compatible
address/quota, authentication, embedding and cache configuration. A shared
database does not repair configuration drift. Shared cache statistics and local
request metrics have different populations even when returned together. The
supported topology is one gateway, two backends and one PostgreSQL/pgvector
service, with external TLS termination. Historical pre-remediation audit rows
are not current implementation.

**Illustrative threshold/outage sequence:** Admin writes the shared threshold
through A; B consults that authority for subsequent lookups instead of its startup
value. PostgreSQL then becomes unavailable. Shared coordination raises rather
than switching to independent local counters or stale threshold state. The cost
is availability while preserving the defined authority. This does not change an
already-running decision retroactively, make provider work transactional or give
the database HA. Readiness covers selected dependencies and the responding
replica, not hosted-provider capacity or every optional repository.

KEEP selected shared state reuses the deployed database without making all
process activity durable. One authoritative gateway for admission is a plausible
alternative with different ownership and failure concentration. A separate
coordinator might address measured contention or cross-replica sharing, but adds
a service, recovery semantics and monitoring. A replicated dict is not a
consistency protocol; distributed coalescing remains absent.

Operations records describe bounded mock-provider verification, drain/failover
procedures and residual failures. They do not establish arbitrary replica counts,
HA PostgreSQL, multi-region operation or hosted-provider quotas. Revisit for
measured contention, duplicate provider cost or a new availability requirement.
Migration needs shared identity/configuration rules, outage/partition and mixed
rollout tests, schema/runtime-role planning, drain ownership and capacity evidence
for the new topology.

Evidence: [coordination transactions](../apps/server/app/infrastructure/coordination.py),
[admission authority](../apps/server/app/middleware/rate_limit.py),
[threshold reads](../apps/server/app/cache/application/service.py),
[shared/outage assertions](../apps/server/tests/security/test_shared_coordination.py),
[two-replica verification](operations/multi-replica-readiness.md#two-replica-verification),
[deployment/drain contract](operations/deployment.md#two-replica-operation),
and [audit limits](operations/production-runtime-audit.md#limits-and-no-action-observations).

## Observability, accounting and evidence provenance

Truthful observations require naming the event population. A caller can miss
without invoking generation itself; a provider attempt can fail before producing
text; successful generation can precede a failed write. Reconstructing billing
or rollback from one result flag discards those distinctions.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Query `cache_hit` / match fields | This resolution's confirmed cache decision | Answer correctness or one lookup per HTTP caller |
| Successful server `provider_called` | Whether this caller led generated work | Failed attempts, embedding dispatches or billed requests |
| Runtime `provider_calls` | Generation attempts recorded before awaiting outcome, including failures | Successful answers, wire retries or invoices |
| Runtime hit/miss counters / follower gauge | Shared lookup events / currently waiting followers | A partition of caller starts or causal savings |
| Embedded follower hits / generation-start count | Confirmed follower outcomes / generator starts | Counterfactual token or dollar savings |
| Browser Monitor traces | Bounded local records of successful non-private submissions | Durable server history or complete fleet traffic |
| Evaluation projections / estimates | Reclassification and assumptions for retained candidates | Observed alternate runs or provider billing |

**Illustrative shared-miss sequence:** two server callers join one task. Starts
count both callers; shared lookup records one miss; generation records one
attempt. Both successful responses can report misses, while only the leader
reports `provider_called=true`. Cancelling a caller records a failed caller
completion without cancelling the shielded task. A later provider failure leaves
an attempted-generation count without a successful response flag. Misses,
callers, attempts and completions therefore cannot be equated.

Runtime counters belong to one collector lifetime and reset on restart. Average
latency uses recorded completions, including failures; p95 uses a bounded recent
sample. Supplied cache size is observed separately from the metrics lock.
Aggregating replica percentiles or mixing shared cache counts with local requests
requires an external measurement design. Embedded generation-start evidence can
overlap later failure/cancellation; terminal follower outcomes are separate
categories. An admitted leader can recheck into a hit without generation.

PRIVATE omits Monitor trace insertion, but current form/query/result state can
still exist in browser memory. The chosen generator may receive the prompt.
Safe aggregate diagnostics do not certify application logs, exports or third-party
retention. Query traces are not receipt attestations; provider-verification
receipts themselves are bounded contributor statements, not cryptographic proof
of execution or universal model compatibility.

KEEP scoped instrumentation exposes defined behavior without storing private
content in aggregate telemetry. Inferring savings from misses is cheap but
misleading; provider-side dispatch/billing correlation adds data and privacy
obligations. Revisit for a specific reconciliation or fleet-monitoring requirement.
Migration needs event ownership, failure/cancellation pairing, reset/window and
retention definitions, plus privacy/multi-replica tests before presenting new
derived quantities as measured.

Evidence: [query accounting](../apps/server/app/query/application/service.py),
[runtime collector](../apps/server/app/observability/metrics.py),
[counter assertions](../apps/server/tests/observability/test_metrics.py),
[embedded reconciliation](embedded-observability.md#fields-and-reconciliation),
[Monitor ownership](../apps/web/src/features/monitor/context/MonitorContext.tsx),
[private-trace assertions](../apps/web/tests/features/monitor/query-workflow.test.tsx),
and [provider receipt limits](provider-live-verification.md#bounds-and-receipt-interpretation).

## Detailed contracts kept in their owning guides

Use [storage setup/lifetimes](embedded-storage.md#connections-cancellation-and-failures),
[provider configuration/ownership](embedded-providers.md#configuration-and-ownership),
and [conformance](cache-store-conformance.md) for implementation procedures.
This reference explains cross-component costs; those guides remain the maintained
authorities for adapter details, limits and recovery commands. Passing conformance
does not certify a deployment.

## Classify limits before drawing conclusions

- **Implemented capability:** present in reviewed executable source; test pointers
  here identify inspected assertions, not a newly passing run.
- **Documented experiment:** a recorded result with its workload and evidence
  boundary, not general author intent or representative production evidence.
- **Hypothetical alternative:** a comparison, not a historically rejected proposal.
- **Design trade-off:** a bounded choice, such as local coalescing.
- **Known technical limitation:** a supported boundary, such as frozen-candidate
  projections; it need not be an implementation defect.
- **Source-only possible defect — NOT REPRODUCED:** a conditional code observation
  still needs runtime reproduction before being called a known failure.
- **Unverified claim/environment:** an unrun test, unknown third-party behavior or
  missing production evidence; absence of a finding proves neither safety nor failure.
- **Unsupported / not implemented:** an absent feature, such as distributed
  exactly-once generation or production answer verification, not a broken feature.
