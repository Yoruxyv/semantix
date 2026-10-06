# Reuse quality evidence

This benchmark asks whether a cached synthetic response answers a candidate request
under the same explicit response-equivalence context. Labels are REUSE / DO_NOT_REUSE,
represented as booleans. It measures answer substitutability, not vague topic similarity,
factual accuracy, authorization, production hit rate, provider speed or money saved.
The existing runtime harness measures performance separately.

## Evidence/design pass

The intended checkout was verified as E:/GitHub/semantix, origin
https://github.com/Yoruxyv/semantix.git, clean main, HEAD and origin/main both
9a2421015fd06e0b2923f693b76b717e12c919a3. A safe origin fetch left that comparison
unchanged. Implementation uses feat/reuse-quality-calibration. The initial shell
Python was 3.13.9; verification uses the existing cache environment Python 3.14.6 and
Node 24.18.0. Lexical controls and validation are offline. The opt-in semantic
benchmark uses pinned local model dependencies; it makes no generation/provider calls.

Current source owns this work under packages/cache/benchmarks and the web
features/benchmark module. The existing React Query, validators, number formatters,
LineChart and Evaluations view navigation are reused. The server's controlled
evaluation dataset/run/history API is a different execution product and is unchanged.
The web image copies public assets, so the static receipt works without changing
the server, API, Vite configuration or container build context.

Source inspection confirmed the embedded facade canonicalizes controls/ASCII repeated
whitespace before embedding, normalizes vectors, searches the scoped store and accepts
similarity >= threshold before authoritative revision/expiry confirmation. MemoryStore
uses exact float64 cosine; PostgreSQL uses pgvector cosine distance with a documented
precision difference. The current embedded default is 0.92, detected from the public
constructor by the harness. No facade signature, default, CacheStore, namespace,
EmbeddingSpace, TTL or store implementation is modified.

## Corpus and label governance

The [data README](data/README.md) explains the input files and fields.
[cases.jsonl](data/cases.jsonl) is independently authored for Semantix. All
requests, answers, entities and policy details are synthetic. No competitor data,
labels, code, examples, documentation or evaluator architecture were copied. The
competitive reference informed the evaluation question only.

[corpus.manifest.json](data/corpus.manifest.json) records version, hash, provenance and review
status. IDs are stable, sorted and unique. There are 80 cases across 20 categories:
40 calibration cases and 40 held-out cases, each with 20 REUSE and 20 DO_NOT_REUSE.
Every category has one positive and one negative in each split. The two cases within
a split can share a source answer; source/candidate prompt families do not cross
splits. Splits were assigned manually before scoring. Held-out means excluded from
threshold selection, not unseen by the author or a production sample.

Each judgement reviews the actual source response and candidate, not only prompt
similarity. notes explain the judgement and never enter embedding, generation or
runtime acceptance. context_id is a synthetic task namespace. Tenant/authorization
changes are not semantic labels. Model/system/preprocessing changes belong to scope
checks below. Output-language changes are labels only when the task explicitly
requires a different response language; digit-only bilingual output can reuse.

The corpus manifest records only a concise review state: unreviewed or
maintainer-reviewed. An agent cannot complete maintainer review. Generate the label
review view, review every case and explicitly approve its version and canonical hash
before changing that metadata. A reviewed label set describes this synthetic corpus;
it does not establish production-domain validity.

Unreviewed or dirty-source runs are labelled development-benchmark / unreviewed.
Certified/static
evidence requires completed maintainer label review and review of the computation,
source hashes, arithmetic and limitations. Creating or replacing the public receipt
is guarded by a fresh corpus hash and completed-review check.

The initial maintained corpus is version 1.0.0. No earlier reuse-quality corpus
exists in the available Git history. Local drafting corrections (including exact-output
clarifications for negation and case-sensitive identifiers) are part of that initial
version; no pre-release patch bump is retained. Labels were not changed to improve
scores, and held-out results did not select thresholds.

After the first checked-in/published version, use patch versions for reviewed case/label
corrections, minor versions for compatible expansion and major versions for incompatible
interpretation/methodology changes. Schema version is separate. Draft iterations do
not bump corpus versions. Intentional input edits recompute the hash, renew review and
stale existing public evidence. Once held-out evidence guides development, retire that
holdout for future proof and author a fresh family-disjoint evaluation version.

This small balanced dataset is descriptive; no confidence intervals, statistical
generalization or universal threshold recommendation are claimed.

Canonical hash rule: decode strict UTF-8, replace CRLF and CR with LF, remove terminal
LFs and append exactly one LF, then SHA256 the UTF-8 bytes. Do not fold Unicode,
spaces, JSON fields or key ordering for hashing. Actual semantic content edits still
change the digest. Windows CRLF, CR and trailing newline behavior are tested.
The repository already enforces LF text through .gitattributes.

## Embeddings, normalization and execution

The primary semantic baseline is [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41),
pinned to revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41, with 384 dimensions.
It runs locally on CPU in float32, one Torch thread, deterministic algorithms and
seed 0. Its pinned uncased tokenizer, 256-token truncation, mean pooling and explicit
L2 output normalization are recorded separately from the prompt-normalization
ablation. Existing cache vector normalization remains unchanged. Its tokenizer can
erase exact-character, casing and whitespace distinctions; semantic similarity
alone does not establish answer substitutability.

The opt-in uv dependency group reuse-quality pins sentence-transformers 6.1.0,
torch 2.14.1, transformers 5.18.0 and huggingface-hub 1.33.0. uv.lock pins their
transitive dependencies. Dependency groups are excluded from distribution metadata:
the minimal semantix-cache installation still requires only NumPy and Pydantic.
Receipt metadata records Python/platform, NumPy/Pydantic and the semantic packages,
including tokenizers and safetensors. Configuration/version drift fails validation.

Two deterministic lexical controls remain available:

- token-count v1: case-sensitive Unicode word tokens plus punctuation tokens;
- char-trigram v1: overlapping three-character slices, preserving case and punctuation.

Both map feature counts into 2048 bins using the first four SHA256 bytes interpreted
big-endian modulo 2048. They have no learned model, download, provider or fitted
vocabulary. Collisions and bag-of-token order loss are deliberate control limits.
Their scores must not be presented as representative semantic-cache quality.

Only an explicit --semantic run imports model dependencies. --download-model is
an explicit first-download option; otherwise the exact revision must already be
cached under the ignored .cache/reuse-quality/model-cache directory. No credentials
or remote model code are needed. This is a maintainer/release operation, outside
ordinary CI and pre-commit. Exact-text embeddings are reused across replays and
ablations; this memoization does not use labels, responses or notes and is not a
runtime cache change. No embedding latency claim follows.

For each baseline, measure three ablations using the same labels/grid/selection rule:

- raw: existing facade input behavior; no additional prompt_normalizer;
- whitespace: Python str.split/join collapses all Unicode whitespace;
- NFC: Unicode canonical composition, without case or punctuation stripping.

The ablation uses the existing optional prompt_normalizer contract. Generation input
and runtime defaults are unchanged. Each preprocessing configuration has a distinct
EmbeddingSpace identity. No aggressive light variant is justified here; no lowercasing,
punctuation stripping, alphanumeric sanitization or runtime evaluator is introduced.

A case uses a fresh MemoryStore, seeds one source via public set, then resolves the
candidate READ_ONLY. Scoring never receives source_response or notes. The response is
only the seeded cache payload. Default and selected-threshold decisions are replayed
through resolve and checked against the projection. This prevents cache growth,
eviction and candidate competition from contaminating pair acceptability. It does
not measure a realistic multi-candidate retrieval or admission workload.

The grid is 0.50, 0.65, 0.75, 0.85, 0.90, 0.92, 0.95, 0.97, 1.00. Select per
embedding/normalization on calibration only: fewest FP, most TP, highest threshold
as final tie-break. The unchanged default is always reported separately. Held-out
sweeps are descriptive and cannot be used to reselect a threshold as proof.
Lower thresholds can increase both correct and wrong reuse; higher thresholds can
reject all positives without proving safety.

Confusion counts are TP/FP/FN/TN; the raw FP count is retained.

- Reuse precision = TP / (TP + FP).
- False acceptance rate (false-positive rate) = FP / (FP + TN): denominator is labelled negatives.
- Wrong among accepted = FP / (TP + FP) = 1 - reuse precision: denominator is accepted hits.
- Reuse recall = TP / (TP + FN).
- Missed reuse / false rejection rate = FN / (TP + FN): denominator is labelled positives.
- Generation avoidance = (TP + FP) / all cases; this includes wrong reuse.

False acceptance rate and wrong among accepted are different metrics; do not label
the former simply "Wrong reuse". Undefined denominators are null / n/a. Wrong reuse
is safety-sensitive, so avoidance alone is not success.

Per-category held-out confusion metrics at default and calibrated thresholds expose
normalization regressions. NFC erases byte-sensitive Unicode distinctions; whitespace
folding erases exact-character spacing distinctions. Inspect unicode-004 and
whitespace-004. Case-sensitive identifiers, decimals, versions, operators and regex/CSS
punctuation also constrain any future normalization decision. More normalization is
not always better. Raw is the conservative observed choice; do not promote a new
runtime default from this small synthetic corpus.

Additional preprocessing ns/prompt is a local perf_counter_ns microbenchmark over
100 passes, excluding facade canonicalization, embedding, store and generation.
Timing is descriptive and naturally varies; scores and metric counts must reproduce.
It is not an end-to-end latency or performance comparison.

## Scope correctness evidence

Reuse existing executable checks rather than duplicating conformance:

- test_engine.py::test_namespaces_spaces_and_changed_metadata: namespace isolation,
  mismatched identity, separate correctly configured space and changed metadata;
- test_engine.py::test_bad_embedding and test_store_conformance.py::test_invalid_vectors_namespaces_and_ttl:
  dimension mismatch and invalid vectors rejected;
- test_store_conformance.py::test_revision_and_detached_candidate: stale revision rejected;
- test_store_conformance.py::test_expiry_retention_cap_and_non_sliding_hit:
  expired candidate not confirmed, non-sliding TTL;
- test_engine.py::test_normalizer_changes_matching_only:
  preprocessing only changes matching, not generation input.

Changing model or preprocessing requires a correctly configured distinct identity.
This benchmark's separate normalization identities demonstrate that choice. Namespace
selection is an application obligation, not authentication or a semantic-model metric.

## Reproduce and review

From packages/cache, using the existing locked environment:

```text
uv sync --locked --extra dev
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark --output ../../.cache/reuse-quality/controls.json
uv run --no-sync pytest tests/test_reuse_quality.py
uv run --no-sync mypy benchmarks/reuse_quality tests/test_reuse_quality.py
uv run --no-sync ruff check --config ../../ruff.toml .
uv run --no-sync pytest --cov=semantix_cache
```

For the explicit semantic maintainer operation, install the opt-in locked group
and allow the initial public-model download:

~~~text
uv sync --locked --extra dev --group reuse-quality
uv run --no-sync python -B -m benchmarks.reuse_quality.benchmark --semantic --download-model --output ../../.cache/reuse-quality/semantic-development.json
~~~

Subsequent local runs use --semantic without --download-model, with the cached
revision. For strict offline reproduction, also set HF_HUB_OFFLINE=1 and
TRANSFORMERS_OFFLINE=1 in the process environment. Compare scores and confusion
counts, excluding timestamp, platform-dependent microtiming and source provenance.
No pretrained inference runs during ordinary automated validation.

Raw runs use the existing write_result guard: outputs outside Git-ignored paths
are refused. Keep raw scores, development receipts and logs under .cache/reuse-quality.
Only source, corpus, schema, tests, methodology and one reviewed public summary belong
in the reviewable diff. No secrets/private prompts/provider bodies are collected.

The result contract is the strict Pydantic Summary in
[benchmark.py](benchmark.py), exported as
[summary.schema.json](schemas/summary.schema.json). Tests check schema parity,
hash integrity, stable scores, arithmetic, invalid IDs, split separation, >= boundary,
zero denominators, raw output restrictions and public-field privacy.

Generate a temporary maintainer view of every case (including exact JSON escapes):

```text
uv run --no-sync python -m benchmarks.reuse_quality.benchmark --review-corpus ../../.cache/reuse-quality/corpus-label-review.md
```

Review source_prompt, source_response and candidate_prompt together, and check
expected_reuse and notes for every ID/category/split. Explicitly approve the corpus
version and canonical cases SHA256, or identify corrections by ID. Do not approve
metrics merely because the labels produce a desirable result. Content corrections
require a recomputed canonical hash and a new review; version them under the data
README's policy after the first checked-in/published corpus. Metadata
review status does not change the cases hash.

After explicit maintainer approval, record label_review as maintainer-reviewed in
data/corpus.manifest.json. Then review the frozen labels, raw computation, exact
source hashes, arithmetic and limitations. Require a clean accepted source state
before replacing the public SSOT:

```text
uv run --no-sync python -m benchmarks.reuse_quality.benchmark --semantic --output ../../.cache/reuse-quality/reviewed.json --review-public
```

This command fails before execution if label review is incomplete, and checks the
hash, reviewed metadata, current clean Git state and source hashes again before
writing. It never marks labels reviewed.

After generation, from apps/web, apply the existing frontend JSON formatting:

```text
npx prettier public/benchmarks/reuse-quality-summary.json --write
```

Formatting must preserve the parsed receipt, including all metrics and identities.
Run the shared validator again before committing. CI only checks formatting and
evidence; it does not generate or rewrite the public receipt.

The public file is deliberately absent until approval; the dashboard then shows
its unavailable state. No placeholder receipt or development scores are served.

The public receipt is
`apps/web/public/benchmarks/reuse-quality-summary.json` (created after approval).
It includes HEAD, a dirty-source flag and canonical hashes of the feature's Python
sources, corpus metadata, summary schema and actual cache runtime sources.
Uncommitted development evidence is not attributed
solely to an unchanged HEAD: these file hashes identify the tested work. Dirty source
can never create a final reviewed receipt. Regenerate after a source change; do not silently serve stale numbers.

In /evaluations select **Reuse quality**. The feature fetches this static asset once
per query lifecycle with cancellation, a timeout and no API credentials. It never
scrapes raw outputs, runs a benchmark or selects a new threshold. An incompatible or
missing receipt yields an unavailable state. React files contain no benchmark
result constants. Python checks validate/reproduce
the public receipt when present; frontend tests use an explicitly synthetic test-only
fixture so they can exercise rendering without approving the actual corpus.

From apps/web:

```text
npm run test -- tests/features/benchmark/ReuseQuality.test.tsx
npm run lint
npm run format:check
npm run imports:check
npm run test:coverage
npm run build
npm run bundle:check
npm run test:e2e -- tests/e2e/reuse-quality.spec.ts
```

Serve Vite on its existing port 4173 and set SEMANTIX_E2E_BASE_URL to
http://127.0.0.1:4173 for the isolated browser test. It intercepts the live API and
the manifest with a test-only fixture, and
requires no server or provider. The test checks required widths/landscapes, enlarged
text, keyboard selection, axe and missing-receipt behavior. Existing CI collects
the new pytest/Vitest/Playwright tests; no new workflow or paid gate is required.

## Interpretation limits

Synthetic hand-authored labels, one candidate, small family counts and one pinned
English pretrained model limit generalization. No claims of universal semantic accuracy, zero wrong
answers, provider compatibility, production generation savings or optimal thresholds
follow. PostgreSQL precision and live context changes need separate evidence.
Independent domain label review, representative fresh holdouts and models suited to
the intended production domain are needed before deployment calibration. A candidate evaluator remains
a later design question; none was added.

The existing page hierarchy and styling are preserved. A native grouped selector
separates the pretrained semantic baseline from lexical controls. The initial
selection is the semantic baseline's raw configuration; each group retains all
recorded ablations. Reviewed public evidence requires all three semantic ablations.
Controls remain available as explicitly labelled stress tests.

The chart and interpretation remain visible. Detailed threshold results and Evidence
limitations use native collapsed details sections with keyboard-accessible summaries.
The UI accepts only clean reviewed receipts and otherwise shows unavailable evidence.

## Automatic validation and explicit evidence replacement

From packages/cache, run the offline, non-mutating validator:

```text
python -B -m benchmarks.reuse_quality.benchmark validate
```

Use the existing locked cache environment. The -B flag prevents Python bytecode
writes. Validation parses all cases and metadata, enforces IDs/splits/label balance,
recomputes canonical hashes, checks schema parity, and validates any existing public
receipt's schema, arithmetic, calibration-selected threshold and truthful review
state, plus the pinned semantic model/revision, dimensions, preprocessing and
package identity. Missing public evidence is explicitly reported as unavailable, without
creating a placeholder or certifying the corpus.

Staleness compares the complete current input-file set and canonical hashes, not
current HEAD. Inputs are this feature's Python implementation, cases, corpus
manifest, summary schema, benchmarks/common.py, cache pyproject.toml/uv.lock, and
the root semantix_cache Python modules forming the current facade/MemoryStore import
closure. Optional provider adapters and PostgreSQL implementation are excluded
because this benchmark does not execute them. Update this input boundary if a future
benchmark actually uses those paths. Dependency pins are conservative execution
inputs. No unrelated documentation or frontend styling is fingerprinted.

source_sha identifies the clean source commit that produced the receipt. A later
receipt-only commit, or unrelated documentation/frontend changes, may have a different
HEAD while these input hashes still match. Validation must continue to pass then.
It does not require the current working tree to be clean; it requires the recorded
public source_dirty flag to be false and the recorded inputs to remain current.

The local pre-commit hook selects only staged feature/evidence files, the public
JSON receipt, root semantix_cache Python modules, benchmarks/common.py and cache
dependency configuration. It skips unrelated docs, translations, frontend components
and styling, and server/client changes. It launches the validator in the existing
cache environment with -B; no environment sync, provider request or model download
occurs. Install pre-commit hooks explicitly using the existing pre-commit tool.
The existing Quality workflow runs validation in its embedded Python matrix;
existing pytest, frontend unit/coverage, Ruff, mypy, import, format and build gates
cover this feature. No second test workflow or paid/model-backed job is added.

Neither hook nor CI ever generates/replaces a public receipt, edits labels/review
state, changes schemas, commits, pushes or marks evidence reviewed. Validation checks
integrity and reproducibility contracts; it cannot prove that semantic labels or a
model are correct.

Canonical maintainer replacement sequence:

1. Review the corpus and approve its version and canonical hash explicitly.
2. Record the actual review state and reach an accepted benchmark/runtime/corpus
   implementation commit, with separately authorized Git actions.
3. Start from that clean source commit and run the benchmark into ignored raw output.
4. Verify source_dirty is false; inspect results, source hashes and limitations.
5. Explicitly use --review-public to rerun and replace the public aggregate receipt.
6. Inspect the JSON and frontend diff; run validation again.
7. Commit the receipt separately if appropriate and separately authorized.

Recomputing receipts automatically would conceal changed evidence. A stale reviewed
receipt therefore fails validation with instructions to rerun and review from clean
source. Real pretrained semantic-model execution is an explicit maintainer operation,
not a hook/CI task. Ordinary automation checks the reviewed receipt's pinned model,
revision, dimensions, preprocessing, package identity and current input hashes without
loading the model. Lexical controls and contract tests stay deterministic/offline.

Validation errors print exact remediation commands to run from packages/cache:

```text
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark refresh-manifest
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark generate-schema
uv run --no-sync --offline python -B -m benchmarks.reuse_quality.benchmark check-schema
```

refresh-manifest validates the full cases first, recomputes the canonical SHA, and
resets label_review to unreviewed if content changed. It never changes cases or bumps
a version; choose the version under the data README policy and obtain renewed review.
An already matching digest does not rewrite the manifest. Schema generation is
likewise explicit. Neither helper is ever called by pre-commit or CI; validation
passes for valid state regardless of how the files were authored.
