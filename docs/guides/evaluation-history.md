# Durable evaluation run history and comparison

Semantix can retain terminal **aggregate** evaluation evidence in PostgreSQL and
compare exactly two retained runs with a server-backed compatibility assessment.
The feature is opt-in and independent from persistent evaluation dataset
storage.

History is intentionally not a replay log. It never stores per-query prompts,
generated responses, matched prompts, matched cache keys, embeddings, or the
destroyed run-local cache.

## Enable durable history

History is disabled by default:

```env
EVALUATION_RUN_HISTORY_STORAGE=disabled
EVALUATION_RUN_HISTORY_RETENTION_DAYS=
EVALUATION_RUN_HISTORY_MAX_PER_NAMESPACE=
EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE=
```

To enable PostgreSQL history, configure `DATABASE_URL` and set all three numeric
history settings explicitly:

```env
EVALUATION_RUN_HISTORY_STORAGE=postgres
EVALUATION_RUN_HISTORY_RETENTION_DAYS=30
EVALUATION_RUN_HISTORY_MAX_PER_NAMESPACE=100
EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE=100
```

The three numeric values must be positive. They intentionally have no implicit
PostgreSQL-mode defaults: a deployment that elects to retain evaluation
evidence must also choose its retention, per-namespace capacity, and cleanup
batch size.

`EVALUATION_DATASET_STORAGE` and `EVALUATION_RUN_HISTORY_STORAGE` are separate.
A deployment may persist either feature independently.

When history is disabled, the list endpoint returns an empty capability-aware
catalog. Detail, delete, and comparison operations return the stable
`evaluation_run_history_disabled` error.

## What becomes durable

A run receives durable history only after pre-execution validation and
authorization succeed and the evaluation is accepted.

Retained terminal states are `completed`, `failed`, and `timed_out`.
Cancellation is not persisted. Validation, authorization, and configuration
errors before the accepted-run boundary do not create a retained run identity.

Completed records retain run identity, concrete namespace, timing, dataset
identity/digest/counts/categories, safe reproducibility metadata, aggregate
measured metrics, and aggregate threshold projections.

Failed and timed-out records retain terminal timing plus a stable failure code
and safe public detail when available. Unknown internal exception messages are
not retained.

History persistence is auxiliary. If a completed evaluation succeeds but the
history write fails, the measured result still returns with
`history_retention.state="retention_failed"`. A history write failure also must
not replace the original evaluation failure.

## Dataset-source and namespace rules

Durable ownership always uses a concrete namespace. `*` grants authorization
scope; it is never stored as run ownership.

For built-in datasets:

- exactly one concrete authorized namespace may be inferred;
- multiple concrete namespaces require explicit selection;
- wildcard/global access requires explicit `history_namespace`;
- authentication-disabled local mode also requires a concrete namespace for
  durable built-in history.

Persisted runs inherit the source dataset namespace. Unsaved inline datasets
remain non-durable even when history storage is enabled.

Scoped readers receive the same not-found response for a missing run and a run
outside their namespace scope. Admin deletion is likewise namespace-scoped and
non-disclosing.

## Retention and deletion

Built-in expiry is:

```text
completed_at + EVALUATION_RUN_HISTORY_RETENTION_DAYS
```

Persisted-dataset history cannot outlive its source dataset:

```text
min(
  completed_at + EVALUATION_RUN_HISTORY_RETENTION_DAYS,
  source_dataset_expires_at
)
```

Expired cleanup is bounded by
`EVALUATION_RUN_HISTORY_CLEANUP_BATCH_SIZE`. Rolling capacity is namespace
scoped; the deterministic oldest retained records are pruned by
`completed_at ASC, run_id ASC`, and only enough records are removed to make
room for the incoming terminal record.

Deleting a persisted source dataset cascades to retained runs. Threshold rows
cascade with their parent run. Retained evaluation history uses exactly two
aggregate tables:

- `semantix.evaluation_runs`
- `semantix.evaluation_run_thresholds`

Do not edit released migration `0003_evaluation_run_history.sql` after it has
been applied.

## History API

```text
GET    /api/v1/evaluations/runs
GET    /api/v1/evaluations/runs/{run_id}
DELETE /api/v1/evaluations/runs/{run_id}
POST   /api/v1/evaluations/runs/compare
```

Viewer access is sufficient to list, inspect, and compare authorized history.
Deletion requires Admin access and a concrete authorized namespace.

Comparison accepts exactly two distinct run IDs. It is read-only and is not
persisted.

## Comparison compatibility

Hard incompatibilities block deltas:

| Code | Meaning |
|---|---|
| `namespace_mismatch` | Ownership namespaces differ |
| `baseline_not_completed` | Baseline is not completed |
| `candidate_not_completed` | Candidate is not completed |
| `dataset_schema_mismatch` | Dataset schema contracts differ |
| `dataset_digest_mismatch` | Dataset digests differ |
| `embedding_dimensions_mismatch` | Embedding dimensions differ |
| `embedding_space_mismatch` | Embedding-space fingerprints differ |
| `normalization_mode_mismatch` | Normalization modes differ |
| `normalization_fingerprint_mismatch` | Normalization fingerprints differ |
| `repetitions_mismatch` | Repetition counts differ |
| `reset_policy_mismatch` | Reset policies differ |
| `comparison_contract_version_mismatch` | Comparison contract versions differ |
| `threshold_evaluation_mode_mismatch` | Threshold evaluation modes differ |

Warnings keep comparison available:

| Code | Meaning |
|---|---|
| `generation_provider_changed` | Generation provider changed |
| `generation_configuration_changed` | Safe generation configuration changed |
| `application_version_changed` | Application version changed |
| `cost_assumptions_changed` | Cost assumptions changed |
| `evaluation_timeout_changed` | Evaluation timeout changed |
| `projection_list_changed` | Projection threshold lists differ |
| `persisted_dataset_identity_changed` | Comparable persisted content has a different saved identity |

A measured-threshold change is not itself a blocker or warning. The opaque
overall configuration fingerprint is explanatory only and never a hard gate.

The safe generation configuration fingerprint may account for the generation
provider, selected generation model, `GENERATION_MAX_NEW_TOKENS`, and
`PROVIDER_MAX_RESPONSE_BYTES` without exposing raw model identifiers, secrets,
provider endpoints, or base URLs.

## Reading deltas

Every returned delta is `candidate - baseline`.

Quality-direction labels are reserved for metrics with an unambiguous
objective under a compatible workload:

- higher is better: precision, recall, F1, true positives, true negatives;
- lower is better: false positives, false negatives, measured latency metrics.

Measured threshold and hit rate are shown as changed rather than globally
improved/regressed. Provider calls, calls avoided, and estimated latency/token/
cost savings are contextual efficiency signals and must be interpreted with
correctness metrics.

Threshold deltas cover thresholds shared by both runs. Historical case evidence
is `not_retained`; comparison never reconstructs per-query evidence.

## Backup and recovery

PostgreSQL backups may contain retained aggregate history. Even without prompts
or generated responses, dataset identity, categories, timing, fingerprints,
failure metadata, and measured aggregates can be operationally sensitive.

Record history storage/retention/capacity settings beside backups. After
restore, verify migration `0003`, both history-table row counts, `/ready`, and an
authorized history list/detail request when history is enabled.

A destructive PostgreSQL volume rebuild removes retained run history together
with other PostgreSQL-backed Semantix data.

## Release verification

Backend:

```powershell
cd backend
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests scripts
```

For SQL/migration/PostgreSQL history changes, use a dedicated disposable test
database:

```powershell
$env:PGVECTOR_TEST_DATABASE_URL = "<dedicated-test-postgresql-dsn>"

uv run --locked pytest `
    tests/benchmark/infrastructure/test_postgres_history_repository.py `
    tests/benchmark/infrastructure/test_postgres_history_queries.py `
    tests/benchmark/infrastructure/test_postgres_repository.py
```

Never point destructive integration tests at development or production data.

Frontend:

```powershell
cd frontend
npm run lint
npm run imports:check
npm test
npm run build
npm run bundle:check
npm run test:e2e -- tests/e2e/tablet-responsive.spec.ts
```

The Playwright suite expects its configured frontend base URL to be serving
unless `SEMANTIX_E2E_BASE_URL` points elsewhere.
