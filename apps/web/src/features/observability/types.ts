export interface RuntimeMetrics {
  observed_at: string;
  uptime_seconds: number;
  request_count: number;
  error_count: number;
  cache_hits: number;
  cache_misses: number;
  provider_calls: number;
  in_flight_coalesced_requests: number;
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
  latency_sample_size: number;
  cache_size: number;
  evictions: number;
  expirations: number;
}

export interface RuntimeDiagnostics {
  observed_at: string;
  process_scope: 'single_backend_process';
  application_version: string;
  embedding_provider_category: string;
  generation_provider_category: string;
  embedding_dimensions: number;
  embedding_space_fingerprint: string;
  generation_configuration_fingerprint: string;
  cache_backend: 'memory' | 'pgvector';
  cache_readiness: 'ready' | 'unavailable';
  normalization_mode: 'identity' | 'typo_correction';
  normalization_algorithm_version: 'identity-v1' | 'symspell-compound-v1';
  normalization_fingerprint: string;
  evaluation_timeout_seconds: number;
  evaluation_max_cases: number;
  evaluation_max_repetitions: number;
  evaluation_max_thresholds: number;
  evaluation_max_request_bytes: number;
  evaluation_dataset_persistence_enabled: boolean;
  evaluation_history_persistence_enabled: boolean;
}
