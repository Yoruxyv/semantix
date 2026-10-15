CREATE DEFINER='semantix_schema_verifier'@'localhost' PROCEDURE semantix_verify()
NOT DETERMINISTIC
READS SQL DATA
SQL SECURITY DEFINER
COMMENT 'semantix-cache:mysql:verify:v2'
SELECT 2,COALESCE((SELECT COUNT(*)=4 AND COALESCE(SUM(JSON_ARRAY(TABLE_NAME,TABLE_TYPE,ENGINE,ROW_FORMAT,TABLE_COLLATION,CREATE_OPTIONS) IN (CAST('["semantix_bindings", "BASE TABLE", "InnoDB", "Dynamic", "utf8mb4_bin", "row_format=DYNAMIC"]' AS JSON),
   CAST('["semantix_entries", "BASE TABLE", "InnoDB", "Dynamic", "utf8mb4_bin", "row_format=DYNAMIC"]' AS JSON),
   CAST('["semantix_payloads", "BASE TABLE", "InnoDB", "Dynamic", "utf8mb4_bin", "row_format=DYNAMIC"]' AS JSON),
   CAST('["semantix_schema_migrations", "BASE TABLE", "InnoDB", "Dynamic", "utf8mb4_bin", "row_format=DYNAMIC"]' AS JSON))),0)=4 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=25 AND COALESCE(SUM(JSON_ARRAY(TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,CHARACTER_SET_NAME,COLLATION_NAME,GENERATION_EXPRESSION) IN (CAST('["semantix_bindings", "binding_id", 1, "bigint", "NO", null, "auto_increment", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "identity_sha256", 2, "binary(32)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "dimensions", 3, "int", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "identity_utf8", 4, "varbinary(4096)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "capacity", 5, "int", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "default_ttl_hex", 6, "varbinary(32)", "YES", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "last_revision_us", 7, "bigint", "YES", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_bindings", "access_counter", 8, "bigint", "NO", "0", "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "binding_id", 1, "bigint", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "cache_key", 2, "varbinary(64)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "namespace", 3, "varbinary(64)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "revision_us", 4, "bigint", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "expires_at_us", 5, "bigint", "YES", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "hit_count", 6, "bigint", "NO", "0", "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "last_accessed_at_us", 7, "bigint", "YES", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "access_seq", 8, "bigint", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_entries", "vector_blob", 9, "mediumblob", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_payloads", "binding_id", 1, "bigint", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_payloads", "cache_key", 2, "varbinary(64)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_payloads", "payload_blob", 3, "mediumblob", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_schema_migrations", "version", 1, "int", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_schema_migrations", "owner", 2, "varbinary(64)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_schema_migrations", "checksum", 3, "binary(32)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_schema_migrations", "state", 4, "varbinary(16)", "NO", null, "", null, null, ""]' AS JSON),
   CAST('["semantix_schema_migrations", "codec", 5, "int", "NO", null, "", null, null, ""]' AS JSON))),0)=25 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=19 AND COALESCE(SUM(JSON_ARRAY(TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,COLLATION,SUB_PART,INDEX_TYPE,NULLABLE,EXPRESSION,IS_VISIBLE) IN (CAST('["semantix_bindings", "binding_identity", 0, 1, "identity_sha256", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_bindings", "binding_identity", 0, 2, "dimensions", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_bindings", "PRIMARY", 0, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "expiry_idx", 1, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "expiry_idx", 1, 2, "expires_at_us", "A", null, "BTREE", "YES", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "expiry_idx", 1, 3, "cache_key", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "lru_idx", 1, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "lru_idx", 1, 2, "access_seq", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "lru_idx", 1, 3, "revision_us", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "lru_idx", 1, 4, "cache_key", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "PRIMARY", 0, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "PRIMARY", 0, 2, "cache_key", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "scope_idx", 1, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "scope_idx", 1, 2, "namespace", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "scope_idx", 1, 3, "revision_us", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_entries", "scope_idx", 1, 4, "cache_key", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_payloads", "PRIMARY", 0, 1, "binding_id", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_payloads", "PRIMARY", 0, 2, "cache_key", "A", null, "BTREE", "", null, "YES"]' AS JSON),
   CAST('["semantix_schema_migrations", "PRIMARY", 0, 1, "version", "A", null, "BTREE", "", null, "YES"]' AS JSON))),0)=19 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=23 AND COALESCE(SUM(JSON_ARRAY(tc.TABLE_NAME,tc.CONSTRAINT_NAME,tc.CONSTRAINT_TYPE,tc.ENFORCED,cc.CHECK_CLAUSE) IN (CAST('["semantix_bindings", "binding_identity", "UNIQUE", "YES", null]' AS JSON),
   CAST('["semantix_bindings", "PRIMARY", "PRIMARY KEY", "YES", null]' AS JSON),
   CAST('["semantix_bindings", "sb_access", "CHECK", "YES", "(`access_counter` >= 0)"]' AS JSON),
   CAST('["semantix_bindings", "sb_capacity", "CHECK", "YES", "(`capacity` between 1 and 5000)"]' AS JSON),
   CAST('["semantix_bindings", "sb_dimensions", "CHECK", "YES", "(`dimensions` between 1 and 16000)"]' AS JSON),
   CAST('["semantix_bindings", "sb_identity", "CHECK", "YES", "(length(`identity_utf8`) between 1 and 4096)"]' AS JSON),
   CAST('["semantix_bindings", "sb_revision", "CHECK", "YES", "(`last_revision_us` between -(62135596800000000) and 253402300799999999)"]' AS JSON),
   CAST('["semantix_entries", "PRIMARY", "PRIMARY KEY", "YES", null]' AS JSON),
   CAST('["semantix_entries", "se_access", "CHECK", "YES", "(`access_seq` > 0)"]' AS JSON),
   CAST('["semantix_entries", "se_accessed", "CHECK", "YES", "(`last_accessed_at_us` between -(62135596800000000) and 253402300799999999)"]' AS JSON),
   CAST('["semantix_entries", "se_binding", "FOREIGN KEY", "YES", null]' AS JSON),
   CAST('["semantix_entries", "se_expiry", "CHECK", "YES", "(`expires_at_us` between -(62135596800000000) and 253402300799999999)"]' AS JSON),
   CAST('["semantix_entries", "se_hits", "CHECK", "YES", "(`hit_count` >= 0)"]' AS JSON),
   CAST('["semantix_entries", "se_key", "CHECK", "YES", "(length(`cache_key`) = 64)"]' AS JSON),
   CAST('["semantix_entries", "se_namespace", "CHECK", "YES", "(length(`namespace`) between 1 and 64)"]' AS JSON),
   CAST('["semantix_entries", "se_revision", "CHECK", "YES", "(`revision_us` between -(62135596800000000) and 253402300799999999)"]' AS JSON),
   CAST('["semantix_payloads", "PRIMARY", "PRIMARY KEY", "YES", null]' AS JSON),
   CAST('["semantix_payloads", "sp_entry", "FOREIGN KEY", "YES", null]' AS JSON),
   CAST('["semantix_payloads", "sp_size", "CHECK", "YES", "(length(`payload_blob`) between 1 and 1230000)"]' AS JSON),
   CAST('["semantix_schema_migrations", "PRIMARY", "PRIMARY KEY", "YES", null]' AS JSON),
   CAST('["semantix_schema_migrations", "sm_codec", "CHECK", "YES", "(`codec` = 1)"]' AS JSON),
   CAST(CONVERT(0x5b2273656d616e7469785f736368656d615f6d6967726174696f6e73222c2022736d5f7374617465222c2022434845434b222c2022594553222c2022286073746174656020696e20285f62696e6172795c5c27494e495449414c495a494e475c5c272c5f62696e6172795c5c2752454144595c5c272929225d USING utf8mb4) AS JSON),
   CAST('["semantix_schema_migrations", "sm_version", "CHECK", "YES", "(`version` > 0)"]' AS JSON))),0)=23 FROM information_schema.TABLE_CONSTRAINTS tc LEFT JOIN information_schema.CHECK_CONSTRAINTS cc ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME WHERE tc.CONSTRAINT_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=11 AND COALESCE(SUM(JSON_ARRAY(TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,ORDINAL_POSITION,IF(REFERENCED_TABLE_SCHEMA=DATABASE(),'$DATABASE',REFERENCED_TABLE_SCHEMA),REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME) IN (CAST('["semantix_bindings", "binding_identity", "identity_sha256", 1, null, null, null]' AS JSON),
   CAST('["semantix_bindings", "binding_identity", "dimensions", 2, null, null, null]' AS JSON),
   CAST('["semantix_bindings", "PRIMARY", "binding_id", 1, null, null, null]' AS JSON),
   CAST('["semantix_entries", "PRIMARY", "binding_id", 1, null, null, null]' AS JSON),
   CAST('["semantix_entries", "PRIMARY", "cache_key", 2, null, null, null]' AS JSON),
   CAST('["semantix_entries", "se_binding", "binding_id", 1, "$DATABASE", "semantix_bindings", "binding_id"]' AS JSON),
   CAST('["semantix_payloads", "PRIMARY", "binding_id", 1, null, null, null]' AS JSON),
   CAST('["semantix_payloads", "PRIMARY", "cache_key", 2, null, null, null]' AS JSON),
   CAST('["semantix_payloads", "sp_entry", "binding_id", 1, "$DATABASE", "semantix_entries", "binding_id"]' AS JSON),
   CAST('["semantix_payloads", "sp_entry", "cache_key", 2, "$DATABASE", "semantix_entries", "cache_key"]' AS JSON),
   CAST('["semantix_schema_migrations", "PRIMARY", "version", 1, null, null, null]' AS JSON))),0)=11 FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=2 AND COALESCE(SUM(JSON_ARRAY(TABLE_NAME,CONSTRAINT_NAME,UNIQUE_CONSTRAINT_NAME,MATCH_OPTION,UPDATE_RULE,DELETE_RULE) IN (CAST('["semantix_entries", "se_binding", "PRIMARY", "NONE", "NO ACTION", "NO ACTION"]' AS JSON),
   CAST('["semantix_payloads", "sp_entry", "PRIMARY", "NONE", "NO ACTION", "CASCADE"]' AS JSON))),0)=2 FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=0 FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=1 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=0 FROM information_schema.PARAMETERS WHERE SPECIFIC_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=0 FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE())
 AND (SELECT COUNT(*)=1 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_NAME='semantix_verify' AND ROUTINE_TYPE='PROCEDURE' AND SECURITY_TYPE='DEFINER' AND SQL_DATA_ACCESS='READS SQL DATA' AND IS_DETERMINISTIC='NO' AND ROUTINE_BODY='SQL' AND PARAMETER_STYLE='SQL' AND ROUTINE_COMMENT='semantix-cache:mysql:verify:v2' AND DEFINER='semantix_schema_verifier@localhost' AND SQL_MODE='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' AND CHARACTER_SET_CLIENT='utf8mb4' AND COLLATION_CONNECTION='utf8mb4_bin' AND DATABASE_COLLATION='utf8mb4_bin')
 AND (SELECT COUNT(*)=4 FROM information_schema.SCHEMA_PRIVILEGES WHERE TABLE_SCHEMA=DATABASE() AND GRANTEE=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))) AND PRIVILEGE_TYPE IN ('SELECT','TRIGGER','EXECUTE','EVENT'))
 AND (SELECT COUNT(*)=2 FROM semantix_schema_migrations)
 AND (SELECT COUNT(*)=1 FROM semantix_schema_migrations WHERE version=1 AND owner=0x73656d616e7469782d63616368653a6d7973716c3a7631 AND checksum=0x2a2b9d29118053d8091871c30369ac0c629fa03d7291722ca1a0ba840f13cd13 AND state=0x5245414459 AND codec=1)
 AND (SELECT COUNT(*)=1 FROM semantix_schema_migrations WHERE version=2 AND owner=0x73656d616e7469782d63616368653a6d7973716c3a7631 AND state=0x5245414459 AND codec=1),0),(SELECT SHA2(ROUTINE_DEFINITION,256) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_NAME='semantix_verify');
