"""SQL statements for durable PostgreSQL evaluation run history."""

RUN_COLUMNS = (
    "run_id",
    "namespace",
    "source_dataset_id",
    "source_dataset_expires_at",
    "terminal_state",
    "accepted_at",
    "started_at",
    "completed_at",
    "expires_at",
    "dataset_id",
    "dataset_source",
    "dataset_schema_version",
    "dataset_version",
    "dataset_digest",
    "dataset_name",
    "dataset_description",
    "dataset_query_count",
    "dataset_expected_hits",
    "dataset_expected_misses",
    "dataset_categories",
    "application_version",
    "embedding_provider_category",
    "generation_provider_category",
    "generation_configuration_fingerprint",
    "comparison_contract_version",
    "embedding_dimensions",
    "embedding_space_fingerprint",
    "normalization_mode",
    "normalization_fingerprint",
    "measured_threshold",
    "evaluation_thresholds",
    "repetitions",
    "reset_cache_before_run",
    "estimated_cost_per_request_usd",
    "estimated_cost_per_1k_tokens_usd",
    "evaluation_timeout_seconds",
    "configuration_fingerprint",
    "threshold_evaluation_mode",
    "total_queries",
    "cache_hits",
    "cache_misses",
    "provider_calls",
    "provider_calls_avoided",
    "hit_rate",
    "average_latency_ms",
    "median_latency_ms",
    "p95_latency_ms",
    "average_cache_hit_latency_ms",
    "average_cache_miss_latency_ms",
    "estimated_latency_saved_ms",
    "estimated_provider_cost_saved_usd",
    "estimated_tokens_saved",
    "true_positive_hits",
    "true_negative_misses",
    "false_positive_hits",
    "false_negative_misses",
    "precision",
    "recall",
    "f1_score",
    "failure_code",
    "safe_failure_detail",
)
RUN_COLUMN_COUNT = len(RUN_COLUMNS)
RUN_SELECT_COLUMNS = ", ".join(RUN_COLUMNS)

PURGE_EXPIRED_HISTORY = """
DELETE FROM semantix.evaluation_runs
WHERE run_id IN (
    SELECT run_id
    FROM semantix.evaluation_runs
    WHERE expires_at <= CURRENT_TIMESTAMP
      AND ($1::text IS NULL OR namespace = $1)
    ORDER BY expires_at, run_id
    LIMIT $2
)
"""

PRUNE_OLDEST_ACTIVE_HISTORY = """
DELETE FROM semantix.evaluation_runs
WHERE run_id IN (
    SELECT run_id
    FROM semantix.evaluation_runs
    WHERE namespace = $1
      AND expires_at > CURRENT_TIMESTAMP
    ORDER BY completed_at ASC, run_id ASC
    LIMIT $2
)
"""

ACQUIRE_NAMESPACE_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"

COUNT_ACTIVE_NAMESPACE_RUNS = """
SELECT COUNT(*)
FROM semantix.evaluation_runs
WHERE namespace = $1
  AND expires_at > CURRENT_TIMESTAMP
"""

COUNT_ACTIVE_RUNS = """
SELECT COUNT(*)
FROM semantix.evaluation_runs
WHERE expires_at > CURRENT_TIMESTAMP
  AND ($1::text IS NULL OR namespace = $1)
"""

INSERT_RUN = (
    "INSERT INTO semantix.evaluation_runs ("
    + ", ".join(RUN_COLUMNS)
    + ") VALUES ("
    + ", ".join(f"${index}" for index in range(1, len(RUN_COLUMNS) + 1))
    + ")"
)

INSERT_THRESHOLD = """
INSERT INTO semantix.evaluation_run_thresholds (
    run_id,
    sequence,
    threshold,
    result_kind,
    hit_rate,
    precision,
    recall,
    f1_score,
    average_latency_ms,
    provider_calls_avoided,
    true_positive_hits,
    true_negative_misses,
    false_positive_hits,
    false_negative_misses
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7,
    $8, $9, $10, $11, $12, $13, $14
)
"""

LIST_ACTIVE_RUNS = f"""
SELECT {RUN_SELECT_COLUMNS}
FROM semantix.evaluation_runs
WHERE expires_at > CURRENT_TIMESTAMP
  AND ($1::text IS NULL OR namespace = $1)
ORDER BY completed_at DESC, run_id ASC
LIMIT $2
OFFSET $3
"""

GET_ACTIVE_RUN = f"""
SELECT {RUN_SELECT_COLUMNS}
FROM semantix.evaluation_runs
WHERE run_id = $1
  AND expires_at > CURRENT_TIMESTAMP
  AND (
      $2::text[] IS NULL
      OR namespace = ANY($2::text[])
  )
"""

GET_RUN_THRESHOLDS = """
SELECT
    sequence,
    threshold,
    result_kind,
    hit_rate,
    precision,
    recall,
    f1_score,
    average_latency_ms,
    provider_calls_avoided,
    true_positive_hits,
    true_negative_misses,
    false_positive_hits,
    false_negative_misses
FROM semantix.evaluation_run_thresholds
WHERE run_id = $1
ORDER BY sequence
"""

DELETE_ACTIVE_RUN = """
DELETE FROM semantix.evaluation_runs
WHERE run_id = $1
  AND namespace = $2
  AND expires_at > CURRENT_TIMESTAMP
RETURNING run_id
"""

READINESS_QUERY = "SELECT COUNT(*) FROM semantix.evaluation_runs WHERE FALSE"
