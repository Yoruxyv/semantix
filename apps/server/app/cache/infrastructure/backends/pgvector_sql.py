from app.cache.api.schemas import CacheEntrySort

PURGE_EXPIRED = """
DELETE FROM semantix.cache_entries
WHERE embedding_space = $1
  AND expires_at IS NOT NULL
  AND expires_at <= CURRENT_TIMESTAMP
"""

FIND_NEAREST = """
SELECT
    cache_key,
    namespace,
    prompt,
    response,
    embedding::text AS embedding,
    created_at,
    1 - (embedding <=> $4::vector) AS similarity_score
FROM semantix.cache_entries
WHERE embedding_space = $1
  AND embedding_dimensions = $2
  AND namespace = $3
ORDER BY embedding <=> $4::vector, created_at, cache_key
LIMIT 1
"""

PUT_ENTRY = """
INSERT INTO semantix.cache_entries (
    embedding_space,
    embedding_dimensions,
    cache_key,
    namespace,
    prompt,
    response,
    embedding,
    created_at,
    expires_at
)
SELECT
    $1,
    $2,
    $3,
    $4,
    $5,
    $6,
    $7::vector,
    GREATEST(
        $8,
        COALESCE(
            (
                SELECT MAX(created_at) + INTERVAL '1 microsecond'
                FROM semantix.cache_entries
                WHERE embedding_space = $1
            ),
            $8
        )
    ),
    CASE
        WHEN $9::double precision IS NULL THEN NULL
        ELSE CURRENT_TIMESTAMP + ($9 * INTERVAL '1 second')
    END
ON CONFLICT (embedding_space, cache_key) DO UPDATE SET
    embedding_dimensions = EXCLUDED.embedding_dimensions,
    namespace = EXCLUDED.namespace,
    prompt = EXCLUDED.prompt,
    response = EXCLUDED.response,
    embedding = EXCLUDED.embedding,
    created_at = EXCLUDED.created_at,
    expires_at = EXCLUDED.expires_at,
    hit_count = 0,
    last_accessed_at = NULL
"""

DELETE_OVERFLOW = """
DELETE FROM semantix.cache_entries
WHERE (embedding_space, cache_key) IN (
    SELECT embedding_space, cache_key
    FROM semantix.cache_entries
    WHERE embedding_space = $1
    ORDER BY
        COALESCE(last_accessed_at, created_at) DESC,
        created_at DESC,
        cache_key
    OFFSET $2
)
"""

RECORD_HIT = """
WITH updated AS (
    UPDATE semantix.cache_entries
    SET
        hit_count = hit_count + 1,
        last_accessed_at = CURRENT_TIMESTAMP
    WHERE embedding_space = $1
      AND cache_key = $2
      AND created_at = $3
    RETURNING namespace
)
INSERT INTO semantix.cache_namespace_counters (
    embedding_space,
    namespace,
    hits,
    misses
)
SELECT $1, namespace, 1, 0
FROM updated
ON CONFLICT (embedding_space, namespace) DO UPDATE SET
    hits = semantix.cache_namespace_counters.hits + 1
RETURNING 1
"""

RECORD_MISS = """
INSERT INTO semantix.cache_namespace_counters (
    embedding_space,
    namespace,
    hits,
    misses
)
VALUES ($1, $2, 0, 1)
ON CONFLICT (embedding_space, namespace) DO UPDATE SET
    misses = semantix.cache_namespace_counters.misses + 1
"""

COUNT_ENTRIES = """
SELECT COUNT(*)
FROM semantix.cache_entries
WHERE embedding_space = $1
  AND ($2::text IS NULL OR namespace = $2)
  AND (
      $3::text IS NULL
      OR POSITION(LOWER($3) IN LOWER(prompt)) > 0
  )
"""

GET_ENTRY = """
WITH ranked AS (
    SELECT
        cache_key,
        namespace,
        prompt,
        response,
        created_at,
        expires_at,
        hit_count,
        last_accessed_at,
        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(last_accessed_at, created_at) DESC,
                created_at DESC,
                cache_key
        ) AS recency_rank
    FROM semantix.cache_entries
    WHERE embedding_space = $1
)
SELECT *, CURRENT_TIMESTAMP AS observed_at
FROM ranked
WHERE cache_key = $2
  AND ($3::text[] IS NULL OR namespace = ANY($3::text[]))
"""

DELETE_ENTRY = """
DELETE FROM semantix.cache_entries
WHERE embedding_space = $1
  AND cache_key = $2
  AND ($3::text[] IS NULL OR namespace = ANY($3::text[]))
"""

CLEAR_ENTRIES = """
DELETE FROM semantix.cache_entries
WHERE embedding_space = $1
  AND ($2::text IS NULL OR namespace = $2)
"""

CLEAR_COUNTERS = """
DELETE FROM semantix.cache_namespace_counters
WHERE embedding_space = $1
  AND ($2::text IS NULL OR namespace = $2)
"""

COUNTER_TOTALS = """
SELECT
    COALESCE(SUM(hits), 0) AS hits,
    COALESCE(SUM(misses), 0) AS misses
FROM semantix.cache_namespace_counters
WHERE embedding_space = $1
  AND ($2::text IS NULL OR namespace = $2)
"""

ADVISORY_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1))"

_SORT_ORDER: dict[CacheEntrySort, str] = {
    "newest": "created_at DESC, cache_key",
    "oldest": "created_at, cache_key",
    "most_hit": "hit_count DESC, created_at DESC, cache_key",
    "nearest_expiry": ("expires_at ASC NULLS LAST, created_at DESC, cache_key"),
}


def list_entries_query(sort: CacheEntrySort) -> str:
    return f"""
    WITH ranked AS (
        SELECT
            cache_key,
            namespace,
            prompt,
            response,
            created_at,
            expires_at,
            hit_count,
            last_accessed_at,
            ROW_NUMBER() OVER (
                ORDER BY
                    COALESCE(last_accessed_at, created_at) DESC,
                    created_at DESC,
                    cache_key
            ) AS recency_rank
        FROM semantix.cache_entries
        WHERE embedding_space = $1
          AND ($2::text IS NULL OR namespace = $2)
    )
    SELECT *, CURRENT_TIMESTAMP AS observed_at
    FROM ranked
    WHERE (
        $3::text IS NULL
        OR POSITION(LOWER($3) IN LOWER(prompt)) > 0
    )
    ORDER BY {_SORT_ORDER[sort]}
    LIMIT $4 OFFSET $5
    """
