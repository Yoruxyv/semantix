import { isNonEmptyString, isNumberInRange, isRecord } from '@/shared/api/validators';

import type {
  EvaluationComparisonBlocker,
  EvaluationComparisonBlockerCode,
  EvaluationComparisonMetricDeltas,
  EvaluationComparisonStatus,
  EvaluationComparisonWarning,
  EvaluationComparisonWarningCode,
  EvaluationRunComparisonResponse,
  EvaluationThresholdComparisonDelta,
} from '../comparisonTypes';
import { decodeEvaluationRunHistoryDetail } from './historyDecoders';

const BLOCKER_CODES: readonly EvaluationComparisonBlockerCode[] = [
  'namespace_mismatch',
  'baseline_not_completed',
  'candidate_not_completed',
  'dataset_schema_mismatch',
  'dataset_digest_mismatch',
  'embedding_dimensions_mismatch',
  'embedding_space_mismatch',
  'normalization_mode_mismatch',
  'normalization_fingerprint_mismatch',
  'repetitions_mismatch',
  'reset_policy_mismatch',
  'comparison_contract_version_mismatch',
  'threshold_evaluation_mode_mismatch',
];

const WARNING_CODES: readonly EvaluationComparisonWarningCode[] = [
  'generation_provider_changed',
  'generation_configuration_changed',
  'application_version_changed',
  'cost_assumptions_changed',
  'evaluation_timeout_changed',
  'projection_list_changed',
  'persisted_dataset_identity_changed',
];

const COMPARISON_STATUSES: readonly EvaluationComparisonStatus[] = [
  'compatible',
  'warning',
  'incompatible',
];

const INTEGER_DELTA_FIELDS = [
  'total_queries',
  'cache_hits',
  'cache_misses',
  'provider_calls',
  'provider_calls_avoided',
  'estimated_tokens_saved',
  'true_positive_hits',
  'true_negative_misses',
  'false_positive_hits',
  'false_negative_misses',
] as const;

const NUMBER_DELTA_FIELDS = [
  'measured_threshold',
  'hit_rate',
  'average_latency_ms',
  'median_latency_ms',
  'p95_latency_ms',
  'estimated_latency_saved_ms',
  'estimated_provider_cost_saved_usd',
  'precision',
  'recall',
  'f1_score',
] as const;

const THRESHOLD_INTEGER_FIELDS = [
  'provider_calls_avoided',
  'true_positive_hits',
  'true_negative_misses',
  'false_positive_hits',
  'false_negative_misses',
] as const;

const THRESHOLD_NUMBER_FIELDS = [
  'hit_rate',
  'precision',
  'recall',
  'f1_score',
  'average_latency_ms',
] as const;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

function includesValue<T extends string>(
  values: readonly T[],
  value: unknown,
): value is T {
  return typeof value === 'string' && values.includes(value as T);
}

function issueDetail(value: unknown): value is string {
  return isNonEmptyString(value) && value.length <= 300;
}

function blocker(value: unknown): EvaluationComparisonBlocker {
  if (
    !isRecord(value) ||
    !includesValue(BLOCKER_CODES, value.code) ||
    !issueDetail(value.detail)
  ) {
    throw new Error('Invalid evaluation comparison blocker');
  }
  return { code: value.code, detail: value.detail };
}

function warning(value: unknown): EvaluationComparisonWarning {
  if (
    !isRecord(value) ||
    !includesValue(WARNING_CODES, value.code) ||
    !issueDetail(value.detail)
  ) {
    throw new Error('Invalid evaluation comparison warning');
  }
  return { code: value.code, detail: value.detail };
}

function metricDeltas(value: unknown): EvaluationComparisonMetricDeltas {
  if (!isRecord(value)) {
    throw new Error('Invalid evaluation comparison metric deltas');
  }

  if (
    !INTEGER_DELTA_FIELDS.every((field) => isInteger(value[field])) ||
    !NUMBER_DELTA_FIELDS.every((field) => isFiniteNumber(value[field])) ||
    !isNullableFiniteNumber(value.average_cache_hit_latency_ms) ||
    !isNullableFiniteNumber(value.average_cache_miss_latency_ms)
  ) {
    throw new Error('Invalid evaluation comparison metric delta values');
  }

  return value as unknown as EvaluationComparisonMetricDeltas;
}

function thresholdDelta(value: unknown): EvaluationThresholdComparisonDelta {
  if (
    !isRecord(value) ||
    !isNumberInRange(value.threshold, 0, 1) ||
    (value.baseline_result_kind !== 'measured' &&
      value.baseline_result_kind !== 'projected') ||
    (value.candidate_result_kind !== 'measured' &&
      value.candidate_result_kind !== 'projected') ||
    !THRESHOLD_INTEGER_FIELDS.every((field) => isInteger(value[field])) ||
    !THRESHOLD_NUMBER_FIELDS.every((field) => isFiniteNumber(value[field]))
  ) {
    throw new Error('Invalid evaluation threshold comparison delta');
  }

  return value as unknown as EvaluationThresholdComparisonDelta;
}

export function decodeEvaluationRunComparison(
  value: unknown,
): EvaluationRunComparisonResponse {
  if (
    !isRecord(value) ||
    !isRecord(value.baseline) ||
    !isRecord(value.candidate) ||
    'query_results' in value.baseline ||
    'query_results' in value.candidate ||
    !isRecord(value.compatibility) ||
    !includesValue(COMPARISON_STATUSES, value.compatibility.status) ||
    typeof value.compatibility.can_compare !== 'boolean' ||
    !Array.isArray(value.compatibility.incompatibilities) ||
    !Array.isArray(value.compatibility.warnings) ||
    value.compatibility.case_evidence !== 'not_retained' ||
    typeof value.compatibility.opaque_configuration_fingerprint_matches !== 'boolean' ||
    !Array.isArray(value.threshold_deltas)
  ) {
    throw new Error('Invalid evaluation run comparison');
  }

  const baseline = decodeEvaluationRunHistoryDetail(value.baseline);
  const candidate = decodeEvaluationRunHistoryDetail(value.candidate);
  const incompatibilities = value.compatibility.incompatibilities.map(blocker);
  const warnings = value.compatibility.warnings.map(warning);
  const thresholdDeltas = value.threshold_deltas.map(thresholdDelta);
  const decodedMetricDeltas =
    value.metric_deltas === null ? null : metricDeltas(value.metric_deltas);

  let expectedStatus: EvaluationComparisonStatus = 'compatible';
  if (incompatibilities.length > 0) {
    expectedStatus = 'incompatible';
  } else if (warnings.length > 0) {
    expectedStatus = 'warning';
  }

  if (
    baseline.run_id === candidate.run_id ||
    value.compatibility.status !== expectedStatus ||
    value.compatibility.can_compare !== (incompatibilities.length === 0) ||
    (value.compatibility.can_compare && decodedMetricDeltas === null) ||
    (!value.compatibility.can_compare &&
      (decodedMetricDeltas !== null || thresholdDeltas.length > 0))
  ) {
    throw new Error('Invalid evaluation comparison compatibility accounting');
  }

  const baselineThresholds = new Map(
    baseline.threshold_evaluations.map((evaluation) => [
      evaluation.threshold,
      evaluation,
    ]),
  );
  const candidateThresholds = new Map(
    candidate.threshold_evaluations.map((evaluation) => [
      evaluation.threshold,
      evaluation,
    ]),
  );

  let previousThreshold = -Infinity;
  for (const delta of thresholdDeltas) {
    const baselineEvaluation = baselineThresholds.get(delta.threshold);
    const candidateEvaluation = candidateThresholds.get(delta.threshold);
    if (
      delta.threshold <= previousThreshold ||
      baselineEvaluation === undefined ||
      candidateEvaluation === undefined ||
      baselineEvaluation.result_kind !== delta.baseline_result_kind ||
      candidateEvaluation.result_kind !== delta.candidate_result_kind
    ) {
      throw new Error('Invalid evaluation comparison threshold accounting');
    }
    previousThreshold = delta.threshold;
  }

  return {
    baseline,
    candidate,
    compatibility: {
      status: value.compatibility.status,
      can_compare: value.compatibility.can_compare,
      incompatibilities,
      warnings,
      case_evidence: 'not_retained',
      opaque_configuration_fingerprint_matches:
        value.compatibility.opaque_configuration_fingerprint_matches,
    },
    metric_deltas: decodedMetricDeltas,
    threshold_deltas: thresholdDeltas,
  };
}
