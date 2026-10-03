# Optional prompt typo normalization

Semantix can correct common English spelling mistakes and accidental word
splits before creating the embedding used for semantic-cache matching. The
feature is disabled by default because automatic correction can change
unfamiliar names or domain-specific terms.

## Configuration

Set these values in `apps/server/.env`:

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

Restart the backend after changing either setting. Clear existing cache entries
when enabling, disabling, or changing correction distance so every stored
embedding uses the same prompt-processing behavior.

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
