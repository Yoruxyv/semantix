import type { EvaluationRunHistoryDetail } from './types';

export type EvaluationComparisonStatus = 'compatible' | 'warning' | 'incompatible';

export type EvaluationComparisonBlockerCode =
  | 'namespace_mismatch'
  | 'baseline_not_completed'
  | 'candidate_not_completed'
  | 'dataset_schema_mismatch'
  | 'dataset_digest_mismatch'
  | 'embedding_dimensions_mismatch'
  | 'embedding_space_mismatch'
  | 'normalization_mode_mismatch'
  | 'normalization_fingerprint_mismatch'
  | 'repetitions_mismatch'
  | 'reset_policy_mismatch'
  | 'comparison_contract_version_mismatch'
  | 'threshold_evaluation_mode_mismatch';

export type EvaluationComparisonWarningCode =
  | 'generation_provider_changed'
  | 'generation_configuration_changed'
  | 'application_version_changed'
  | 'cost_assumptions_changed'
  | 'evaluation_timeout_changed'
  | 'projection_list_changed'
  | 'persisted_dataset_identity_changed';

export interface EvaluationRunComparisonRequest {
  baseline_run_id: string;
  candidate_run_id: string;
}

export interface EvaluationComparisonBlocker {
  code: EvaluationComparisonBlockerCode;
  detail: string;
}

export interface EvaluationComparisonWarning {
  code: EvaluationComparisonWarningCode;
  detail: string;
}

export interface EvaluationComparisonCompatibility {
  status: EvaluationComparisonStatus;
  can_compare: boolean;
  incompatibilities: EvaluationComparisonBlocker[];
  warnings: EvaluationComparisonWarning[];
  case_evidence: 'not_retained';
  opaque_configuration_fingerprint_matches: boolean;
}

export interface EvaluationComparisonMetricDeltas {
  measured_threshold: number;
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

export interface EvaluationThresholdComparisonDelta {
  threshold: number;
  baseline_result_kind: 'measured' | 'projected';
  candidate_result_kind: 'measured' | 'projected';
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

export interface EvaluationRunComparisonResponse {
  baseline: EvaluationRunHistoryDetail;
  candidate: EvaluationRunHistoryDetail;
  compatibility: EvaluationComparisonCompatibility;
  metric_deltas: EvaluationComparisonMetricDeltas | null;
  threshold_deltas: EvaluationThresholdComparisonDelta[];
}
