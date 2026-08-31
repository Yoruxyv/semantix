# Cache policies

Semantix exposes cache behavior explicitly so callers can evaluate reuse,
privacy, lifetime, isolation, and threshold trade-offs.

## Semantic lookup

For a cache-enabled read:

1. the configured normalizer prepares matching text;
2. the embedding provider creates a vector;
3. `EmbeddingService` validates dimensions and finite values, then normalizes
   the vector;
4. the selected backend removes expired entries;
5. the backend searches compatible vectors in the request namespace;
6. the nearest response is returned only when its cosine similarity meets the
   active threshold.

The generation provider receives the original prompt only on a miss. The
original prompt is stored and displayed even when optional typo normalization
changes the matching text.

## Similarity threshold

`SIMILARITY_THRESHOLD` sets the startup value between `0` and `1`. The active
threshold can be previewed in the Monitor workspace and applied through the
cache threshold API. Applying it from Monitor requires an administrator with
wildcard namespace access; other authorized users retain the local preview.

- Higher thresholds reduce reuse and generally lower false-positive risk.
- Lower thresholds increase reuse and generally raise false-positive risk.

No universal value is safe for every model or dataset. Use the controlled
[Benchmark](benchmarking.md) workspace before changing a threshold for a new
embedding model or workload.

The similarity trace places scored queries on the full `-1.0` to `1.0`
cosine-similarity domain. Vertical position only separates overlapping points.
Cache thresholds remain between `0.0` and `1.0`, so negative scores are always
projected misses. Previewing a threshold changes projected colors; it does not
change backend decisions until applied.

## TTL and LRU

`CACHE_TTL_SECONDS` controls entry lifetime. Expired entries are removed before
cache operations and inspector results.

API and Python SDK callers may request `cache_ttl_seconds` from `1` through
`31,536,000` on Normal or Refresh requests. The server remains authoritative:
a finite `CACHE_TTL_SECONDS` caps the request, while a server configured with
no default TTL uses the requested value. Omission or `null` keeps the configured
default and never means no expiry. Cache hits do not extend an entry's lifetime;
a Refresh write replaces the entry and starts its effective TTL at that write.

Read only, Bypass, and Private requests cannot write, so supplying a request TTL
with those modes returns HTTP `422` before provider work. Concurrent misses may
coalesce only when their effective TTL and other cache-policy fields match.
Different TTLs still write the existing namespace-scoped key, so the normal
replacement semantics apply; TTL is not part of the persistent cache key.

`MAX_CACHE_SIZE` bounds entries in the active embedding space. When insertion
would exceed that limit, the least recently used entry is evicted. Reads update
hit count and recency.

The memory backend resets all entries and counters when its process restarts.
The pgvector backend persists entries, counters, hit counts, and access times.
See [pgvector](pgvector.md).

## Namespaces

Every entry and cache key belongs to one namespace. Requests without an
explicit namespace use `default`. Lookup never compares entries across
namespaces.

Namespace values:

- contain 1 through 64 characters;
- allow letters, numbers, `.`, `_`, `:`, and `-`.

Statistics and clearing can target one namespace. Capacity remains global to
the active embedding space, so heavy writes in one namespace can evict an LRU
entry from another namespace.

Monitor preselects a sole authorized namespace. Principals with multiple
concrete namespaces must choose one, while wildcard principals enter one valid
concrete namespace explicitly. The `*` authorization marker is never sent as a
query namespace.

## Read, write, and private policies

Query requests support:

| Input                       | Effect                        |
| --------------------------- | ----------------------------- |
| `cache_enabled=false`       | Disable both reads and writes |
| `cache_read_enabled=false`  | Skip lookup                   |
| `cache_write_enabled=false` | Do not store generated output |
| `private=true`              | Disable reads and writes      |

`cache_enabled=false` overrides the granular flags. `private=true` also forces
both operations off. Semantix does not attempt automatic secret detection;
callers must mark sensitive prompts private.

Useful combinations:

- read disabled, write enabled: force provider generation and refresh storage;
- read enabled, write disabled: reuse an existing answer without storing a new
  one;
- both disabled: bypass the semantic cache entirely.

Monitor exposes these combinations as mutually exclusive Normal, Read only,
Refresh and write, Bypass cache, and Private request modes. The effective
namespace and mode are shown before submission and with the result. Successful
non-private queries add that safe context to the bounded in-memory trace.
Private queries are omitted from the trace entirely, so their prompt, response,
matched content, and cache key do not enter trace state.

Provider failures and empty provider responses are never cached.

## Cache poisoning and integrity

Namespace filtering is an integrity boundary; similarity is not. Memory and
pgvector lookup select candidates only from the authorized request namespace,
so an equal embedding in another namespace cannot win. Exact cache keys are
also namespace-scoped, but exact-key hashing does not govern semantic lookup.

Inside one namespace, a materially different prompt can reuse an incorrect
response whenever its embedding meets the active threshold. This is an
inherent risk of similarity-only reuse, including entity substitutions,
numeric changes, negation, and prompts that influence a generated response
before it is cached. Structural provider-response validation does not make the
response semantically trusted.

Evaluate adversarial miss cases and benign paraphrase hit controls for the
configured embedding model and threshold. Restrict Operator tokens to the
namespaces they need, use Private or Bypass cache for content that must not be
reused, and inspect or clear suspect entries explicitly. See the complete
[poisoning threat model](../../SECURITY.md#semantic-cache-poisoning-threat-model).

## Request coalescing

Concurrent requests with the same namespace, prompt, and effective cache
policy share one in-flight resolution. A leader performs lookup, generation,
and storage; followers await it.

The in-flight registry lock protects only task registration and removal. It is
not held during embedding, cache, or provider I/O. Success and failure both
remove the task so later requests can use the cache or retry.

Coalescing is process-local. Multiple backend replicas require an external
coordination design if duplicate provider calls across replicas must also be
prevented.

## Embedding compatibility

Provider, model, and dimensions define an embedding space. Vectors from
different spaces must never be compared.

- Memory storage naturally starts a new space after restart.
- Pgvector partitions stored rows by embedding provider, model, and dimensions.

Changing prompt normalization also changes matching behavior. Clear active
cache entries when enabling, disabling, or changing typo correction so stored
and incoming embeddings use one policy. See
[Prompt typo normalization](prompt-typo-normalization.md).

## Inspector and aggregate counters

The Cache workspace exposes safe metadata:

- namespace and cache key;
- original prompt and truncated response preview;
- creation and expiry;
- remaining TTL;
- entry hits and last access;
- LRU recency rank.

Deleting one entry does not rewrite historical aggregate hit/miss counters.
Clearing the cache removes entries and resets those counters. Embeddings and
full responses are never rendered by the deep-linkable entry-detail page.
The existing single-entry endpoint can return the complete response only after
an explicit user request from the Cache Inspector; its safe Markdown renderer
does not execute raw HTML.

`/cache/entries/{cache_key}` is a best-effort operational link, not a durable
record. It can stop resolving after expiry, LRU eviction, deletion, restart, or
an embedding-space change. Missing and unauthorized entries intentionally use
the same message. Evaluation cache keys remain isolated evidence and are not
linked to this live-cache route.
Monitor renders “Open matched live cache entry” only for a true live hit with a
server-returned `matched_cache_key`; misses never receive the link.
