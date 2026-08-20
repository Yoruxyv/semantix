# API

FastAPI serves interactive documentation at <http://localhost:8000/docs>.
Application errors use a stable object containing `error` and `detail`.

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/query` | Submit a query |
| `GET` | `/api/v1/cache/stats` | Read global or namespace cache statistics |
| `GET` | `/api/v1/cache/threshold` | Read the active similarity threshold |
| `PUT` | `/api/v1/cache/threshold` | Update the active threshold |
| `GET` | `/api/v1/cache/entries` | Search, sort, and paginate safe cache metadata |
| `GET` | `/api/v1/cache/entries/{cache_key}` | Read one authorized cache entry with its complete response |
| `DELETE` | `/api/v1/cache/entries/{cache_key}` | Delete one entry |
| `DELETE` | `/api/v1/cache` | Clear all entries or one namespace |
| `GET` | `/api/v1/benchmarks/datasets` | List controlled benchmark datasets |
| `POST` | `/api/v1/benchmarks/run` | Run an isolated benchmark |
| `GET` | `/api/v1/evaluations/datasets` | List built-in evaluation datasets |
| `POST` | `/api/v1/evaluations/datasets/validate` | Validate and preview a session-local JSON dataset |
| `GET` | `/api/v1/evaluations/datasets/persisted` | List namespace-authorized persisted datasets |
| `POST` | `/api/v1/evaluations/datasets/persisted` | Persist one validated schema v1 dataset |
| `GET` | `/api/v1/evaluations/datasets/persisted/{dataset_id}` | Read persisted metadata and ordered cases |
| `DELETE` | `/api/v1/evaluations/datasets/persisted/{dataset_id}` | Delete one persisted dataset and its cases |
| `POST` | `/api/v1/evaluations/runs` | Run a built-in, inline, or persisted evaluation dataset |
| `GET` | `/api/v1/evaluations/runs` | List authorized retained aggregate evaluation history |
| `GET` | `/api/v1/evaluations/runs/{run_id}` | Read one authorized retained aggregate run |
| `DELETE` | `/api/v1/evaluations/runs/{run_id}` | Delete one retained run from a concrete namespace |
| `POST` | `/api/v1/evaluations/runs/compare` | Compare exactly two retained runs with server-backed compatibility checks |
| `GET` | `/api/v1/metrics` | Read process-local aggregate metrics (global admin only) |
| `GET` | `/health` | Read application and provider-type health |

The frontend exposes the evaluation laboratory at canonical route
`/evaluations`; `/benchmarks` is a replace-redirect kept for compatibility.
Canonical backend contracts use `/api/v1/evaluations/*`. The existing
`/api/v1/benchmarks/*` built-in contracts remain available for compatibility.

## Query request

```json
{
  "prompt": "Explain semantic caching",
  "namespace": "default",
  "cache_enabled": true,
  "cache_read_enabled": true,
  "cache_write_enabled": true,
  "private": false
}
```

Only `prompt` is required. `cache_enabled=false` overrides both granular flags.
`private=true` also disables reads and writes. Disabling reads while keeping
writes enabled refreshes the entry from the provider; disabling writes still
permits an eligible cached response.

The endpoint requires Operator capability. Namespace authorization remains
server-side: a sole concrete namespace can be inferred for older clients, but
the Monitor UI always sends its selected concrete namespace. Multiple-scope
and wildcard principals must select or enter one authorized concrete value;
`*` is never a query namespace.

See [Cache policies](../guides/cache-policies.md) for precedence and namespace
rules.

## Query response evidence

```json
{
  "response": "A previously generated answer",
  "cache_hit": true,
  "similarity_score": 0.967,
  "similarity_threshold": 0.92,
  "matched_prompt": "What is semantic caching?",
  "matched_cache_key": "29769c1b33db361734e377b6e20368cd58ab3d7d048545073402ad830a0513ab",
  "cache_entry_created_at": "2026-07-17T10:00:00Z",
  "cache_entry_age_seconds": 18.4,
  "generation_skipped": true,
  "provider_called": false,
  "latency_ms": 7.2
}
```

On a miss, matched-entry fields are `null`. The nearest similarity may still
be present when an entry existed but did not meet the threshold. The leader of
a generated miss reports `provider_called=true`; a coalesced follower remains
a miss but reports `generation_skipped=true` and `provider_called=false`
because it awaited the leader.

Monitor links `matched_cache_key` to `/cache/entries/{cache_key}` only when
`cache_hit=true`. This is live-cache evidence subject to the detail endpoint's
existing Viewer authorization and non-disclosing not-found behavior. Misses
and isolated evaluation keys are never linked.

Embeddings and full inspector responses are never exposed through the query or
cache-management contracts.

## Benchmark contracts

`GET /api/v1/benchmarks/datasets` returns Viewer-accessible built-in dataset
metadata, including stable versions and SHA-256 digests derived from ordered
evaluation semantics.

`POST /api/v1/benchmarks/run` requires Operator access and
`allow_external_provider_calls=true`. Requests accept 1 through 5 repetitions
and 2 through 15 unique thresholds from 0 through 1. The backend sorts the
explicit threshold list, inserts the measured `threshold` exactly once, and
rejects a combined list beyond 15 values.

```json
{
  "dataset_id": "quick",
  "threshold": 0.92,
  "evaluation_thresholds": [0.8, 0.9, 0.92, 0.95],
  "repetitions": 1,
  "reset_cache_before_run": true,
  "estimated_cost_per_request_usd": 0,
  "estimated_cost_per_1k_tokens_usd": 0,
  "allow_external_provider_calls": true
}
```

Every response includes complete TP/TN/FP/FN counts that reconcile with cache
hits, misses, provider calls, calls avoided, and per-query outcomes. Cache hits
carry `matched_prompt` and `matched_cache_key`; misses carry neither. The
measured threshold is marked `result_kind="measured"` and all alternates are
marked `result_kind="projected"` under
`threshold_evaluation_mode="frozen_candidate_projection"`.

Each per-query `outcome` is derived from `expected_cache_hit` and
`actual_cache_hit`: true positive and false positive are cache hits, while true
negative and false negative are misses. `correct`, `provider_called`, matched
prompt, and matched key must agree with that decision. Backend response
validation and the frontend strict decoder reject inconsistent evidence.
Matched keys identify only the destroyed run-local evaluation cache and are
never live Cache-entry links.

The `reproducibility` object is allowlisted: application version, dataset
identity, provider categories, embedding dimensions, non-secret embedding and
normalization fingerprints, `measured_threshold`, `evaluation_thresholds`,
repetitions, reset policy, cost assumptions, timeout, and a configuration
fingerprint. `measured_threshold` always equals the top-level `threshold`.
Both the measured threshold and complete projection list are inputs to the
deterministically serialized configuration fingerprint. The object excludes
credentials, authorization values, provider endpoints, model identifiers, and
embeddings.

Runs use fresh in-memory evaluation caches and cannot modify the live cache or
runtime counters. `EVALUATION_TIMEOUT_SECONDS` bounds wall-clock execution.
Timeouts return HTTP `504` with `error="evaluation_timeout"`.

## Canonical Evaluations contracts

`GET /api/v1/evaluations/datasets` returns the same Viewer-accessible built-in
catalog as the legacy dataset endpoint. Dataset summaries now identify
`dataset_source` and nullable `schema_version`.

`POST /api/v1/evaluations/datasets/validate` requires Operator access and
accepts a parsed JSON dataset plus the intended repetition and threshold
counts. It returns a normalized preview and makes zero provider calls.
Structured import failures use safe `issues` with stable codes and JSON
pointers. See [evaluation dataset schema version 1](evaluation-dataset-schema-v1.md)
for the complete contract and limits.

`POST /api/v1/evaluations/runs` requires Operator access,
`allow_external_provider_calls=true`, and a discriminated source:

```json
{
  "dataset_source": {
    "kind": "builtin",
    "dataset_id": "quick"
  },
  "threshold": 0.92,
  "evaluation_thresholds": [0.8, 0.9, 0.92, 0.95],
  "repetitions": 1,
  "reset_cache_before_run": true,
  "estimated_cost_per_request_usd": 0,
  "estimated_cost_per_1k_tokens_usd": 0,
  "allow_external_provider_calls": true
}
```

For an import, use `{"kind":"inline","definition":{...}}`. The full
definition is revalidated inside the run request. Responses preserve the
existing measured/projection semantics and add source/schema evidence to the
dataset and reproducibility objects. Per-query evidence can include
`expected_match_case_id` and `note`.

### Persistent evaluation dataset catalog

Persistence is opt-in with `EVALUATION_DATASET_STORAGE=postgres`; the default
`session` mode returns a successful empty catalog with
`persistence_enabled=false` and does not require a database. Catalog operations
never call embedding or generation providers and never store generated
responses or run results.

`GET /api/v1/evaluations/datasets/persisted` requires Viewer access. It accepts
optional `namespace`, `offset`, and `limit` query parameters and returns
immutable metadata, pagination evidence, storage capability, and configured
retention/capacity limits. `GET .../{dataset_id}` also returns ordered schema v1
cases. Missing, expired, and foreign-namespace IDs all use the same
`evaluation_dataset_not_found` response.

`POST /api/v1/evaluations/datasets/persisted` requires Operator access and
revalidates the complete dataset before writing it:

```json
{
  "namespace": "default",
  "retention_days": 30,
  "dataset": {
    "schema_version": 1,
    "name": "Domain safety set",
    "cases": [
      {
        "case_id": "seed",
        "prompt": "Synthetic prompt",
        "expected_cache_hit": false
      }
    ]
  }
}
```

`namespace` may be omitted only when the principal has exactly one authorized
namespace. A wildcard administrator must supply an explicit namespace for
create, delete, and persisted runs. Identical content may be saved more than
once; each explicit save creates a separate immutable UUID record while
retaining the same content digest.

`DELETE .../{dataset_id}?namespace=default` requires Admin access and deletes
the dataset and all of its cases transactionally. Expired records are hidden
immediately and are purged opportunistically in bounded batches during catalog
operations.

A persisted run uses:

```json
{
  "dataset_source": {
    "kind": "persisted",
    "dataset_id": "123e4567-e89b-42d3-a456-426614174000",
    "namespace": "default"
  },
  "threshold": 0.92,
  "evaluation_thresholds": [0.8, 0.92],
  "allow_external_provider_calls": true
}
```

The run still uses a fresh isolated in-memory evaluation cache. Persisting a
dataset does not change threshold execution, cache decisions, provider calls,
limits, response projections, or live-cache behavior.

### Durable evaluation run history

Run history is independently opt-in with
`EVALUATION_RUN_HISTORY_STORAGE=postgres`. PostgreSQL mode requires
`DATABASE_URL` plus explicit positive retention, per-namespace capacity, and
cleanup batch settings.

History is aggregate-only: it never retains `query_results`, prompts, generated
responses, matched prompts, matched cache keys, embeddings, or the destroyed
run-local cache. Accepted runs may retain terminal `completed`, `failed`, or
`timed_out` records. Cancellation and pre-execution validation/authorization
failures are not retained.

Built-in history uses `history_namespace`; a sole concrete namespace may be
inferred, while multi-namespace and wildcard/global principals must choose a
concrete namespace. `*` is never retained ownership. Persisted runs inherit the
source dataset namespace, and unsaved inline runs remain non-durable.

`GET /api/v1/evaluations/runs` and detail require Viewer access. Scoped foreign
and missing IDs share the same not-found behavior. Admin deletion is always
concrete-namespace scoped. Deleting a persisted source dataset cascades to its
retained runs.

History retention is auxiliary: a successful evaluation remains successful if
history persistence fails and reports `history_retention.state="retention_failed"`.

### Retained run comparison

`POST /api/v1/evaluations/runs/compare` requires Viewer access and accepts two
distinct run IDs:

```json
{
  "baseline_run_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "candidate_run_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

The server resolves both runs through authorized namespace scope before
compatibility checks. Hard blockers include namespace, terminal state, dataset
schema/digest, embedding dimensions/space, normalization, repetitions, reset
policy, comparison-contract version, and threshold-evaluation mode.

Warnings keep comparison available for generation provider/configuration,
application version, cost assumptions, timeout, projection-list differences,
and comparable persisted content saved under different record identities. A
measured-threshold change is not itself a warning.

Deltas are candidate minus baseline. Threshold deltas cover only shared
projection thresholds. The opaque overall configuration fingerprint is
explanatory only, never a hard gate. `case_evidence` is `"not_retained"`.

See [Durable evaluation run history and comparison](../guides/evaluation-history.md)
for retention, exact compatibility codes, metric semantics, and recovery.

## Cache inspector query

`GET /api/v1/cache/entries` accepts:

- `namespace`: optional exact namespace;
- `search`: optional case-insensitive prompt fragment;
- `sort`: `newest`, `oldest`, `most_hit`, or `nearest_expiry`;
- `offset`: zero-based result offset;
- `limit`: page size from 1 through 100.

The response contains `items`, `total`, `offset`, `limit`, and `has_more`.
Items include the original prompt, `response_preview`,
`response_preview_truncated`, and a null `response`, but never the embedding.
Responses that fit the 240-character preview limit retain their complete
Markdown source. Longer responses use a neutral preview message instead of
cutting Markdown syntax.

`GET /api/v1/cache/entries/{cache_key}` returns the same metadata plus the
complete cached `response`. It applies the existing Viewer authentication and
namespace authorization rules and returns the same non-disclosing not-found
response for missing and unauthorized entries. The Cache Inspector requests
this detail only when a user explicitly opens the complete response. Provider
output remains untrusted text: the frontend Markdown renderer does not execute
raw HTML and continues to reject unsafe link and image URLs.

The frontend route `/cache/entries/{cache_key}` provides a deep-linkable view
of the authorized metadata and bounded response preview. It never renders the
complete response or embedding. The identifier is live operational evidence,
not a permanent record: TTL expiry, LRU eviction, deletion, restart, or an
embedding-space change can make a saved URL stop resolving. Missing and
unauthorized keys use the same neutral browser state.

`GET /api/v1/cache/stats?namespace=...` and
`DELETE /api/v1/cache?namespace=...` target one namespace. Omitting the
parameter returns global statistics or clears the active embedding space.

## Runtime metrics

`GET /api/v1/metrics` returns aggregate process-local values. With token
authentication enabled, it requires an `admin` principal with
`namespaces:["*"]`. Scoped viewers, operators, and namespace administrators
receive `403 Forbidden`. Authentication-disabled local development retains
access through its implicit global administrator.

These counters are global to the backend process and are not namespace
scoped. Namespace users should use `GET /api/v1/cache/stats`, which applies
their authorized namespace scope.

```json
{
  "observed_at": "2026-07-19T08:00:00Z",
  "uptime_seconds": 3600.0,
  "request_count": 120,
  "error_count": 1,
  "cache_hits": 72,
  "cache_misses": 48,
  "provider_calls": 46,
  "in_flight_coalesced_requests": 0,
  "average_latency_ms": 325.4,
  "p95_latency_ms": 1280.2,
  "latency_sample_size": 120,
  "cache_size": 48,
  "evictions": 3,
  "expirations": 2
}
```

Counters reset on backend restart. The bounded P95 sample retains at most 2,048
completed query latencies. Validation and rate-limit failures occur before the
query application service and are not included in its request/error counters.

For load-testing semantics and the distinction between caller decisions and
actual cache lookups, see [Load testing](../operations/load-testing.md).
