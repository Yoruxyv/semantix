# Evaluations and benchmarking

The Evaluations workspace measures cache quality, latency, and provider-call
savings against ordered prompts with explicit expected `HIT` or `MISS`
decisions. Every accepted run creates a fresh isolated in-memory cache and
never reads, writes, clears, or increments counters on the interactive cache.
When reset is enabled the run-local cache is cleared before every repetition;
when disabled, later repetitions in that same run can reuse earlier state.
Completed, failed, timed-out, and cancelled runs never seed a later run.

## Measured reference run

The README result came from an actual Phase 4 benchmark API run:

| Run property | Value |
|---|---|
| Run ID | `0488b35e487b4d0f94e151a97271847b` |
| Started | July 19, 2026 at 08:15:30 UTC |
| Dataset | Quick semantic safety set |
| Queries | 8 |
| Repetitions | 1 |
| Cache reset | Yes |
| Threshold | `0.92` |
| Providers | Hugging Face embeddings and generation |
| Prompt typo correction | Enabled |

Measured metrics:

| Metric | Result |
|---|---:|
| Cache hits / misses | 4 / 4 |
| Provider calls / avoided | 4 / 4 |
| Hit rate | 50% |
| Average latency | 2051.5 ms |
| Median latency | 1314.3 ms |
| P95 latency | 5550.0 ms |
| Average hit latency | 330.3 ms |
| Average miss latency | 3772.7 ms |
| Estimated latency saved | 13,769.6 ms |
| False positives / negatives | 0 / 0 |
| Precision / recall / F1 | 1.0 / 1.0 / 1.0 |

This is one local observation, not a service-level claim. The application
reported provider types but intentionally does not expose model identifiers in
health or benchmark responses. Provider load, selected models, network,
normalization, machine resources, and dataset ordering affect results.

At projected threshold `0.70`, the same observed scores produced one false
positive. At `0.98`, they produced one false negative. That is why the README
reports the evaluated threshold and quality errors alongside latency.

## Built-in datasets

| Dataset | Version | Queries | Expected hits | Expected misses | Coverage |
|---|---|---:|---:|---:|---|
| `quick` | `1.0.0` | 8 | 4 | 4 | Seed, exact duplicate, paraphrase, typo, unrelated, negation, different intent |
| `extended` | `1.0.0` | 12 | 6 | 6 | Quick set plus more paraphrase, typo, negation, and intent boundaries |

Cases are ordered because earlier misses seed later expected hits. Every case
has an explicit expected classification. The API returns a SHA-256 digest
derived from ordered case IDs, categories, prompts, and expected decisions;
display names and descriptions do not affect it.

## Run from the frontend

1. Open <http://localhost:4173/evaluations>.
2. Select a built-in dataset, or choose **Custom JSON dataset** and select a
   schema version 1 file.
3. To reuse a validated import later, open **Datasets** and explicitly save it
   to an authorized namespace. This control appears only when PostgreSQL
   evaluation storage is enabled and the principal has Operator access.
4. Optionally disclose the advanced sweep controls and choose a start, end,
   and step. The UI shows the resulting explicit list and includes the measured
   threshold exactly once.
5. Keep one repetition and reset enabled for a short independent run.
6. Review the bounded case count and maximum generation-call warning.
7. Confirm the run.
8. Select a confusion-matrix outcome or use the false-positive and
   false-negative quick filters.
9. Search the measured cases and open a case detail to inspect its expected and
   actual decisions, match evidence, threshold, provider-call state, latency,
   and dataset identity.
10. Inspect threshold projections and similarity distributions separately from
   measured case evidence.
11. Export JSON for the complete response or CSV revision 3 for independently
    interpretable per-case evidence.

Benchmark requests may call the selected generation provider. Review provider
cost, rate limits, and data handling before confirming.

### Compare a run with current runtime diagnostics

Global administrators can open **Observability → Runtime diagnostics** to
compare an evaluation export's embedding-space, generation-configuration, and
normalization fingerprints with the current backend process. Matching values
support environment review but do not replace dataset digest, measured
threshold, repetitions, reset policy, or the run's overall configuration
fingerprint. Diagnostics are current process state only and are not retained as
evaluation history.

The section also shows provider categories, embedding dimensions, normalization
status, cache readiness, evaluation limits, and whether dataset or run-history
persistence is enabled. It intentionally omits model names, provider/database
URLs, credentials, prompts, responses, namespaces, dataset names, and run IDs.

Leaving the Evaluations workspace aborts the browser request and prevents a late
response from updating the unmounted page. It does not guarantee that provider
work already accepted by the backend has stopped.

### Session-local custom datasets

Custom JSON files are parsed locally, then sent to the server validation
endpoint for authoritative schema, reference, byte, case, and workload checks.
The preview makes zero embedding or generation calls. It shows the transient
digest, expected hit/miss counts, decoded size, warnings, bounded query work,
and maximum possible provider calls.

The imported object remains only in the mounted Evaluations feature unless an
Operator explicitly saves it. Removal, reload, sign-out, and an
authentication-principal change clear the session copy. Semantix does not use
`localStorage`, `sessionStorage`, IndexedDB, or a service worker for imported
datasets. During execution, prompts may leave the system through the configured
providers; the review warning makes that boundary explicit.

The server revalidates the inline definition in the run request. A successful
preview is not a reusable authorization or integrity proof. Read the
[schema version 1 reference](../reference/evaluation-dataset-schema-v1.md)
before producing files.

### Persistent dataset catalog

Set `EVALUATION_DATASET_STORAGE=postgres` and configure `DATABASE_URL` to
enable the Datasets catalog. Session-only remains the default and displays a
clear disabled-persistence fallback without opening a database connection.

The catalog distinguishes Built-in, Session, and Persisted sources. Viewer
principals can list and inspect permitted persisted metadata and cases.
Operators can explicitly save a validated session import and select persisted
detail for a later run. Admins can delete a dataset after an inline
confirmation names its exact dataset, namespace, case count, and consequence.
Principals with multiple namespaces must choose one for save; wildcard
administrators must type an explicit namespace.

Every persisted record includes an immutable UUID, namespace, schema version,
digest, decoded size, case count, creation timestamp, and expiry timestamp.
The default retention is 30 days, the maximum is 365 days, and the default
capacity is 100 active records per namespace. Identical content may be saved
again as a separate record with the same digest. Expired content disappears
from catalog and run access and is purged opportunistically in bounded batches.
No run summary, per-query result, generated response, embedding, or live-cache
entry is persisted by the **dataset catalog**. Durable aggregate run history is
a separate opt-in feature controlled by `EVALUATION_RUN_HISTORY_STORAGE`; see
[Durable evaluation run history and comparison](evaluation-history.md).

When run history is enabled, built-in runs require a concrete history namespace
unless the authenticated principal has exactly one concrete namespace that the
server can infer. Persisted runs inherit the source dataset namespace. Unsaved
inline datasets remain non-durable.

The backend separately applies `EVALUATION_TIMEOUT_SECONDS` (300 seconds by
default, validated from greater than zero through 3,600). A timeout returns the
structured `evaluation_timeout` error and discards the run-local cache. It does
not claim that a remote provider has cancelled work it already accepted.

## Run through the API

PowerShell:

```powershell
$body = @{
    dataset_source = @{
        kind = "builtin"
        dataset_id = "quick"
    }
    threshold = 0.92
    evaluation_thresholds = @(0.80, 0.90, 0.92, 0.95)
    repetitions = 1
    reset_cache_before_run = $true
    estimated_cost_per_request_usd = 0
    estimated_cost_per_1k_tokens_usd = 0
    allow_external_provider_calls = $true
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/evaluations/runs" `
    -ContentType "application/json" `
    -Body $body
```

`allow_external_provider_calls=true` is mandatory. It prevents an accidental
benchmark from silently creating provider traffic.

## Metric interpretation

- **Provider calls avoided** equals queries served from the benchmark cache.
- **True-positive hit** means an expected reuse was served from the cache.
- **True-negative miss** means a required generation remained a miss.
- **Precision** answers: of returned hits, how many were expected hits?
- **Recall** answers: of expected hits, how many were returned as hits?
- **False positive** means the cache returned a response where the dataset
  expected a miss.
- **False negative** means the cache generated a new response where reuse was
  expected.
- **Estimated latency saved** uses the run's observed average hit/miss latency.
- **Estimated token savings** uses a simple character-based approximation.
- **Estimated costs** use the optional values supplied by the operator.

Cost and token estimates are evaluation aids, not provider billing records.
Measured classification and latency fields, estimated savings fields, and
projected threshold fields are named and displayed separately.

Threshold charts are **frozen-candidate projections**. They reclassify the
nearest-match scores observed in the original run without replaying cache
writes at each alternate threshold. Because the candidate set does not evolve,
their quality, provider-savings, and latency estimates can differ from a real
ordered run at that threshold. The projection makes no additional provider
calls and uses the original run's average hit and miss latency.

## Error analysis and case details

The four-cell confusion matrix is an interactive filter over the measured
cases. Each cell has a text label, count, explanation, and selected state.
False-positive and false-negative quick filters provide direct paths to the
two correctness errors, while search remains bounded to the current
session-local result. Selecting “All cases” restores the complete deterministic
sequence and repetition order.

Compact cards expose the essential evidence on mobile and tablet widths. The
wide comparison table remains available inside an explicit scroll region on
larger viewports. Both presentations open the same inline case detail. Prompts,
case IDs, categories, and matched prompts are rendered as escaped plain text,
not Markdown or HTML.

A matched evaluation key is evidence from the destroyed run-local cache. It is
shown without a link and does not identify a record in the live Cache
workspace. Case details also distinguish the measured threshold from the
frozen-candidate projection charts and never offer automatic threshold
application.

The complete per-query result and local filters are discarded on reload unless
the user exports them. When PostgreSQL run history is enabled, Semantix may
retain the terminal **aggregate** run record separately, but it never stores the
per-query prompts, generated responses, matched prompts, matched cache keys, or
run-local cache. Saving a dataset alone never saves a run.

## Export formats

JSON remains a structurally complete copy of the run response. CSV export
schema revision 3 repeats the run ID, timestamps, dataset source, import schema
version, dataset identity, measured
and projected threshold context, safe configuration fingerprint and provider
metadata on every case row, followed by complete case evidence including
repetition, expected match reference, note, outcome, provider-call state,
matched prompt, and matched key.

CSV string cells beginning with `=`, `+`, `-`, or `@` are prefixed with a
single quote so spreadsheet applications treat them as text. JSON values are
not modified. New downloads use the `semantix-evaluation-<run-id>` filename
stem; the former `semantix-benchmark-<run-id>` download name was a UI filename,
not a stable API contract.

## Reproducibility metadata

Run responses include the run ID, timezone-aware timestamps, dataset version
and digest, `reproducibility.measured_threshold`, the explicit
`evaluation_thresholds` list, repetitions, reset policy, cost assumptions,
timeout, provider categories, embedding dimensions, and SHA-256 fingerprints
for the embedding space, normalization configuration, and complete safe
configuration. The metadata measured threshold must equal the response's
top-level `threshold`. It is fingerprinted separately from the complete
projection list, so runs measured at different thresholds cannot share a
configuration fingerprint even when their projection lists match.

This is a positive allowlist. It does not contain credentials, authorization
material, private provider endpoints, raw embeddings, or model identifiers.
Matched cache keys are evaluation evidence only and do not identify entries in
the live Cache workspace.

## Comparing runs responsibly

Record at least:

- timestamp and run ID;
- dataset and ordering;
- threshold and repetition count;
- cache-reset policy;
- embedding and generation providers/models;
- prompt normalization settings;
- backend and database mode;
- local hardware and Docker resource limits;
- relevant provider or network conditions.

Do not compare runs as though only the threshold changed when another item in
that list also changed.

For retained runs, prefer the server-backed comparison endpoint and History UI.
They enforce explicit compatibility blockers, surface configuration warnings,
and calculate candidate-minus-baseline aggregate deltas. See
[Durable evaluation run history and comparison](evaluation-history.md).
