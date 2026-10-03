CREATE TABLE semantix.cache_entries (
    embedding_space TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    cache_key TEXT NOT NULL CHECK (cache_key ~ '^[a-f0-9]{64}$'),
    namespace VARCHAR(64) NOT NULL,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    embedding vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    hit_count BIGINT NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    last_accessed_at TIMESTAMPTZ,
    PRIMARY KEY (embedding_space, cache_key),
    CHECK (vector_dims(embedding) = embedding_dimensions)
);

CREATE INDEX cache_entries_scope_namespace_idx
    ON semantix.cache_entries (embedding_space, namespace);

CREATE INDEX cache_entries_scope_expiry_idx
    ON semantix.cache_entries (embedding_space, expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX cache_entries_scope_recency_idx
    ON semantix.cache_entries (
        embedding_space,
        (COALESCE(last_accessed_at, created_at))
    );

CREATE TABLE semantix.cache_namespace_counters (
    embedding_space TEXT NOT NULL,
    namespace VARCHAR(64) NOT NULL,
    hits BIGINT NOT NULL DEFAULT 0 CHECK (hits >= 0),
    misses BIGINT NOT NULL DEFAULT 0 CHECK (misses >= 0),
    PRIMARY KEY (embedding_space, namespace)
);
