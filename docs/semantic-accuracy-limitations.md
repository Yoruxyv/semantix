# Semantic-answer accuracy limitations

Semantix retrieves cached responses using embedding similarity within an
application-selected namespace and embedding space. A high similarity score
does not establish that the stored response answers the current request, or
that the response is factually correct. Choose reuse rules for your workload;
do not treat a cache hit as a correctness certificate.

## Similarity, compatibility and truth

Embedding similarity measures proximity under a particular model and
preprocessing configuration. Questions about related topics can require
different answers. Negation, entity substitutions, numbers, permissions,
output format, missing information and changing context can matter more than
their contribution to a similarity score.

Answer compatibility asks whether the **actual cached response** satisfies the
current request under the application's current task and context. Factual
correctness asks whether the response's claims are true. These are separate
questions: a compatible response can contain an error, describe obsolete
behavior or rely on knowledge that is no longer current. Exact matching does
not establish factual truth either, especially when relevant context changes.

Semantix's structural response validation, namespace isolation, TTL and
revision-aware hit confirmation protect defined cache behavior. They do not
verify an answer's meaning or facts. TTL limits residence time; it cannot
prove that an answer remains current throughout that interval.

## What the completed exploratory evaluation found

An internal, frozen evaluation used **11 requests and four complete cached
Python answers**. All comparisons used the same requests, cached answers and
provisional reference decisions. Both embedding routes used the same frozen
MiniLM retrieval configuration.

| System | Correct reuses | Known incorrect reuses | Compatible paraphrases recovered |
| --- | ---: | ---: | ---: |
| Canonical exact caching | 2 | 0 | 0/2 |
| MiniLM embedding-only retrieval | 2 | 1 | 0/2 |
| MiniLM retrieval plus GPT-4.1 mini verification | 2 | 0 | 0/2 |

There were four requests with a provisionally compatible cached answer: two
exact matches and two paraphrases. All three systems recovered two of four,
giving 50% compatible-request recall and 0% paraphrase recall. Known-label
precision was 100% for exact and guarded reuse, and 66.7% for embedding-only
reuse. No UNCERTAIN reference was accepted as a safe reuse.

Both compatible paraphrases missed the fixed retrieval threshold. The guarded
route produced **zero additional correct reuses over exact caching**. Only
three candidates reached paid verification: GPT-4.1 mini allowed the two exact
matches and rejected a request for safe exclusive file creation whose cached
answer explained checking whether a file exists. Those three decisions are
narrow exploratory observations, not a general verifier accuracy estimate.

The result did not justify implementing the proposed verifier. OpenAI
answer-compatibility verification is **not a production Semantix feature**.
The favorable calibration findings and unsuccessful exploratory findings were
preserved separately; calibration success was not substituted for this outcome.

The references were an independent **AI-assisted assessment**, not independent
human validation. Human review and adjudication remained incomplete.
A deletion/replacement request remained UNCERTAIN; an image-import request
remained AI NO versus authored UNCERTAIN, without silent adjudication. Neither
pair was sent to the verifier. The split was consumed for exploratory testing
and cannot later be described as untouched or human-validated confirmation. The small, curated sample of public question
titles and two synthetic probes is not a representative production workload.

## Retrieval limits what a verifier can assess

A verifier can evaluate only candidates that retrieval supplies. If a useful
answer falls below the threshold or is not selected, rejecting incompatible
candidates cannot recover it. Zero verifier false rejections among the tested
candidates does not imply that useful paraphrases survived the full pipeline.

Lowering a threshold or considering additional candidates may increase recall.
It can also introduce incompatible candidates, more data transfer, greater
verification latency and cost, and new candidate-selection or acceptance
risks. Neither change was validated as a solution by the frozen exploratory
run. There is no claim that semantic matching can never improve reuse, or
that a different model or workload must reproduce these results.

## Implementation guarantees and defect evidence

Similarity-based incorrect reuse and retrieval misses are general semantic
caching risks. A failure to enforce a documented namespace, expiry, policy or
revision guarantee would be an implementation defect and requires separate
reproduction through the documented library behavior.

The completed investigations **did not establish a Semantix library
implementation defect**. This does not establish that defects are impossible.
External runner instrumentation failures were preserved as such and were not
reclassified as library defects without independent reproduction. Storage
integration does not resolve semantic-answer accuracy.

## Policies, namespaces and trusted context

The embedded API's [CachePolicy members](../packages/cache/README.md#contract)
control reads and writes. `CachePolicy.NORMAL` permits reuse;
`CachePolicy.READ_ONLY` can still reuse an incompatible answer;
`CachePolicy.REFRESH` skips reads but can store the newly generated response.
`CachePolicy.BYPASS` and `CachePolicy.PRIVATE` skip both cache reads and writes.
The server HTTP API expresses these choices through
[read, write and private flags](guides/cache-policies.md#read-write-and-private-policies).
PRIVATE is not authentication, authorization, encryption or a guarantee that a
generation provider will not receive the request. Apply your application's
privacy and access controls separately.

A namespace partitions eligible cached responses; it does not authorize a
caller. The embedded application's owner must authenticate and authorize
access before selecting a namespace or returning data. The official server
applies configured role and namespace checks with token authentication enabled;
its local development mode with authentication disabled grants implicit admin
access. Follow the [server authorization guide](operations/deployment.md#namespace-authorization)
when exposing it to other users. Choosing a namespace is not a substitute for
these controls.

Define relevant context using trusted application configuration: tenant or
permission scope, knowledge revision, generation instructions, locale, output
contract and freshness requirements, as applicable. Do not derive trusted
permissions or revision claims solely from untrusted prompt text. Semantix does
not infer changes inside generation callables or automatically decide which
context changes invalidate an answer. See
[context identity and migration](context-identity-and-migration.md) for namespace
and embedding-space responsibilities. Context isolation reduces inappropriate
cross-scope reuse but does not prove compatibility within a scope.

## Practical selection guidance

- Prefer application-owned **canonical exact matching**, with relevant trusted
  context in the key or scope, when requests repeat and there is no demonstrated
  benefit from paraphrase reuse. A similarity threshold of 1 is not an exact-text
  matching mode and should not be used as proof of exact equivalence.
- Consider **conservative semantic reuse** for stable, low-consequence answers
  when workload-specific evidence shows useful paraphrase recall alongside
  acceptable incorrect-reuse behavior. Measure both; rejecting nearly every
  paraphrase is not a useful accuracy improvement.
- **Bypass reuse** when a response depends on live observations, sensitive
  decisions, current permissions, changing account state, precise identifiers
  or constraints that your cache scope cannot reliably represent. Apply
  authorization and any required factual checks to newly generated answers too.

Assess useful correct reuse rather than raw hit rate. Include missed compatible
answers, false rejections, uncertain references, latency and actual costs.
Preserve negative results and distinguish calibration from untouched validation.
The [reuse-quality benchmark guide](../packages/cache/benchmarks/reuse_quality/README.md)
describes separate static benchmark evidence and its limits; it does not turn
this exploratory result into a universal model ranking or validated safeguard.

## Evidence and interpretation

These findings come from a small, controlled exploratory evaluation of
semantic-answer reuse using Python programming questions and previously cached
responses. It compared exact matching, embedding-based retrieval and
embedding-based retrieval with an experimental answer-compatibility verifier.

The results illustrate two distinct limitations: embedding similarity can
retrieve an incompatible answer, and retrieval can miss a compatible answer
before a verifier has an opportunity to assess it.

Reference judgments were AI-assisted and were not independently human-validated.
The limited, curated dataset did not represent production traffic. Interpret the
findings as observed behavior under the tested configuration, not a universal
benchmark, production accuracy guarantee or proof that semantic caching cannot
be improved. This page summarizes those observations; it does not claim public
availability or independent reproduction of the underlying evaluation.

No Semantix library implementation defect was established by this evaluation.
Semantic-answer compatibility and factual correctness remain separate concerns
that applications must evaluate according to their requirements.
