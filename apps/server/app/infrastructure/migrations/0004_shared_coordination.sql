CREATE TABLE semantix.rate_limit_buckets (
    bucket_key TEXT PRIMARY KEY,
    hits BIGINT NOT NULL CHECK (hits >= 0),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX rate_limit_buckets_expiry_idx
    ON semantix.rate_limit_buckets (expires_at);

CREATE TABLE semantix.authentication_attempts (
    client_key TEXT PRIMARY KEY,
    failures SMALLINT NOT NULL CHECK (failures >= 0),
    escalation_stage SMALLINT NOT NULL CHECK (escalation_stage >= 0),
    locked_until TIMESTAMPTZ,
    last_activity TIMESTAMPTZ NOT NULL
);
CREATE INDEX authentication_attempts_activity_idx
    ON semantix.authentication_attempts (last_activity);

CREATE TABLE semantix.cache_threshold (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    threshold DOUBLE PRECISION NOT NULL CHECK (threshold BETWEEN 0 AND 1)
);
