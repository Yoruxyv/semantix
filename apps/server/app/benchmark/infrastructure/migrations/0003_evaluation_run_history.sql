CREATE TABLE semantix.evaluation_runs (
    run_id UUID PRIMARY KEY,
    namespace VARCHAR(64) NOT NULL,

    source_dataset_id UUID
        REFERENCES semantix.evaluation_datasets(dataset_id)
        ON DELETE CASCADE,
    source_dataset_expires_at TIMESTAMPTZ,

    terminal_state TEXT NOT NULL
        CHECK (terminal_state IN ('completed', 'failed', 'timed_out')),

    accepted_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,

    dataset_id VARCHAR(100) NOT NULL,
    dataset_source TEXT NOT NULL
        CHECK (dataset_source IN ('builtin', 'persisted')),
    dataset_schema_version INTEGER,
    dataset_version VARCHAR(50) NOT NULL,
    dataset_digest CHAR(64) NOT NULL
        CHECK (dataset_digest ~ '^[a-f0-9]{64}$'),
    dataset_name VARCHAR(100) NOT NULL,
    dataset_description VARCHAR(300) NOT NULL,
    dataset_query_count INTEGER NOT NULL CHECK (dataset_query_count > 0),
    dataset_expected_hits INTEGER NOT NULL CHECK (dataset_expected_hits >= 0),
    dataset_expected_misses INTEGER NOT NULL CHECK (dataset_expected_misses >= 0),
    dataset_categories TEXT[] NOT NULL,

    application_version VARCHAR(50) NOT NULL,
    embedding_provider_category VARCHAR(50) NOT NULL,
    generation_provider_category VARCHAR(50) NOT NULL,
    generation_configuration_fingerprint CHAR(64) NOT NULL
        CHECK (generation_configuration_fingerprint ~ '^[a-f0-9]{64}$'),
    comparison_contract_version INTEGER NOT NULL
        CHECK (comparison_contract_version = 1),

    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    embedding_space_fingerprint CHAR(64) NOT NULL
        CHECK (embedding_space_fingerprint ~ '^[a-f0-9]{64}$'),

    normalization_mode TEXT NOT NULL
        CHECK (normalization_mode IN ('identity', 'typo_correction')),
    normalization_fingerprint CHAR(64) NOT NULL
        CHECK (normalization_fingerprint ~ '^[a-f0-9]{64}$'),

    measured_threshold DOUBLE PRECISION NOT NULL
        CHECK (measured_threshold >= 0 AND measured_threshold <= 1),
    evaluation_thresholds DOUBLE PRECISION[] NOT NULL,
    repetitions INTEGER NOT NULL CHECK (repetitions >= 1 AND repetitions <= 5),
    reset_cache_before_run BOOLEAN NOT NULL,

    estimated_cost_per_request_usd DOUBLE PRECISION NOT NULL
        CHECK (
            estimated_cost_per_request_usd >= 0
            AND estimated_cost_per_request_usd <= 100
        ),
    estimated_cost_per_1k_tokens_usd DOUBLE PRECISION NOT NULL
        CHECK (
            estimated_cost_per_1k_tokens_usd >= 0
            AND estimated_cost_per_1k_tokens_usd <= 100
        ),
    evaluation_timeout_seconds DOUBLE PRECISION NOT NULL
        CHECK (
            evaluation_timeout_seconds > 0
            AND evaluation_timeout_seconds <= 3600
        ),
    configuration_fingerprint CHAR(64) NOT NULL
        CHECK (configuration_fingerprint ~ '^[a-f0-9]{64}$'),

    threshold_evaluation_mode TEXT NOT NULL
        CHECK (threshold_evaluation_mode = 'frozen_candidate_projection'),

    total_queries INTEGER CHECK (total_queries > 0),
    cache_hits INTEGER CHECK (cache_hits >= 0),
    cache_misses INTEGER CHECK (cache_misses >= 0),
    provider_calls INTEGER CHECK (provider_calls >= 0),
    provider_calls_avoided INTEGER CHECK (provider_calls_avoided >= 0),

    hit_rate DOUBLE PRECISION
        CHECK (hit_rate >= 0 AND hit_rate <= 1),
    average_latency_ms DOUBLE PRECISION CHECK (average_latency_ms >= 0),
    median_latency_ms DOUBLE PRECISION CHECK (median_latency_ms >= 0),
    p95_latency_ms DOUBLE PRECISION CHECK (p95_latency_ms >= 0),
    average_cache_hit_latency_ms DOUBLE PRECISION
        CHECK (average_cache_hit_latency_ms >= 0),
    average_cache_miss_latency_ms DOUBLE PRECISION
        CHECK (average_cache_miss_latency_ms >= 0),

    estimated_latency_saved_ms DOUBLE PRECISION
        CHECK (estimated_latency_saved_ms >= 0),
    estimated_provider_cost_saved_usd DOUBLE PRECISION
        CHECK (estimated_provider_cost_saved_usd >= 0),
    estimated_tokens_saved INTEGER CHECK (estimated_tokens_saved >= 0),

    true_positive_hits INTEGER CHECK (true_positive_hits >= 0),
    true_negative_misses INTEGER CHECK (true_negative_misses >= 0),
    false_positive_hits INTEGER CHECK (false_positive_hits >= 0),
    false_negative_misses INTEGER CHECK (false_negative_misses >= 0),

    precision DOUBLE PRECISION
        CHECK (precision >= 0 AND precision <= 1),
    recall DOUBLE PRECISION
        CHECK (recall >= 0 AND recall <= 1),
    f1_score DOUBLE PRECISION
        CHECK (f1_score >= 0 AND f1_score <= 1),

    failure_code VARCHAR(100),
    safe_failure_detail VARCHAR(300),

    CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    CHECK (dataset_expected_hits + dataset_expected_misses = dataset_query_count),
    CHECK (cardinality(dataset_categories) > 0),
    CHECK (
        cardinality(evaluation_thresholds) >= 2
        AND cardinality(evaluation_thresholds) <= 15
    ),

    CHECK (
        accepted_at <= started_at
        AND started_at <= completed_at
        AND completed_at < expires_at
    ),

    CHECK (
        (
            dataset_source = 'builtin'
            AND source_dataset_id IS NULL
            AND source_dataset_expires_at IS NULL
            AND dataset_schema_version IS NULL
        )
        OR
        (
            dataset_source = 'persisted'
            AND source_dataset_id IS NOT NULL
            AND source_dataset_expires_at IS NOT NULL
            AND dataset_schema_version = 1
            AND expires_at <= source_dataset_expires_at
        )
    ),

    CHECK (
        (
            terminal_state = 'completed'
            AND total_queries IS NOT NULL
            AND failure_code IS NULL
            AND safe_failure_detail IS NULL
        )
        OR
        (
            terminal_state IN ('failed', 'timed_out')
            AND total_queries IS NULL
            AND failure_code IS NOT NULL
        )
    )
);

CREATE INDEX evaluation_runs_namespace_completed_idx
    ON semantix.evaluation_runs (
        namespace,
        completed_at DESC,
        run_id
    );

CREATE INDEX evaluation_runs_expiry_idx
    ON semantix.evaluation_runs (
        expires_at,
        run_id
    );

CREATE INDEX evaluation_runs_source_dataset_idx
    ON semantix.evaluation_runs (source_dataset_id)
    WHERE source_dataset_id IS NOT NULL;


CREATE TABLE semantix.evaluation_run_thresholds (
    run_id UUID NOT NULL
        REFERENCES semantix.evaluation_runs(run_id)
        ON DELETE CASCADE,

    sequence INTEGER NOT NULL CHECK (sequence > 0),

    threshold DOUBLE PRECISION NOT NULL
        CHECK (threshold >= 0 AND threshold <= 1),

    result_kind TEXT NOT NULL
        CHECK (result_kind IN ('measured', 'projected')),

    hit_rate DOUBLE PRECISION NOT NULL
        CHECK (hit_rate >= 0 AND hit_rate <= 1),

    precision DOUBLE PRECISION NOT NULL
        CHECK (precision >= 0 AND precision <= 1),

    recall DOUBLE PRECISION NOT NULL
        CHECK (recall >= 0 AND recall <= 1),

    f1_score DOUBLE PRECISION NOT NULL
        CHECK (f1_score >= 0 AND f1_score <= 1),

    average_latency_ms DOUBLE PRECISION NOT NULL
        CHECK (average_latency_ms >= 0),

    provider_calls_avoided INTEGER NOT NULL
        CHECK (provider_calls_avoided >= 0),

    true_positive_hits INTEGER NOT NULL
        CHECK (true_positive_hits >= 0),

    true_negative_misses INTEGER NOT NULL
        CHECK (true_negative_misses >= 0),

    false_positive_hits INTEGER NOT NULL
        CHECK (false_positive_hits >= 0),

    false_negative_misses INTEGER NOT NULL
        CHECK (false_negative_misses >= 0),

    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, threshold),

    CHECK (
        true_positive_hits + false_positive_hits
        = provider_calls_avoided
    )
);

CREATE UNIQUE INDEX evaluation_run_thresholds_measured_idx
    ON semantix.evaluation_run_thresholds (run_id)
    WHERE result_kind = 'measured';