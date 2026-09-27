# Evaluation dataset schema version 1

Semantix accepts one bounded JSON schema for imported semantic-cache evaluation
datasets. Imported documents are treated as untrusted. Validation and inline
runs keep them request-local; when PostgreSQL evaluation storage is enabled,
an Operator may explicitly save a successfully validated document to an
authorized namespace. The frontend never writes the document to browser
storage, and Semantix never stores generated responses or run history with it.

## Document

```json
{
  "schema_version": 1,
  "name": "Domain safety set",
  "description": "Optional bounded description",
  "cases": [
    {
      "case_id": "seed",
      "prompt": "How do I reset my password?",
      "expected_cache_hit": false,
      "category": "account"
    },
    {
      "case_id": "repeat",
      "prompt": "Help me change a forgotten password.",
      "expected_cache_hit": true,
      "expected_match_case_id": "seed",
      "category": "account",
      "note": "Optional human-readable evidence"
    }
  ]
}
```

All objects are strict: unknown fields are rejected. Required dataset fields
are `schema_version`, `name`, and `cases`. Required case fields are `case_id`,
`prompt`, and `expected_cache_hit`.

| Field | Contract |
|---|---|
| `schema_version` | Integer literal `1` |
| `name` | Non-empty string, at most 100 characters |
| `description` | Optional non-empty string, at most 300 characters |
| `cases` | Ordered non-empty array, at most the configured case limit |
| `case_id` | Unique 1–100 character identifier matching `[A-Za-z0-9][A-Za-z0-9._:-]*` |
| `prompt` | Non-empty string, at most 2,000 characters |
| `expected_cache_hit` | Boolean semantic-cache decision |
| `expected_match_case_id` | Optional ID of an earlier case; allowed only for an expected hit |
| `category` | Optional non-empty string, at most 100 characters |
| `note` | Optional non-empty plain-text string, at most 500 characters |

Omitted categories normalize to `uncategorized`. Notes, descriptions, and
categories are rendered as escaped plain text, not Markdown or HTML.

## Identity and digest

Validation derives a request-local ID in the form `custom:<digest-prefix>`.
The SHA-256 digest covers ordered execution semantics: case ID, normalized
category, prompt, expected decision, and an expected-match reference when
present. Display name, description, and note do not affect the digest.
Reordering cases or changing execution semantics changes it.

The transient ID is evidence, not a lookup key. It cannot retrieve or share an
import after the request. An explicit persistent save assigns a separate UUID.
Saving identical canonical content more than once creates separate immutable
records with the same digest.

## Validation and limits

Submit a parsed document to `POST /api/v1/evaluations/datasets/validate`:

```json
{
  "dataset": {
    "schema_version": 1,
    "name": "Minimum set",
    "cases": [
      {
        "case_id": "only-case",
        "prompt": "Synthetic prompt",
        "expected_cache_hit": false
      }
    ]
  },
  "repetitions": 1,
  "threshold_count": 2
}
```

Validation makes zero embedding or generation calls. It reports normalized
counts, decoded bytes, warnings, `cases × repetitions` query executions,
threshold-projection evaluations, and the maximum possible generation calls.

Four independent server limits apply:

- `MAX_REQUEST_BODY_BYTES` limits the complete HTTP request before JSON
  parsing;
- `EVALUATION_DATASET_MAX_DECODED_BYTES` limits the UTF-8 bytes of the
  canonical decoded dataset object;
- `EVALUATION_DATASET_MAX_CASES` limits case count;
- `EVALUATION_MAX_WORKLOAD_QUERIES` limits `cases × repetitions`.

Defaults are 65,536 request bytes, 49,152 decoded dataset bytes, 50 cases, and
250 query executions. The decoded-content default intentionally leaves room
for the validation/run envelope beneath the existing 64 KiB request boundary.
Threshold projections do not replay provider work.

### Dataset sizing profile

On August 1, 2026, a synthetic 50-case document with bounded 284-character
prompts was validated 100 times at the maximum default workload
(`50 cases x 5 repetitions`, 15 thresholds). The canonical decoded document
was 18,418 bytes and mapped to 51 PostgreSQL rows. Mean validation time was
0.393 ms; `pg_column_size` measured 17,666 bytes across the dataset row and 50
case rows (216 + 17,450 bytes). The disposable environment used Python 3.14.6,
PostgreSQL 17.10, and an AMD Ryzen 9 5900HX.

This is sizing evidence for the default case, byte, count, and cleanup bounds,
not a production performance claim. `pg_column_size` excludes relation page,
index, and backup overhead; deployments must measure their own data and
retention policy.

## Stable dataset validation errors

Invalid imported content returns HTTP `422`,
`error="evaluation_dataset_invalid"`, a generic safe detail, and bounded
`issues`. Each issue includes `code`, `detail`, and a JSON `pointer`; safe
`case_id` and zero-based `case_index` context may also appear.

| Code | Meaning |
|---|---|
| `unsupported_schema_version` | The document is not schema version 1 |
| `required_field` | A required field is absent |
| `unknown_field` | A strict object contains an unsupported field |
| `empty_string` | A required or supplied string is empty |
| `value_too_long` | A bounded string exceeds its limit |
| `invalid_identifier` | An identifier contains unsupported characters |
| `cases_required` | The case array is empty |
| `invalid_value` | A field has the wrong JSON type or value |
| `invalid_document` | The decoded value cannot be represented as a JSON object |
| `duplicate_case_id` | A case ID occurs more than once |
| `contradictory_expected_match` | An expected miss supplies a match reference |
| `self_expected_match` | A case references itself |
| `ambiguous_expected_match` | A reference targets a duplicated ID |
| `missing_expected_match` | A referenced case does not exist |
| `forward_expected_match` | A reference does not point to an earlier case |
| `case_limit_exceeded` | The configured case cap is exceeded |
| `decoded_size_exceeded` | The decoded-content cap is exceeded |
| `workload_limit_exceeded` | Cases multiplied by repetitions exceed the cap |

Malformed request JSON follows the normal API `validation_error` path.
Prompts are never copied into dataset-validation issue details.

## Persistence, retention, and execution

`POST /api/v1/evaluations/datasets/persisted` revalidates the same strict
document before writing metadata and ordered cases transactionally. Each
record includes namespace, schema version, digest, decoded bytes, case count,
creation time, and expiry time. Default retention is 30 days, maximum retention
is 365 days, and the default active capacity is 100 datasets per namespace;
deployments can lower or raise these bounded settings within their configured
limits.

Expiry makes a record unavailable to list, detail, delete, and run operations.
Catalog operations opportunistically purge expired rows in bounded batches;
there is no background worker. Explicit deletion removes the dataset and its
cases transactionally. Built-in definitions remain code-owned and are never
copied into the catalog.

`POST /api/v1/evaluations/runs` accepts either a built-in reference or the
complete inline definition, or a namespace-authorized persisted UUID. The
server always revalidates inline content at execution; a preview is not
authorization or an integrity token. Persisted content was revalidated at save
time and is reconstructed in deterministic case order. Every source uses the
same fresh, isolated, bounded cache.

The legacy `/api/v1/benchmarks/datasets` and `/api/v1/benchmarks/run`
contracts remain available for built-in clients. Enabling persistent storage
adds the checksum-protected `0002` PostgreSQL migration; existing session-only
clients and schema version 1 documents remain compatible.
