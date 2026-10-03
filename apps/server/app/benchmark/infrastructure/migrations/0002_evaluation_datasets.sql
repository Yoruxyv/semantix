CREATE TABLE semantix.evaluation_datasets (
    dataset_id UUID PRIMARY KEY,
    namespace VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(300),
    source_type TEXT NOT NULL DEFAULT 'imported'
        CHECK (source_type = 'imported'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    digest CHAR(64) NOT NULL CHECK (digest ~ '^[a-f0-9]{64}$'),
    case_count INTEGER NOT NULL CHECK (case_count > 0),
    decoded_bytes INTEGER NOT NULL CHECK (decoded_bytes > 0),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    CHECK (expires_at > created_at)
);

CREATE INDEX evaluation_datasets_namespace_created_idx
    ON semantix.evaluation_datasets (namespace, created_at DESC, dataset_id);

CREATE INDEX evaluation_datasets_expiry_idx
    ON semantix.evaluation_datasets (expires_at, dataset_id);

CREATE TABLE semantix.evaluation_dataset_cases (
    dataset_id UUID NOT NULL
        REFERENCES semantix.evaluation_datasets(dataset_id)
        ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    case_id VARCHAR(100) NOT NULL
        CHECK (case_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'),
    prompt VARCHAR(2000) NOT NULL CHECK (length(prompt) > 0),
    expected_cache_hit BOOLEAN NOT NULL,
    expected_match_case_id VARCHAR(100),
    category VARCHAR(100) NOT NULL CHECK (length(category) > 0),
    note VARCHAR(500),
    PRIMARY KEY (dataset_id, sequence),
    UNIQUE (dataset_id, case_id),
    FOREIGN KEY (dataset_id, expected_match_case_id)
        REFERENCES semantix.evaluation_dataset_cases(dataset_id, case_id)
        ON DELETE CASCADE,
    CHECK (
        expected_cache_hit
        OR expected_match_case_id IS NULL
    )
);

CREATE INDEX evaluation_dataset_cases_dataset_sequence_idx
    ON semantix.evaluation_dataset_cases (dataset_id, sequence);
