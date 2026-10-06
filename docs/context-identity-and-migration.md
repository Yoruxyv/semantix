# Context identity and cache migration

A cached answer is reusable only within the application's intended context.
Identical prompt text can require different answers when the generation model,
knowledge, tenant, language or output contract changes. Semantix does not infer
these inputs from prompts, closures or ContextVars.

**Namespace is cache partitioning, not authorization.** Authenticate and authorize
access in your application before selecting a scope or returning cached data.
Use synthetic or opaque aliases in scope names; never put credentials in them.

## Choose the two identities

| Public concept | What the application must define |
| --- | --- |
| `namespace` | Which completed answers may be reused together: application/tenant, generation revision, knowledge/index/retrieval revision, permissions or approval epoch, locale and output contract as relevant |
| `EmbeddingSpace(identity=..., dimensions=...)` | Which vectors can be compared: model and exact revision, tokenizer, pooling, preprocessing/normalizer and dimension configuration |

Scope names are application-defined. There is no universal naming convention.
Namespaces contain 1–64 ASCII characters matching
`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`. Use trusted, unambiguous short configuration
aliases; do not truncate names, join arbitrary user-supplied strings or assume
this regex authenticates a tenant. The same prompt in separate namespaces has
separate canonical keys. Search, confirmation, delete and clear are scoped.
Capacity/LRU can still be shared across namespaces within a store.

An embedder and store must declare exactly the same `EmbeddingSpace` at cache
construction and throughout operations. Equal dimensions alone do not prove
compatibility. Wrong vector dimensions raise `EmbeddingError` at the facade;
invalid direct store queries raise `CacheValidationError`, and invalid writes
raise `CacheStoreError`. A changed binding raises `EmbeddingSpaceError`.

MemoryStore binds one space. Use a separate matching store/cache for a new space;
PgVectorStore can use separate bound instances over shared tables and filters by
identity and dimension. A `CacheEntry` has no space tag: custom stores and direct
`put` callers must preserve the declared space. Keys alone do not identify a
space or prove vector compatibility. See the [store contract](embedded-storage.md#custom-database-or-vector-service).

## Run the offline recipes

The [complete example](../packages/cache/examples/context_identity.py) reuses the
[public custom-embedding wrapper](../packages/cache/examples/custom_integration.py)
and imports only public cache types. From `packages/cache/`, with the existing
local development environment:

~~~text
uv run --no-sync --offline python -m examples.context_identity
uv run --no-sync --offline pytest tests/test_context_identity_example.py
~~~

No provider, credentials, database or model download is needed. The synthetic
two-dimensional vectors demonstrate isolation, not semantic quality. Every scope
in `partitioned_resolve()` uses the same question and vector, so separation depends
on the explicit identity.

## Generation model and version

`partitioned_resolve()` constructs these example namespaces:

~~~text
support:demo-a:g1:kb1:en:text1
support:demo-a:g2:kb1:en:text1
~~~

Here `g1` and `g2` are aliases for two application-selected generation-model
revisions, including configuration that changes the required answer. Both use
the same embedder. Their first resolves generate independently; each repeated
resolve confirms its own cached answer. Changing the generation model does not
by itself require a new embedding space when the embedding pipeline is unchanged.
Version the namespace whenever old answers are incompatible with the new model,
system instructions, tools, approval or permissions policy. Semantix will not
notice a changed callable's internal state.

## Tenant and application

The example's `support_namespace()` joins trusted configuration aliases after
application authorization. Changing `demo-a` to `demo-b` creates a separate scope
for the same prompt. `support` is an application alias; use a different scope for
another application whose answers are incompatible.

These are synthetic identifiers, not personal tenant data. In an actual service,
map the authenticated principal to an authorized internal tenant alias yourself.
Never let a caller select another tenant's namespace unchecked. A namespace does
not authenticate the principal, enforce permission checks or encrypt responses.
When authorization context affects the answer, also partition by an appropriate
permission/policy revision and retire old scopes according to your retention policy.

## Knowledge, index and retrieval revision

The example changes `kb1` to `kb2` and verifies an independent miss and confirmed
hit. These aliases represent the full answer-producing knowledge configuration:
document-set/corpus revision, index revision and retrieval-policy revision. Rotate
the alias when any incompatible part changes. A prompt about the same topic can
need a new answer after an index or document update.

The generator remains your own RAG/application workflow. Semantix supplies no
retriever or RAG engine and does not hash retrieved documents automatically. Freeze
the relevant generation context for the request and select its matching scope.

## Locale and output contract

The example independently changes `en` to `id` and `text1` to `json1`. The locale
branch returns Indonesian demonstration text; the format branch returns a JSON
object with an `answer` field. Each has its own cached output.

Put language, JSON schema version, output format or a materially different style
in scope when returning the old text would violate the caller's contract. Cosmetic
presentation applied after retrieval may not need a new scope if the stored answer
remains interchangeable. The application makes this decision; Semantix does not
detect locale, translate answers or validate an application's JSON schema.

## Embedding revision and preprocessing

`embedding_revision_and_migration()` keeps the logical model `demo-model` and two
dimensions, but changes raw preprocessing to lowercase:

~~~python
old_space = EmbeddingSpace(identity="demo-model:r1:raw:d2", dimensions=2)
new_space = EmbeddingSpace(identity="demo-model:r1:lower:d2", dimensions=2)
~~~

`Weather today` produces different toy vectors under these pipelines. Binding the
new embedder to the old store raises `EmbeddingSpaceError`; a new matching store
starts empty. Keep identity stable for an unchanged pipeline and change it for
incompatible model/tokenizer/revision, pooling or preprocessing changes, including
an optional `prompt_normalizer`. Do not change a live object's metadata to reuse
old entries. A similarly named model, equal dimensions or successful construction
cannot prove that vectors were produced by the declared pipeline.

Canonical prompt handling always replaces control characters with spaces,
collapses horizontal whitespace and trims. Generation sees that canonical text.
An optional prompt normalizer affects embedding text only. Neither operation adds
application context. The engine normalizes valid vectors for cosine comparison;
these recipes do not change runtime defaults.

## Your generation callable and custom integrations

Pass your existing async callable accepting canonical prompt text and returning
completed, application-approved text:

~~~python
result = await cache.resolve(
    prompt=question,
    namespace=namespace,
    generate=my_existing_generation_callable,
)
~~~

Under the default `NORMAL` policy, a confirmed hit skips generation. A miss calls
generation and writes validated completed text before returning a successful
`CacheResult`. A lookup error propagates instead of generating through the failure.
Generation exceptions propagate unchanged; invalid completed output is not cached.
`READ_ONLY`, `REFRESH`, `BYPASS` and `PRIVATE` have distinct read/write behavior;
see the [policy table](../packages/cache/README.md#contract).

The example uses `CustomEmbedding` with explicit metadata and an async embedding
callable. A bare embedding function needs this metadata wrapper. No subclass,
provider registry or maintained generation adapter is required. Replace the toy
callable with your application integration without importing private cache helpers.
For an independent structural `CacheStore`, use the existing
[company-store example](../packages/cache/examples/custom_store.py) and
[conformance requirements](embedded-storage.md#custom-database-or-vector-service).
Expected integration failures should use safe typed cache errors.

The facade borrows the embedder, store and generator and closes only itself.
The example separately enters/exits MemoryStore to close its owned state/workers.
Applications own provider clients and other resources; drain/cancel active work
before closing them. Preserve finite deadlines and propagate cancellation in
custom integrations. See [ownership](../packages/cache/README.md#extension-and-ownership).

Optional `coalescing_key` attests to compatible concurrent generation inputs;
changing it alone does not partition persisted answers. These sequential recipes
leave coalescing disabled. Read the existing
[coalescing rules](../packages/cache/README.md#optional-cold-miss-coalescing) before
using it with model, tenant or knowledge context.

## Low-level get and set

`get(prompt, namespace=...)` performs semantic lookup, threshold filtering and
atomic confirmation; it is not an exact-key fetch. `set(prompt, response, ...)`
re-embeds the prompt, validates completed text and returns the canonical key only
after a successful write. It does not generate, moderate or approve the answer.
Use it after your own streaming/tool/RAG workflow has approved the final text.
`delete(key, namespace=...)` takes the returned key, not the prompt. `clear` affects
only the specified namespace in the bound space.

A candidate must pass inclusive threshold eligibility and atomic confirmation of
its `created_at` revision and expiry before becoming a hit. Replacement invalidates
old candidates, including across delete/clear and reinsert. Failed confirmation
means a miss. The store's clock is authoritative: MemoryStore uses monotonic expiry;
UTC `expires_at` is metadata. Do not confirm solely from a previously fetched
snapshot or client wall-clock timestamp. Hits do not extend retention.

## Migration from another semantic cache

**Fresh re-embedding is the safe default unless compatibility is proven.** The
executable migration recipe exports approved synthetic prompt/response text,
imports with `new_cache.set`, then checks `get`, `delete` and `clear` in the new
space. The old bound store stays independent. This is a small integration recipe,
not a database migration engine or a production migration validation run.

1. Inventory the old cache's model/revision, preprocessing, metric, threshold,
   tenant/session/context scope, metadata, retention and invalidation behavior.
2. Define Semantix namespaces and embedding-space identities from your application's
   equivalence rules. Sessions only belong together when their answers are reusable.
3. If attempting vector reuse, prove exact pipeline, coordinate, dimension,
   normalization and metric compatibility on representative inputs. A model name or
   dimension match is insufficient. `set` always embeds; direct store imports must
   implement the public store contract and truthful space metadata.
4. Otherwise export approved source prompts/responses and re-embed through `set`.
   Revalidate that each answer still satisfies its new context. Skip expired data;
   choose an explicit remaining retention budget capped by the target store default.
   The demo's 60-second budget is synthetic, not preservation of a foreign expiry.
5. Recalibrate similarity thresholds on representative domain calibration data for
   the chosen embedder/store; evaluate held-out cases separately. Neither an old
   threshold nor the inclusive default `0.92` (or `1.0`) establishes safe reuse.
6. Shadow authorized representative reads in an isolated target scope before
   cutover; inspect wrong reuse counts, false acceptance rates, missed reuse and
   required output contracts. Keep development tuning separate from held-out evaluation.
7. Compare expected reuse/non-reuse behavior and errors, then cut over only when
   domain evidence is acceptable. Retain an export, rollback route and retention
   policy for the old cache.

Foreign internal IDs, namespaces, sessions, metadata, TTLs, hit counters and
revision state do not automatically map to Semantix. Let `set` create canonical
keys/new revisions; do not pretend foreign hit counts or timestamps are Semantix
confirmation evidence. Persistent schema provisioning is a separate explicit step:
see [storage initialization](embedded-storage.md#new-postgresql-database).

## Generation succeeds but persistence fails

Generation may already have called a provider, performed a tool action or charged
money when the subsequent store write fails. `resolve` raises the persistence
failure; it does not return a successful resolution or silently replay generation.
The cache cannot roll back those external effects. There is no transaction spanning
generation and cache persistence. An interrupted/failed write may also have an
uncertain commit outcome in an external store; do not assume a safe automatic retry.

Catch the typed failure at your application's boundary, surface an appropriate
error, and use your own idempotency/recovery policy before attempting the workflow
again. Lookup failures likewise raise. Do not suppress errors to fabricate hit or
write evidence. If you need to retain an approved answer separately for recovery,
your application can own generation and subsequent `set`, handling persistence
failure explicitly; this changes who holds the answer, not transactional guarantees.

## Executable contract evidence

The [recipe tests](../packages/cache/tests/test_context_identity_example.py) execute
both offline recipes and inject a public `put` failure after successful generation,
asserting one completed generation effect and no replay. Existing regression tests
already cover the required negative isolation cases:

| Assertion | Existing test |
| --- | --- |
| Namespace A cannot hit B; incompatible identities cannot bind/reuse | `test_engine.py::test_namespaces_spaces_and_changed_metadata` |
| Wrong vector dimensions are rejected before store work | `test_engine.py::test_bad_embedding` |
| Stale revision cannot confirm, including after clear/reinsert | `test_store_conformance.py::TestBuiltInStores::test_revision_and_detached_candidate` |
| Expired candidate cannot confirm; hits do not extend TTL | `test_store_conformance.py::TestBuiltInStores::test_expiry_retention_cap_and_non_sliding_hit` |
| MemoryStore expiry is exact and authoritative | `test_memory.py::test_ttl_exact_boundary_cap_and_overwrite` |

See [engine tests](../packages/cache/tests/test_engine.py),
[shared store tests](../packages/cache/tests/test_store_conformance.py) and
[MemoryStore tests](../packages/cache/tests/test_memory.py). Run those files alongside
the recipe tests with `uv run --no-sync --offline pytest`. PostgreSQL variants
require an explicitly disposable test database and otherwise skip; the core
recipes and MemoryStore/company-store checks remain offline.
