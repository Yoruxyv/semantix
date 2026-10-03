export type BenchmarkDatasetId = 'quick' | 'extended';
export type EvaluationDatasetSourceKind = 'builtin' | 'inline' | 'persisted';
export type EvaluationRunRetentionState =
  'not_retained' | 'retained' | 'retention_failed';

export type BenchmarkOutcome =
  'true_positive' | 'true_negative' | 'false_positive' | 'false_negative';

export interface BenchmarkDatasetSummary {
  dataset_id: string;
  dataset_source: EvaluationDatasetSourceKind;
  schema_version: number | null;
  version: string;
  digest: string;
  name: string;
  description: string;
  query_count: number;
  expected_hits: number;
  expected_misses: number;
  categories: string[];
}

export interface BenchmarkDatasetListResponse {
  datasets: BenchmarkDatasetSummary[];
  default_dataset_id: BenchmarkDatasetId;
}

export interface BenchmarkRunRequest {
  dataset_id: BenchmarkDatasetId;
  threshold: number;
  evaluation_thresholds: number[];
  repetitions: number;
  reset_cache_before_run: boolean;
  estimated_cost_per_request_usd: number;
  estimated_cost_per_1k_tokens_usd: number;
  allow_external_provider_calls: true;
}

export interface EvaluationDatasetValidationRequest {
  dataset: unknown;
  repetitions: number;
  threshold_count: number;
}

export interface EvaluationDatasetWarning {
  code: string;
  detail: string;
  count: number;
}

export interface EvaluationDatasetPreview {
  schema_version: 1;
  dataset_id: string;
  digest: string;
  name: string;
  description: string | null;
  case_count: number;
  expected_hits: number;
  expected_misses: number;
  categories: string[];
  decoded_bytes: number;
  warnings: EvaluationDatasetWarning[];
  query_executions: number;
  threshold_projection_evaluations: number;
  maximum_provider_calls: number;
  provider_calls_made: 0;
  limits: {
    max_cases: number;
    max_decoded_bytes: number;
    max_workload_queries: number;
  };
}

export interface ImportedEvaluationCase {
  case_id: string;
  prompt: string;
  expected_cache_hit: boolean;
  expected_match_case_id: string | null;
  category: string | null;
  note: string | null;
}

export interface PersistedEvaluationDatasetMetadata {
  dataset_id: string;
  namespace: string;
  name: string;
  description: string | null;
  source_type: 'imported';
  schema_version: 1;
  digest: string;
  case_count: number;
  decoded_bytes: number;
  created_at: string;
  expires_at: string;
}

export interface PersistedEvaluationDatasetDetail extends PersistedEvaluationDatasetMetadata {
  cases: ImportedEvaluationCase[];
}

export interface PersistedEvaluationDatasetCatalogLimits {
  default_retention_days: number;
  max_retention_days: number;
  max_persisted_per_namespace: number;
}

export interface PersistedEvaluationDatasetListResponse {
  storage_mode: 'session' | 'postgres';
  persistence_enabled: boolean;
  items: PersistedEvaluationDatasetMetadata[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  limits: PersistedEvaluationDatasetCatalogLimits;
}

export interface PersistEvaluationDatasetRequest {
  namespace?: string;
  dataset: unknown;
  retention_days?: number;
}

export interface DeletePersistedEvaluationDatasetResponse {
  deleted: true;
  dataset_id: string;
  namespace: string;
}

export interface EvaluationRunRequest extends Omit<BenchmarkRunRequest, 'dataset_id'> {
  history_namespace?: string;
  dataset_source:
    | { kind: 'builtin'; dataset_id: BenchmarkDatasetId }
    | { kind: 'inline'; definition: unknown }
    | { kind: 'persisted'; dataset_id: string; namespace: string };
}

export interface BenchmarkMetrics {
  total_queries: number;
  cache_hits: number;
  cache_misses: number;
  provider_calls: number;
  provider_calls_avoided: number;
  hit_rate: number;
  average_latency_ms: number;
  median_latency_ms: number;
  p95_latency_ms: number;
  average_cache_hit_latency_ms: number | null;
  average_cache_miss_latency_ms: number | null;
  estimated_latency_saved_ms: number;
  estimated_provider_cost_saved_usd: number;
  estimated_tokens_saved: number;
  true_positive_hits: number;
  true_negative_misses: number;
  false_positive_hits: number;
  false_negative_misses: number;
  precision: number;
  recall: number;
  f1_score: number;
}

export interface BenchmarkQueryResult {
  sequence: number;
  repetition: number;
  case_id: string;
  category: string;
  prompt: string;
  expected_cache_hit: boolean;
  expected_match_case_id: string | null;
  note: string | null;
  actual_cache_hit: boolean;
  correct: boolean;
  outcome: BenchmarkOutcome;
  similarity_score: number | null;
  latency_ms: number;
  provider_called: boolean;
  matched_prompt: string | null;
  matched_cache_key: string | null;
}

export interface ThresholdEvaluation {
  threshold: number;
  result_kind: 'measured' | 'projected';
  hit_rate: number;
  precision: number;
  recall: number;
  f1_score: number;
  average_latency_ms: number;
  provider_calls_avoided: number;
  true_positive_hits: number;
  true_negative_misses: number;
  false_positive_hits: number;
  false_negative_misses: number;
}

export interface BenchmarkReproducibilityMetadata {
  application_version: string;
  dataset_id: string;
  dataset_source: EvaluationDatasetSourceKind;
  dataset_schema_version: number | null;
  dataset_version: string;
  dataset_digest: string;
  embedding_provider_category: string;
  generation_provider_category: string;
  generation_configuration_fingerprint: string;
  comparison_contract_version: 1;
  embedding_dimensions: number;
  embedding_space_fingerprint: string;
  normalization_mode: 'identity' | 'typo_correction';
  normalization_fingerprint: string;
  measured_threshold: number;
  evaluation_thresholds: number[];
  repetitions: number;
  reset_cache_before_run: boolean;
  estimated_cost_per_request_usd: number;
  estimated_cost_per_1k_tokens_usd: number;
  evaluation_timeout_seconds: number;
  configuration_fingerprint: string;
}

export interface EvaluationRunRetentionStatus {
  state: EvaluationRunRetentionState;
}

export interface BenchmarkRunResponse {
  run_id: string;
  started_at: string;
  completed_at: string;
  dataset: BenchmarkDatasetSummary;
  threshold: number;
  repetitions: number;
  reset_cache_before_run: boolean;
  estimated_cost_per_request_usd: number;
  estimated_cost_per_1k_tokens_usd: number;
  reproducibility: BenchmarkReproducibilityMetadata;
  history_retention: EvaluationRunRetentionStatus;
  metrics: BenchmarkMetrics;
  threshold_evaluation_mode: 'frozen_candidate_projection';
  threshold_evaluations: ThresholdEvaluation[];
  query_results: BenchmarkQueryResult[];
}

export type EvaluationRunTerminalState = 'completed' | 'failed' | 'timed_out';

export interface EvaluationRunHistoryItem {
  run_id: string;
  namespace: string;
  terminal_state: EvaluationRunTerminalState;
  accepted_at: string;
  started_at: string;
  completed_at: string;
  expires_at: string;
  source_dataset_expires_at: string | null;
  dataset: BenchmarkDatasetSummary;
  reproducibility: BenchmarkReproducibilityMetadata;
  metrics: BenchmarkMetrics | null;
  failure_code: string | null;
  safe_failure_detail: string | null;
}

export interface EvaluationRunHistoryDetail extends EvaluationRunHistoryItem {
  threshold_evaluation_mode: 'frozen_candidate_projection';
  threshold_evaluations: ThresholdEvaluation[];
}

export interface EvaluationRunHistoryListResponse {
  storage_mode: 'disabled' | 'postgres';
  retention_enabled: boolean;
  items: EvaluationRunHistoryItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface DeleteEvaluationRunHistoryResponse {
  deleted: true;
  run_id: string;
  namespace: string;
}
