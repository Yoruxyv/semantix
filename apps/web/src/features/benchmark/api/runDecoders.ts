import {
  createEnumGuard,
  isNonEmptyString,
  isNonNegativeInteger,
  isNonNegativeNumber,
  isNumberInRange,
  isRecord,
} from '@/shared/api/validators';
import { SIMILARITY_MAX, SIMILARITY_MIN } from '@/shared/domain/similarity';

import type {
  BenchmarkOutcome,
  BenchmarkQueryResult,
  BenchmarkRunResponse,
  EvaluationRunRetentionState,
  EvaluationRunRetentionStatus,
} from '../types';
import {
  RUN_ID_PATTERN,
  SHA256_PATTERN,
  decodeBenchmarkDatasetSummaryValue,
  decodeBenchmarkMetricsValue,
  decodeBenchmarkReproducibilityValue,
  decodeThresholdEvaluationValue,
  isNullableBoundedString,
  isTimezoneAwareIsoDate,
} from './decoderValues';

const OUTCOMES: readonly BenchmarkOutcome[] = [
  'true_positive',
  'true_negative',
  'false_positive',
  'false_negative',
];
const RUN_RETENTION_STATES: readonly EvaluationRunRetentionState[] = [
  'not_retained',
  'retained',
  'retention_failed',
];

const isOutcome = createEnumGuard(OUTCOMES);
const isRunRetentionState = createEnumGuard(RUN_RETENTION_STATES);

function queryResult(value: unknown): BenchmarkQueryResult {
  if (!isRecord(value)) {
    throw new Error('Invalid benchmark query result');
  }

  const hasValidSimilarityScore =
    value.similarity_score === null ||
    isNumberInRange(value.similarity_score, SIMILARITY_MIN, SIMILARITY_MAX);
  const hasValidMatchedKey =
    value.matched_cache_key === null ||
    (typeof value.matched_cache_key === 'string' &&
      SHA256_PATTERN.test(value.matched_cache_key));

  if (
    !isNonNegativeInteger(value.sequence) ||
    value.sequence < 1 ||
    !isNonNegativeInteger(value.repetition) ||
    value.repetition < 1 ||
    !isNonEmptyString(value.case_id) ||
    value.case_id.length > 100 ||
    !isNonEmptyString(value.category) ||
    value.category.length > 100 ||
    !isNonEmptyString(value.prompt) ||
    value.prompt.length > 2_000 ||
    typeof value.expected_cache_hit !== 'boolean' ||
    !isNullableBoundedString(value.expected_match_case_id, 100) ||
    !isNullableBoundedString(value.note, 500) ||
    typeof value.actual_cache_hit !== 'boolean' ||
    typeof value.correct !== 'boolean' ||
    !isOutcome(value.outcome) ||
    !hasValidSimilarityScore ||
    !isNonNegativeNumber(value.latency_ms) ||
    typeof value.provider_called !== 'boolean' ||
    !isNullableBoundedString(value.matched_prompt, 2_000) ||
    !hasValidMatchedKey
  ) {
    throw new Error('Invalid benchmark query result');
  }

  let expectedOutcome: BenchmarkOutcome;
  if (value.actual_cache_hit) {
    expectedOutcome = value.expected_cache_hit ? 'true_positive' : 'false_positive';
  } else {
    expectedOutcome = value.expected_cache_hit ? 'false_negative' : 'true_negative';
  }
  if (
    value.outcome !== expectedOutcome ||
    value.correct !== (value.expected_cache_hit === value.actual_cache_hit) ||
    (!value.expected_cache_hit && value.expected_match_case_id !== null) ||
    value.provider_called === value.actual_cache_hit ||
    (value.actual_cache_hit &&
      (value.matched_prompt === null || value.matched_cache_key === null)) ||
    (!value.actual_cache_hit &&
      (value.matched_prompt !== null || value.matched_cache_key !== null))
  ) {
    throw new Error('Invalid benchmark query accounting');
  }

  return value as unknown as BenchmarkQueryResult;
}

function runRetention(value: unknown): EvaluationRunRetentionStatus {
  if (!isRecord(value) || !isRunRetentionState(value.state)) {
    throw new Error('Invalid evaluation run retention status');
  }

  return value as unknown as EvaluationRunRetentionStatus;
}

export function decodeBenchmarkRun(value: unknown): BenchmarkRunResponse {
  if (
    !isRecord(value) ||
    typeof value.run_id !== 'string' ||
    !RUN_ID_PATTERN.test(value.run_id) ||
    !isTimezoneAwareIsoDate(value.started_at) ||
    !isTimezoneAwareIsoDate(value.completed_at) ||
    !isNumberInRange(value.threshold, 0, 1) ||
    !isNonNegativeInteger(value.repetitions) ||
    !isNumberInRange(value.repetitions, 1, 5) ||
    typeof value.reset_cache_before_run !== 'boolean' ||
    !isNonNegativeNumber(value.estimated_cost_per_request_usd) ||
    !isNonNegativeNumber(value.estimated_cost_per_1k_tokens_usd) ||
    !isRecord(value.reproducibility) ||
    value.threshold_evaluation_mode !== 'frozen_candidate_projection' ||
    !Array.isArray(value.threshold_evaluations) ||
    value.threshold_evaluations.length < 2 ||
    value.threshold_evaluations.length > 15 ||
    !Array.isArray(value.query_results) ||
    value.query_results.length === 0
  ) {
    throw new Error('Invalid benchmark run response');
  }

  const decodedDataset = decodeBenchmarkDatasetSummaryValue(value.dataset);
  const decodedReproducibility = decodeBenchmarkReproducibilityValue(
    value.reproducibility,
  );
  const decodedHistoryRetention = runRetention(value.history_retention);
  const decodedMetrics = decodeBenchmarkMetricsValue(value.metrics);
  const thresholdEvaluations = value.threshold_evaluations.map(
    decodeThresholdEvaluationValue,
  );
  const queryResults = value.query_results.map(queryResult);
  const expectedResultCount = decodedDataset.query_count * value.repetitions;
  const thresholds = thresholdEvaluations.map((evaluation) => evaluation.threshold);
  const measured = thresholdEvaluations.filter(
    (evaluation) => evaluation.result_kind === 'measured',
  );
  const outcomeCount = (outcome: BenchmarkOutcome): number =>
    queryResults.filter((query) => query.outcome === outcome).length;

  if (
    Date.parse(value.completed_at) < Date.parse(value.started_at) ||
    queryResults.length !== expectedResultCount ||
    decodedMetrics.total_queries !== queryResults.length ||
    decodedMetrics.true_positive_hits !== outcomeCount('true_positive') ||
    decodedMetrics.true_negative_misses !== outcomeCount('true_negative') ||
    decodedMetrics.false_positive_hits !== outcomeCount('false_positive') ||
    decodedMetrics.false_negative_misses !== outcomeCount('false_negative') ||
    decodedMetrics.provider_calls !==
      queryResults.filter((query) => query.provider_called).length ||
    measured.length !== 1 ||
    measured[0]?.threshold !== value.threshold ||
    thresholds.some(
      (threshold, index) =>
        index > 0 && threshold <= (thresholds[index - 1] ?? threshold),
    ) ||
    thresholdEvaluations.some(
      (evaluation) =>
        evaluation.true_positive_hits +
          evaluation.true_negative_misses +
          evaluation.false_positive_hits +
          evaluation.false_negative_misses !==
        queryResults.length,
    ) ||
    decodedReproducibility.dataset_id !== decodedDataset.dataset_id ||
    decodedReproducibility.dataset_source !== decodedDataset.dataset_source ||
    decodedReproducibility.dataset_schema_version !== decodedDataset.schema_version ||
    decodedReproducibility.dataset_version !== decodedDataset.version ||
    decodedReproducibility.dataset_digest !== decodedDataset.digest ||
    decodedReproducibility.measured_threshold !== value.threshold ||
    decodedReproducibility.repetitions !== value.repetitions ||
    decodedReproducibility.reset_cache_before_run !== value.reset_cache_before_run ||
    decodedReproducibility.estimated_cost_per_request_usd !==
      value.estimated_cost_per_request_usd ||
    decodedReproducibility.estimated_cost_per_1k_tokens_usd !==
      value.estimated_cost_per_1k_tokens_usd ||
    decodedReproducibility.evaluation_thresholds.length !== thresholds.length ||
    decodedReproducibility.evaluation_thresholds.some(
      (threshold, index) => threshold !== thresholds[index],
    )
  ) {
    throw new Error('Invalid benchmark run accounting');
  }

  return {
    run_id: value.run_id,
    started_at: value.started_at,
    completed_at: value.completed_at,
    dataset: decodedDataset,
    threshold: value.threshold,
    repetitions: value.repetitions,
    reset_cache_before_run: value.reset_cache_before_run,
    estimated_cost_per_request_usd: value.estimated_cost_per_request_usd,
    estimated_cost_per_1k_tokens_usd: value.estimated_cost_per_1k_tokens_usd,
    reproducibility: decodedReproducibility,
    history_retention: decodedHistoryRetention,
    metrics: decodedMetrics,
    threshold_evaluation_mode: value.threshold_evaluation_mode,
    threshold_evaluations: thresholdEvaluations,
    query_results: queryResults,
  };
}
