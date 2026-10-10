# Engineering decisions, trade-offs and limits

This is a present-day explanation of the implementation reviewed at
[`b35246a`](https://github.com/Yoruxyv/semantix/commit/b35246aa446f615be2b7cef90c7fc4f4a722d9e6).
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
security or production certification.

## An embedded core with optional HTTP products

**Decision / status.** Implemented: `semantix-cache` can run without the server.
Embedding and storage use structural ports; generation is an application-owned
async callable. The optional server delegates authoritative entries, revisions,
TTL and LRU to the package stores and shares semantic ordering helpers, while
owning HTTP orchestration, authorization and telemetry. `semantix-client` is a
separate HTTP client, not another cache engine.

**Context / fit.** Applications can reuse their generation flow without adopting
FastAPI or a workbench. A shared store implementation keeps entry semantics in
one owner without making embedded callers adopt server administration contracts.

**Alternatives.** KEEP these boundaries; require the entire server for every
consumer; or make the facade own provider selection and generation workflows.
Bundling would centralize setup but couple lightweight consumers to more policy
and dependencies.

**Trade-offs / failure behavior.** Applications own credentials, context and
resource lifetimes. The facade closes itself, not borrowed dependencies. Server
and embedded orchestration/results still differ and need compatibility review.
Generation followed by a failed cache write raises instead of returning a
successful resolution; external generation effects cannot be rolled back.
There is no transaction across provider work and persistence or safe automatic
replay guarantee after an uncertain remote write.

**Revisit when.** Repeated consumer integration failures demonstrate a missing
shared contract, or a public API change needs a coordinated compatibility plan.
Similar-looking orchestration alone is insufficient evidence to merge owners.

**Pointers.** [Public extension/ownership contract](../packages/cache/README.md#extension-and-ownership),
[server path dependency](../apps/server/pyproject.toml),
[store delegation](../apps/server/app/cache/infrastructure/backends/official.py),
[backend/package parity tests](../apps/server/tests/cache/infrastructure/backends/test_platform_parity.py),
and [generation/write failure boundary](context-identity-and-migration.md#generation-succeeds-but-persistence-fails).

## Local coalescing with distinct caller contracts

**Decision / status.** Implemented: in-flight sharing is local to an instance and
event loop, not a distributed exactly-once provider-call guarantee. Embedded
coalescing is opt-in for eligible NORMAL cold misses with an explicit context
key. Server `QueryService` chooses its own namespace/prompt/effective-policy key,
including for bypass work; it does not use the embedded facade's admission rules.

**Context / fit.** Concurrent equivalent misses can repeat generation. Local
sharing avoids a distributed ownership/lease protocol and keeps ordinary
embedded hits outside the registry.

**Alternatives.** KEEP local sharing; leave embedded coalescing disabled for
independent samples or side effects; or introduce distributed coordination.
The latter requires explicit lease expiry, ownership and failure-recovery rules,
not just a shared cache database.

**Trade-offs / failure behavior.** Embedded callers still embed separately.
Followers await the leader, then acquire their own confirmed hit; expiry or
replacement can require their own generation. Admission overflow falls back to
independent work. Follower cancellation affects that follower; leader
cancellation fails the flight, with no promotion or detached generation task.

The server instead shields its shared task from caller cancellation, so work can
continue after an awaiting caller leaves. A server follower receiving generated
text can report `cache_hit=false` and `provider_called=false`: following work is
not a cache hit. Sharing failures does not make provider or write effects atomic.
Separate replicas can still generate the same cold answer.

**Revisit when.** Measured cross-replica duplicate work or required side-effect
semantics justify the extra coordination, with a defined failure and ownership
contract. Reduced call counts alone do not establish latency or correctness gains.

**Pointers.** [Embedded eligibility and cancellation](../packages/cache/README.md#optional-cold-miss-coalescing),
[embedded implementation](../packages/cache/src/semantix_cache/engine.py),
[embedded cancellation tests](../packages/cache/tests/test_coalescing.py),
[server coalescer](../apps/server/app/query/application/coalescing.py),
[server accounting tests](../apps/server/tests/query/application/test_service.py),
and [two-replica evidence](operations/multi-replica-readiness.md#two-replica-verification).

## Explicit context, policy and authorization boundaries

**Decision / status.** Implemented: namespaces partition reusable answers;
`EmbeddingSpace` identifies comparable vectors. Applications declare relevant
generation/knowledge/permission revisions in trusted scope configuration.
BYPASS and PRIVATE skip cache reads/writes; READ_ONLY can still reuse an answer.
The embedded package does not authenticate callers; server namespace and role
authorization belongs at its HTTP boundary.

**Context / fit.** Equal prompt text or equal vector dimensions do not establish
equivalent context. Explicit identity prevents accidental comparisons across
incompatible spaces while keeping application-specific context outside the cache.

**Alternatives.** KEEP explicit scopes; maximize reuse in a common namespace;
or let the cache infer context changes from prompts and callables. Shared scopes
reduce configuration work but remove isolation; implicit inference cannot establish
trusted permissions or detect every external change.

**Trade-offs / failure behavior.** More scopes reduce reuse and require deliberate
rotation/migration. A coalescing key does not partition persisted answers. TTL
bounds residence, not factual freshness. The facade rejects mismatched/changed
embedding metadata and requires store revision/expiry confirmation before a hit;
those checks do not authorize a caller or understand arbitrary external facts.
PRIVATE does not prevent a generation provider receiving the prompt or control
application logging. Browser controls are usability, not authorization.

**Revisit when.** An application cannot reliably express its changing context;
prefer bypass or application-owned exact/context keys until an evaluated contract
can preserve the required isolation.

**Pointers.** [Identity responsibilities](context-identity-and-migration.md#choose-the-two-identities),
[policy contract](../packages/cache/README.md#contract),
[lookup validation/confirmation](../packages/cache/src/semantix_cache/engine.py),
[isolation tests](../packages/cache/tests/test_engine.py),
and [server namespace resolution](../apps/server/app/security/auth.py).

## Similarity reuse without a production answer verifier

**Decision / status.** Implemented: reuse depends on an eligible similarity score
and authoritative store confirmation. Production LLM answer-compatibility
verification was evaluated and not adopted in the documented exploratory work.
Neither semantic nor exact matching proves factual truth.

**Context / fit.** Nearby embeddings can represent requests requiring different
answers. Revision, expiry and structural response validation establish cache
behavior, not answer compatibility. Keeping this distinction visible makes
false-hit risk a workload decision rather than an implicit correctness promise.

**Alternatives.** KEEP conservative semantic reuse where evidence supports it;
use application-owned canonical exact matching with relevant context; bypass
reuse; or evaluate an answer verifier. A verifier adds data transfer, latency,
cost and acceptance errors, and can assess only retrieved candidates.

**Trade-offs / failure behavior.** The frozen exploratory comparison covered
11 requests and four cached answers. Guarded retrieval recovered no additional
correct reuse over exact caching; compatible paraphrases missed retrieval before
verification. Reference decisions were AI-assisted, human adjudication was
incomplete, and this was not a representative production sample. Those results
explain non-adoption in that experiment, not universal verifier ineffectiveness.
A high score or threshold of 1 is not an exact-text or correctness certificate.

**Revisit when.** Fresh representative, independently reviewed evidence shows
useful correct reuse and acceptable incorrect reuse, including retrieval misses,
uncertain labels, latency, privacy and cost. Do not relabel a consumed exploratory
split as untouched confirmation.

**Pointers.** [Recorded findings and limits](semantic-accuracy-limitations.md),
[implemented threshold/ordering](../packages/cache/src/semantix_cache/_semantics.py),
and [separate static benchmark limits](../packages/cache/benchmarks/reuse_quality/README.md#interpretation-limits).
The exploratory summary does not claim public access to its underlying run.

## Human-controlled thresholds and isolated evaluation

**Decision / status.** Implemented: the server's live threshold is global and
requires a wildcard/global Admin to change. Preview does not apply it. Evaluation
creates fresh bounded memory state and never seeds the live cache; alternate
thresholds reclassify one measured candidate set without additional provider calls.
These server controls do not add automatic tuning to the embedded facade.

**Context / fit.** Hit rate alone can reward wrong reuse. Isolation lets operators
inspect quality/latency trade-offs without changing interactive entries. Frozen
projections make comparisons cheaper than rerunning every threshold.

**Alternatives.** KEEP applying thresholds explicitly after review; automatically tune from
hit rate; replay real ordered runs at each threshold; or evaluate against the live
cache. Reruns provide new candidate evolution but cost provider work and require
controlled conditions. Live-cache evaluation couples experiments to user state.

**Trade-offs / failure behavior.** Projection candidates do not evolve with the
alternate threshold. Even the row labelled measured uses score reclassification
and need not equal actual confirmed-hit aggregates. Execution serialization is
instance-local; its cooperative timeout includes lock waiting/execution, not all
source-resolution or history work, and cancellation does not prove remote work
stopped. Optional history retains terminal aggregates, not per-query answers;
retention failure can coexist with a successful measured result. Estimates are
not provider billing or guarantees of future savings.

**Revisit when.** Representative replay evidence shows projections mislead the
intended decisions, or users require different threshold scope. Evaluate public
contracts, authorization and reproducibility before changing either boundary.

**Pointers.** [Threshold permissions](../apps/server/app/cache/api/router.py),
[isolated executor](../apps/server/app/benchmark/application/run_executor.py),
[projection formula](../apps/server/app/benchmark/domain/metrics.py),
[isolation tests](../apps/server/tests/benchmark/application/test_service.py),
[benchmark interpretation](guides/benchmarking.md#metric-interpretation),
and [history limits](guides/evaluation-history.md#what-becomes-durable).

## Detailed contracts kept in their owning guides

- [Storage](embedded-storage.md), [Redis](embedded-redis.md) and
  [conformance](cache-store-conformance.md): one structural port does not make
  backend precision, TTL clocks, transaction, search or durability guarantees
  identical. A passing conformance suite does not certify a deployment.
- [Setup/ownership](embedded-storage.md#connections-cancellation-and-failures) and
  [providers](embedded-providers.md#configuration-and-ownership): explicit setup,
  borrowed resources, deadlines and uncertain remote outcomes stay backend-specific.
- [Two-replica operation](operations/deployment.md#two-replica-operation) and
  [audit limits](operations/production-runtime-audit.md#limits-and-no-action-observations):
  shared PostgreSQL controls coexist with local coalescing and metrics. Historical
  pre-remediation findings are not current architecture; supported Compose evidence
  does not establish HA PostgreSQL, multi-region behavior or hosted-provider capacity.
- [Numeric observations](embedded-observability.md#fields-and-reconciliation):
  follower hits are observations, not causal provider-call, token or dollar savings.
  Instance snapshots do not create fleet telemetry.

## Classify limits before drawing conclusions

- **Design trade-off:** a bounded choice, such as local coalescing.
- **Known technical limitation:** a supported boundary, such as frozen-candidate
  projections; it need not be an implementation defect.
- **Source-only possible defect — NOT REPRODUCED:** a conditional code observation
  still needs runtime reproduction before being called a known failure.
- **Unverified claim/environment:** an unrun test, unknown third-party behavior or
  missing production evidence; absence of a finding proves neither safety nor failure.
- **Unsupported / not implemented:** an absent feature, such as distributed
  exactly-once generation or production answer verification, not a broken feature.
