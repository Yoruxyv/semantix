CREATE TABLE {ledger} (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE {bindings} (
    embedding_space TEXT NOT NULL CHECK (length(embedding_space) BETWEEN 1 AND 1024),
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions BETWEEN 1 AND 16000),
    revision TIMESTAMPTZ,
    access_order BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (embedding_space, embedding_dimensions)
);
CREATE TABLE {entries} (
    embedding_space TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL,
    cache_key TEXT NOT NULL CHECK (cache_key ~ '^[a-f0-9]{{64}}$'),
    namespace VARCHAR(64) NOT NULL CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{{0,63}}$'),
    prompt TEXT NOT NULL CHECK (length(prompt) BETWEEN 1 AND 2000),
    response TEXT NOT NULL CHECK (length(response) BETWEEN 1 AND 100000),
    embedding {vector} NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    hit_count BIGINT NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    last_accessed_at TIMESTAMPTZ,
    access_order BIGINT NOT NULL,
    PRIMARY KEY (embedding_space, embedding_dimensions, cache_key),
    FOREIGN KEY (embedding_space, embedding_dimensions)
        REFERENCES {bindings} (embedding_space, embedding_dimensions),
    CHECK ({vector_dims}(embedding) = embedding_dimensions)
);
CREATE INDEX {scope_index} ON {entries} (embedding_space, embedding_dimensions, namespace);
COMMENT ON TABLE {ledger} IS 'semantix-cache:pgvector:v1';
COMMENT ON TABLE {bindings} IS 'semantix-cache:pgvector:v1';
COMMENT ON TABLE {entries} IS 'semantix-cache:pgvector:v1';
