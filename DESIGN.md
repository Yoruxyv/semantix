# Product and engineering principles

Semantix exists to make semantic-cache decisions visible and testable. These principles
describe the product contract; [ARCHITECTURE.md](ARCHITECTURE.md) records its present
wiring.

## Inspect decisions

A query reports hit or miss, similarity and threshold, provider-call behavior, latency,
and matched-entry evidence when a live hit exists. Cache inspection and evaluation make
the consequences of a threshold visible. Keep these signals truthful and scoped to what
was actually measured. Raw embeddings are not a primary product interface.

## Favor safe reuse over maximum hit rate

Similarity is probabilistic. A false hit can return the wrong cached response even when
the score clears the threshold. Namespace and embedding-space isolation, validated
provider output, and explicit read/write/private policies protect cache integrity.
Evaluation reports false positives and false negatives; it does not claim a universally
safe threshold.

## Keep evaluation separate from live cache

Evaluation uses a fresh bounded run cache and cannot seed or read the interactive cache.
Threshold alternatives are projections from one measured candidate set, not hidden
repeated provider calls. Runs are bounded by dataset size, workload, and time. An
operator explicitly acknowledges provider-backed work when required.

## Leave consequential controls with people

The similarity threshold is visible and global in the current product. Evaluation does
not apply a recommendation automatically. Provider selection and credentials are
deployment-owned, not edited from the browser. Persistent dataset storage is optional
and requires a separate authorized save.

## Treat authorization and privacy as server duties

The backend resolves role and namespace permissions; UI checks improve usability but do
not grant access. Foreign namespace resources should not leak through detail responses.
Private requests bypass live cache reads and writes and are omitted from Monitor traces.
Diagnostics and aggregate metrics omit prompts, full responses, credentials, private
endpoints, and raw settings. Retention and exports must be explicit.

## Make public behavior predictable

Validate inputs at HTTP boundaries, return stable bounded error contracts, and keep
browser and SDK decoders aligned with backend responses. The independently installable
SDK reflects selected public HTTP capabilities; new backend behavior is not
automatically an SDK feature.

## Scope operational claims to evidence

Report workload, provider, cache state, topology, host, duration, and failures for
performance claims. Keep failed runs and remediations visible. The documented production
verdict covers only the audited workload, topology, and deployment boundary, with its
stated residual limits. Favor simple proven mechanisms until evidence justifies new
distributed infrastructure.

Semantix remains a semantic-cache service and workbench, not a generic chatbot or
unrelated platform category.
