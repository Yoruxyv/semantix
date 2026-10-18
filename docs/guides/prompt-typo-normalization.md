# Optional prompt typo normalization

The optional Semantix server can correct common English spelling mistakes and
accidental word splits before creating the embedding used for semantic-cache matching. The
feature is disabled by default because automatic correction can change
unfamiliar names or domain-specific terms.

## Configuration

For a directly run backend or development Compose, set these values in
`apps/server/.env`:

```env
PROMPT_TYPO_CORRECTION_ENABLED=true
PROMPT_TYPO_MAX_EDIT_DISTANCE=2
```

The edit distance accepts values from `0` through `3`. A larger value permits
more aggressive corrections. The default of `2` handles examples such as:

```text
semntic caching -> semantic caching
cahcing         -> caching
ex plain        -> explain
```

These are startup settings; the dashboard's admin diagnostics is read-only.
Production Compose receives them through its explicit environment mapping, not the
development `.env` file. Restart a directly run backend or recreate affected
containers after configuration changes; a container restart alone does not update
its configured environment. See [deployment](../operations/deployment.md).

Changing preprocessing may make retained embeddings incompatible. Plan a coordinated
transition across replicas: drain active work, preserve recoverable data, choose
compatible isolated storage or an explicitly reviewed migration, verify the new
configuration and define rollback before restoring traffic. A diagnostic fingerprint
alone does not isolate old vectors. Deletion is a separate authorized decision, not
an automatic configuration step. See [server storage](platform-storage.md) and
[preprocessing identity and migration](../embedded/context-identity-and-migration.md#embedding-revision-and-preprocessing).

## Behavior

Correction applies only to the text passed to the embedding provider for cache
lookup and storage. Semantix still:

- sends the original prompt to the generation provider on a cache miss;
- stores and displays the original prompt in the cache inspector;
- reports the original cached prompt as the matched prompt.

This keeps generated responses faithful to user input while making harmless
typo variants more likely to produce compatible cache embeddings. Benchmark
runs use the same configured normalizer as regular queries. SymSpell may also
standardize punctuation and whitespace in the matching text; this does not
alter the original prompt.

When Unicode lowercasing changes SymSpell's token count, such as for `İstanbul`,
Semantix uses the entire supplied prompt unchanged as matching text instead of
passing misaligned token lists to compound correction. Lookup and newly computed
write embeddings use the same deterministic fallback; other typos in that prompt
are left uncorrected. Token-aligned inputs keep the existing correction behavior,
including its limitations for non-English text. This guard adds no case folding,
Unicode canonicalization, or answer-compatibility guarantee, and it does not clear
retained entries. Deploy the same preprocessing behavior across replicas and follow
the existing cache-transition precautions if retained embeddings used a different
behavior.

The normalizer uses the English frequency dictionary bundled with `symspellpy`.
It never downloads dictionary data at runtime. When correction is enabled,
Semantix loads the dictionary during application startup and refuses to start
if the dictionary is unavailable or invalid. When correction is disabled, no
dictionary is loaded.

Semantix adds a small protected vocabulary for its common project terms,
including `Semantix`, `pgvector`, `namespace`, `OpenAI`, and `FastAPI`.
Unfamiliar proper names and specialized vocabulary can still be corrected
incorrectly, so leave the feature disabled when exact spelling preservation is
more important than typo tolerance.

## Capitalization and matching

The current server uses SymSpell's `transfer_casing=True`, generally retaining the
input capitalization. It does not implement case-insensitive matching. At edit
distance 2 with the bundled dictionary, the matching texts are:

| Application prompt | Matching text |
| --- | --- |
| `Explain semantic caching` | `Explain semantic caching` |
| `explain semantic caching` | `explain semantic caching` |
| `expln semantic caching` | `explain semantic caching` |
| `explainn semantic caching` | `explain semantic caching` |

The first two inputs may produce different embeddings and similarity scores.
Capitalization does not always cause a miss, and spelling correction does not
guarantee a hit. Reuse still requires the configured similarity threshold and other
eligibility checks, including namespace, compatible space, expiry and live revision.
Neither correction nor similarity proves answer compatibility. Dictionary behavior
can still change unfamiliar names, identifiers or non-English text. Enabled distance
0 still uses compound preprocessing; it is not equivalent to disabling correction.

## Standalone package and custom preprocessing

The independent `semantix-cache` package provides a synchronous `prompt_normalizer`
callable on `AsyncSemanticCache`. Installing the package does not install SymSpell,
enable these server settings or include the server's protected vocabulary. The hook
changes embedding text only; generation and cache entries retain the canonical
application prompt. See the [package contract](../../packages/cache/README.md#matching-text-preprocessing).

Applications may supply their own evaluated casing, whitespace or vocabulary
transforms through that hook. These are custom implementations, not built-in modes.
Do not blindly remove punctuation, stop words, negation, numbers, identifiers, tenant
or permission context, system instructions or conversation history: they can change
which answer is appropriate. Keep required context in the application request and
its cache identity. Make preprocessing deterministic, version it with the embedding
space and use compatible isolated storage when changing it, following the linked
identity/migration guide rather than relabeling existing vectors.
