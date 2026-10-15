CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    checksum TEXT NOT NULL
) STRICT;
CREATE TABLE binding_state (
    binding_id INTEGER PRIMARY KEY,
    identity TEXT NOT NULL COLLATE BINARY,
    dimensions INTEGER NOT NULL CHECK(dimensions BETWEEN 1 AND 16000),
    capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 5000 AND capacity * dimensions * 8 <= 67108864),
    default_ttl_hex TEXT,
    last_revision_us INTEGER CHECK(last_revision_us BETWEEN -62135596800000000 AND 253402300799999999),
    access_counter INTEGER NOT NULL CHECK(access_counter >= 0),
    UNIQUE(identity, dimensions)
) STRICT;
CREATE TABLE cache_entries (
    binding_id INTEGER NOT NULL REFERENCES binding_state(binding_id),
    cache_key TEXT NOT NULL COLLATE BINARY CHECK(length(cache_key) = 64),
    namespace TEXT NOT NULL COLLATE BINARY CHECK(length(namespace) BETWEEN 1 AND 64),
    vector_blob BLOB NOT NULL,
    revision_us INTEGER NOT NULL CHECK(revision_us BETWEEN -62135596800000000 AND 253402300799999999),
    expires_at_us INTEGER CHECK(expires_at_us BETWEEN -62135596800000000 AND 253402300799999999),
    hit_count INTEGER NOT NULL CHECK(hit_count >= 0),
    last_accessed_at_us INTEGER CHECK(last_accessed_at_us BETWEEN -62135596800000000 AND 253402300799999999),
    access_seq INTEGER NOT NULL CHECK(access_seq > 0),
    PRIMARY KEY(binding_id, cache_key)
) STRICT;
CREATE TABLE cache_payloads (
    binding_id INTEGER NOT NULL,
    cache_key TEXT NOT NULL COLLATE BINARY,
    payload_blob BLOB NOT NULL,
    PRIMARY KEY(binding_id, cache_key),
    FOREIGN KEY(binding_id, cache_key) REFERENCES cache_entries(binding_id, cache_key) ON DELETE CASCADE
) STRICT;
CREATE INDEX scope_idx ON cache_entries(binding_id, namespace, revision_us, cache_key);
CREATE INDEX lru_idx ON cache_entries(binding_id, access_seq, revision_us, cache_key);
CREATE INDEX expiry_idx ON cache_entries(binding_id, expires_at_us);
