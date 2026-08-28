import {
  createEnumGuard,
  isIsoDate,
  isNonEmptyString,
  isNonNegativeInteger,
  isNonNegativeNumber,
  isNullableNonNegativeNumber,
  isNumberInRange,
  isRecord,
} from '@/shared/api/validators';

import type {
  BenchmarkDatasetSummary,
  BenchmarkMetrics,
  BenchmarkReproducibilityMetadata,
  EvaluationDatasetSourceKind,
  ProviderCategory,
  ThresholdEvaluation,
} from '../types';

const PROVIDER_CATEGORIES: readonly ProviderCategory[] = [
  'huggingface',
  'openai',
  'anthropic',
  'gemini',
  'ollama',
  'mock',
];
const RESULT_KINDS = ['measured', 'projected'] as const;
const NORMALIZATION_MODES = ['identity', 'typo_correction'] as const;
const DATASET_SOURCE_KINDS: readonly EvaluationDatasetSourceKind[] = [
  'builtin',
  'inline',
  'persisted',
];

const isProviderCategory = createEnumGuard(PROVIDER_CATEGORIES);
const isResultKind = createEnumGuard(RESULT_KINDS);
const isNormalizationMode = createEnumGuard(NORMALIZATION_MODES);
const isDatasetSourceKind = createEnumGuard(DATASET_SOURCE_KINDS);

export const RUN_ID_PATTERN = /^[a-f0-9]{32}$/;
export const SHA256_PATTERN = /^[a-f0-9]{64}$/;
export const DATASET_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
export const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TIMEZONE_SUFFIX_PATTERN = /(Z|[+-]\d{2}:\d{2})$/i;

export function isTimezoneAwareIsoDate(value: unknown): value is string {
  return isIsoDate(value) && TIMEZONE_SUFFIX_PATTERN.test(value);
}

export function isNullableBoundedString(
  value: unknown,
  maximumLength: number,
): value is string | null {
  return value === null || (isNonEmptyString(value) && value.length <= maximumLength);
}

export function decodeBenchmarkDatasetSummaryValue(
  value: unknown,
): BenchmarkDatasetSummary {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.dataset_id) ||
    value.dataset_id.length > 100 ||
    !DATASET_ID_PATTERN.test(value.dataset_id) ||
    !isDatasetSourceKind(value.dataset_source) ||
    !(
      value.schema_version === null ||
      (isNonNegativeInteger(value.schema_version) && value.schema_version >= 1)
    ) ||
    !isNonEmptyString(value.version) ||
    value.version.length > 50 ||
    typeof value.digest !== 'string' ||
    !SHA256_PATTERN.test(value.digest) ||
    !isNonEmptyString(value.name) ||
    value.name.length > 100 ||
    !isNonEmptyString(value.description) ||
    value.description.length > 300 ||
    !isNonNegativeInteger(value.query_count) ||
    value.query_count < 1 ||
    !isNonNegativeInteger(value.expected_hits) ||
    !isNonNegativeInteger(value.expected_misses) ||
    !Array.isArray(value.categories) ||
    value.categories.length === 0 ||
    !value.categories.every(
      (category) => isNonEmptyString(category) && category.length <= 100,
    )
  ) {
    throw new Error('Invalid benchmark dataset');
  }

  if (
    value.expected_hits + value.expected_misses !== value.query_count ||
    new Set(value.categories).size !== value.categories.length ||
    (value.dataset_source === 'builtin' && value.schema_version !== null) ||
    ((value.dataset_source === 'inline' || value.dataset_source === 'persisted') &&
      value.schema_version !== 1)
  ) {
    throw new Error('Invalid benchmark dataset accounting');
  }

  return {
    dataset_id: value.dataset_id,
    dataset_source: value.dataset_source,
    schema_version: value.schema_version,
    version: value.version,
    digest: value.digest,
    name: value.name,
    description: value.description,
    query_count: value.query_count,
    expected_hits: value.expected_hits,
    expected_misses: value.expected_misses,
    categories: value.categories,
  };
}

export function decodeBenchmarkMetricsValue(value: unknown): BenchmarkMetrics {
  if (!isRecord(value)) {
    throw new Error('Invalid benchmark metrics');
  }

  const totalQueries = value.total_queries;
  const cacheHits = value.cache_hits;
  const cacheMisses = value.cache_misses;
  const providerCalls = value.provider_calls;
  const providerCallsAvoided = value.provider_calls_avoided;
  const truePositiveHits = value.true_positive_hits;
  const trueNegativeMisses = value.true_negative_misses;
  const falsePositiveHits = value.false_positive_hits;
  const falseNegativeMisses = value.false_negative_misses;
  const integers = [value.estimated_tokens_saved];

  const nonNegativeNumbers = [
    value.average_latency_ms,
    value.median_latency_ms,
    value.p95_latency_ms,
    value.estimated_latency_saved_ms,
    value.estimated_provider_cost_saved_usd,
  ];

  if (
    !isNonNegativeInteger(totalQueries) ||
    !isNonNegativeInteger(cacheHits) ||
    !isNonNegativeInteger(cacheMisses) ||
    !isNonNegativeInteger(providerCalls) ||
    !isNonNegativeInteger(providerCallsAvoided) ||
    !isNonNegativeInteger(truePositiveHits) ||
    !isNonNegativeInteger(trueNegativeMisses) ||
    !isNonNegativeInteger(falsePositiveHits) ||
    !isNonNegativeInteger(falseNegativeMisses) ||
    !integers.every(isNonNegativeInteger) ||
    totalQueries < 1 ||
    !nonNegativeNumbers.every(isNonNegativeNumber) ||
    !isNumberInRange(value.hit_rate, 0, 1) ||
    !isNumberInRange(value.precision, 0, 1) ||
    !isNumberInRange(value.recall, 0, 1) ||
    !isNumberInRange(value.f1_score, 0, 1) ||
    !isNullableNonNegativeNumber(value.average_cache_hit_latency_ms) ||
    !isNullableNonNegativeNumber(value.average_cache_miss_latency_ms)
  ) {
    throw new Error('Invalid benchmark metrics');
  }

  if (
    cacheHits + cacheMisses !== totalQueries ||
    providerCalls + providerCallsAvoided !== totalQueries ||
    truePositiveHits + trueNegativeMisses + falsePositiveHits + falseNegativeMisses !==
      totalQueries ||
    truePositiveHits + falsePositiveHits !== cacheHits ||
    trueNegativeMisses + falseNegativeMisses !== cacheMisses ||
    providerCalls !== cacheMisses ||
    providerCallsAvoided !== cacheHits
  ) {
    throw new Error('Invalid benchmark metric accounting');
  }

  return value as unknown as BenchmarkMetrics;
}

export function decodeThresholdEvaluationValue(value: unknown): ThresholdEvaluation {
  if (
    !isRecord(value) ||
    !isNumberInRange(value.threshold, 0, 1) ||
    !isResultKind(value.result_kind) ||
    !isNumberInRange(value.hit_rate, 0, 1) ||
    !isNumberInRange(value.precision, 0, 1) ||
    !isNumberInRange(value.recall, 0, 1) ||
    !isNumberInRange(value.f1_score, 0, 1) ||
    !isNonNegativeNumber(value.average_latency_ms) ||
    !isNonNegativeInteger(value.provider_calls_avoided) ||
    !isNonNegativeInteger(value.true_positive_hits) ||
    !isNonNegativeInteger(value.true_negative_misses) ||
    !isNonNegativeInteger(value.false_positive_hits) ||
    !isNonNegativeInteger(value.false_negative_misses)
  ) {
    throw new Error('Invalid threshold evaluation');
  }

  if (
    value.true_positive_hits + value.false_positive_hits !==
    value.provider_calls_avoided
  ) {
    throw new Error('Invalid threshold evaluation accounting');
  }

  return value as unknown as ThresholdEvaluation;
}

export function decodeBenchmarkReproducibilityValue(
  value: unknown,
): BenchmarkReproducibilityMetadata {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.application_version) ||
    value.application_version.length > 50 ||
    !isNonEmptyString(value.dataset_id) ||
    value.dataset_id.length > 100 ||
    !DATASET_ID_PATTERN.test(value.dataset_id) ||
    !isDatasetSourceKind(value.dataset_source) ||
    !(
      value.dataset_schema_version === null ||
      (isNonNegativeInteger(value.dataset_schema_version) &&
        value.dataset_schema_version >= 1)
    ) ||
    !isNonEmptyString(value.dataset_version) ||
    value.dataset_version.length > 50 ||
    typeof value.dataset_digest !== 'string' ||
    !SHA256_PATTERN.test(value.dataset_digest) ||
    !isProviderCategory(value.embedding_provider_category) ||
    !isProviderCategory(value.generation_provider_category) ||
    typeof value.generation_configuration_fingerprint !== 'string' ||
    !SHA256_PATTERN.test(value.generation_configuration_fingerprint) ||
    value.comparison_contract_version !== 1 ||
    !isNonNegativeInteger(value.embedding_dimensions) ||
    value.embedding_dimensions < 1 ||
    typeof value.embedding_space_fingerprint !== 'string' ||
    !SHA256_PATTERN.test(value.embedding_space_fingerprint) ||
    !isNormalizationMode(value.normalization_mode) ||
    typeof value.normalization_fingerprint !== 'string' ||
    !SHA256_PATTERN.test(value.normalization_fingerprint) ||
    !isNumberInRange(value.measured_threshold, 0, 1) ||
    !Array.isArray(value.evaluation_thresholds) ||
    value.evaluation_thresholds.length < 2 ||
    value.evaluation_thresholds.length > 15 ||
    !value.evaluation_thresholds.every((threshold) =>
      isNumberInRange(threshold, 0, 1),
    ) ||
    !isNonNegativeInteger(value.repetitions) ||
    !isNumberInRange(value.repetitions, 1, 5) ||
    typeof value.reset_cache_before_run !== 'boolean' ||
    !isNumberInRange(value.estimated_cost_per_request_usd, 0, 100) ||
    !isNumberInRange(value.estimated_cost_per_1k_tokens_usd, 0, 100) ||
    !isNonNegativeNumber(value.evaluation_timeout_seconds) ||
    value.evaluation_timeout_seconds <= 0 ||
    value.evaluation_timeout_seconds > 3_600 ||
    typeof value.configuration_fingerprint !== 'string' ||
    !SHA256_PATTERN.test(value.configuration_fingerprint)
  ) {
    throw new Error('Invalid benchmark reproducibility metadata');
  }

  const thresholds = value.evaluation_thresholds as number[];
  if (
    (value.dataset_source === 'builtin' && value.dataset_schema_version !== null) ||
    ((value.dataset_source === 'inline' || value.dataset_source === 'persisted') &&
      value.dataset_schema_version !== 1) ||
    thresholds.some(
      (threshold, index) =>
        index > 0 && threshold <= (thresholds[index - 1] ?? threshold),
    )
  ) {
    throw new Error('Invalid benchmark reproducibility thresholds');
  }

  return value as unknown as BenchmarkReproducibilityMetadata;
}
