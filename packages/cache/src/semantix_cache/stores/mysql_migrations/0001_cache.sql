CREATE TABLE semantix_schema_migrations (
 version INT NOT NULL PRIMARY KEY,
 owner VARBINARY(64) NOT NULL,
 checksum BINARY(32) NOT NULL,
 state VARBINARY(16) NOT NULL,
 codec INT NOT NULL,
 CONSTRAINT sm_version CHECK (version > 0),
 CONSTRAINT sm_state CHECK (state IN (_binary'INITIALIZING', _binary'READY')),
 CONSTRAINT sm_codec CHECK (codec = 1)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE semantix_bindings (
 binding_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 identity_sha256 BINARY(32) NOT NULL,
 dimensions INT NOT NULL,
 identity_utf8 VARBINARY(4096) NOT NULL,
 capacity INT NOT NULL,
 default_ttl_hex VARBINARY(32) NULL,
 last_revision_us BIGINT NULL,
 access_counter BIGINT NOT NULL DEFAULT 0,
 UNIQUE KEY binding_identity (identity_sha256, dimensions),
 CONSTRAINT sb_dimensions CHECK (dimensions BETWEEN 1 AND 16000),
 CONSTRAINT sb_capacity CHECK (capacity BETWEEN 1 AND 5000),
 CONSTRAINT sb_identity CHECK (OCTET_LENGTH(identity_utf8) BETWEEN 1 AND 4096),
 CONSTRAINT sb_revision CHECK (last_revision_us BETWEEN -62135596800000000 AND 253402300799999999),
 CONSTRAINT sb_access CHECK (access_counter >= 0)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE semantix_entries (
 binding_id BIGINT NOT NULL,
 cache_key VARBINARY(64) NOT NULL,
 namespace VARBINARY(64) NOT NULL,
 revision_us BIGINT NOT NULL,
 expires_at_us BIGINT NULL,
 hit_count BIGINT NOT NULL DEFAULT 0,
 last_accessed_at_us BIGINT NULL,
 access_seq BIGINT NOT NULL,
 vector_blob MEDIUMBLOB NOT NULL,
 PRIMARY KEY (binding_id, cache_key),
 KEY scope_idx (binding_id, namespace, revision_us, cache_key),
 KEY expiry_idx (binding_id, expires_at_us, cache_key),
 KEY lru_idx (binding_id, access_seq, revision_us, cache_key),
 CONSTRAINT se_binding FOREIGN KEY (binding_id) REFERENCES semantix_bindings(binding_id),
 CONSTRAINT se_key CHECK (OCTET_LENGTH(cache_key) = 64),
 CONSTRAINT se_namespace CHECK (OCTET_LENGTH(namespace) BETWEEN 1 AND 64),
 CONSTRAINT se_revision CHECK (revision_us BETWEEN -62135596800000000 AND 253402300799999999),
 CONSTRAINT se_expiry CHECK (expires_at_us BETWEEN -62135596800000000 AND 253402300799999999),
 CONSTRAINT se_accessed CHECK (last_accessed_at_us BETWEEN -62135596800000000 AND 253402300799999999),
 CONSTRAINT se_hits CHECK (hit_count >= 0),
 CONSTRAINT se_access CHECK (access_seq > 0)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE semantix_payloads (
 binding_id BIGINT NOT NULL,
 cache_key VARBINARY(64) NOT NULL,
 payload_blob MEDIUMBLOB NOT NULL,
 PRIMARY KEY (binding_id, cache_key),
 CONSTRAINT sp_entry FOREIGN KEY (binding_id, cache_key) REFERENCES semantix_entries(binding_id, cache_key) ON DELETE CASCADE,
 CONSTRAINT sp_size CHECK (OCTET_LENGTH(payload_blob) BETWEEN 1 AND 1230000)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
