import { isCacheNamespace } from '@/features/cache/namespace';
import {
  createEnumGuard,
  isNonEmptyString,
  isNonNegativeInteger,
  isRecord,
} from '@/shared/api/validators';

import type {
  BenchmarkDatasetId,
  BenchmarkDatasetListResponse,
  DeletePersistedEvaluationDatasetResponse,
  EvaluationDatasetPreview,
  EvaluationDatasetWarning,
  ImportedEvaluationCase,
  PersistedEvaluationDatasetDetail,
  PersistedEvaluationDatasetListResponse,
  PersistedEvaluationDatasetMetadata,
} from '../types';
import {
  DATASET_ID_PATTERN,
  SHA256_PATTERN,
  UUID_PATTERN,
  decodeBenchmarkDatasetSummaryValue,
  isNullableBoundedString,
  isTimezoneAwareIsoDate,
} from './decoderValues';

const DATASET_IDS: readonly BenchmarkDatasetId[] = ['quick', 'extended'];
const isDatasetId = createEnumGuard(DATASET_IDS);

export function decodeBenchmarkDatasets(value: unknown): BenchmarkDatasetListResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.datasets) ||
    value.datasets.length === 0 ||
    !isDatasetId(value.default_dataset_id)
  ) {
    throw new Error('Invalid benchmark dataset response');
  }

  const datasets = value.datasets.map(decodeBenchmarkDatasetSummaryValue);
  if (!datasets.some((item) => item.dataset_id === value.default_dataset_id)) {
    throw new Error('Invalid default benchmark dataset');
  }

  return { datasets, default_dataset_id: value.default_dataset_id };
}

function warning(value: unknown): EvaluationDatasetWarning {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.code) ||
    value.code.length > 100 ||
    !isNonEmptyString(value.detail) ||
    value.detail.length > 300 ||
    !isNonNegativeInteger(value.count) ||
    value.count < 1
  ) {
    throw new Error('Invalid evaluation dataset warning');
  }
  return value as unknown as EvaluationDatasetWarning;
}

export function decodeEvaluationDatasetPreview(
  value: unknown,
): EvaluationDatasetPreview {
  if (
    !isRecord(value) ||
    value.schema_version !== 1 ||
    !isNonEmptyString(value.dataset_id) ||
    value.dataset_id.length > 100 ||
    !DATASET_ID_PATTERN.test(value.dataset_id) ||
    typeof value.digest !== 'string' ||
    !SHA256_PATTERN.test(value.digest) ||
    !isNonEmptyString(value.name) ||
    value.name.length > 100 ||
    !isNullableBoundedString(value.description, 300) ||
    !isNonNegativeInteger(value.case_count) ||
    value.case_count < 1 ||
    !isNonNegativeInteger(value.expected_hits) ||
    !isNonNegativeInteger(value.expected_misses) ||
    value.expected_hits + value.expected_misses !== value.case_count ||
    !Array.isArray(value.categories) ||
    value.categories.length === 0 ||
    !value.categories.every(
      (category) => isNonEmptyString(category) && category.length <= 100,
    ) ||
    !isNonNegativeInteger(value.decoded_bytes) ||
    value.decoded_bytes < 1 ||
    !Array.isArray(value.warnings) ||
    !isNonNegativeInteger(value.query_executions) ||
    value.query_executions < 1 ||
    !isNonNegativeInteger(value.threshold_projection_evaluations) ||
    value.threshold_projection_evaluations < 2 ||
    !isNonNegativeInteger(value.maximum_provider_calls) ||
    value.maximum_provider_calls < 1 ||
    value.provider_calls_made !== 0 ||
    !isRecord(value.limits) ||
    !isNonNegativeInteger(value.limits.max_cases) ||
    value.limits.max_cases < 1 ||
    !isNonNegativeInteger(value.limits.max_decoded_bytes) ||
    value.limits.max_decoded_bytes < 1 ||
    !isNonNegativeInteger(value.limits.max_workload_queries) ||
    value.limits.max_workload_queries < 1
  ) {
    throw new Error('Invalid evaluation dataset preview');
  }

  const warnings = value.warnings.map(warning);
  if (
    new Set(value.categories).size !== value.categories.length ||
    value.query_executions > value.limits.max_workload_queries ||
    value.case_count > value.limits.max_cases ||
    value.decoded_bytes > value.limits.max_decoded_bytes ||
    value.maximum_provider_calls !== value.query_executions
  ) {
    throw new Error('Invalid evaluation dataset preview accounting');
  }

  return {
    ...value,
    warnings,
  } as unknown as EvaluationDatasetPreview;
}

function importedCase(value: unknown): ImportedEvaluationCase {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.case_id) ||
    value.case_id.length > 100 ||
    !DATASET_ID_PATTERN.test(value.case_id) ||
    !isNonEmptyString(value.prompt) ||
    value.prompt.length > 2_000 ||
    typeof value.expected_cache_hit !== 'boolean' ||
    !isNullableBoundedString(value.expected_match_case_id, 100) ||
    !isNullableBoundedString(value.category, 100) ||
    !isNullableBoundedString(value.note, 500) ||
    (!value.expected_cache_hit && value.expected_match_case_id !== null)
  ) {
    throw new Error('Invalid persisted evaluation case');
  }

  return value as unknown as ImportedEvaluationCase;
}

function persistedMetadata(value: unknown): PersistedEvaluationDatasetMetadata {
  if (
    !isRecord(value) ||
    typeof value.dataset_id !== 'string' ||
    !UUID_PATTERN.test(value.dataset_id) ||
    typeof value.namespace !== 'string' ||
    !isCacheNamespace(value.namespace) ||
    !isNonEmptyString(value.name) ||
    value.name.length > 100 ||
    !isNullableBoundedString(value.description, 300) ||
    value.source_type !== 'imported' ||
    value.schema_version !== 1 ||
    typeof value.digest !== 'string' ||
    !SHA256_PATTERN.test(value.digest) ||
    !isNonNegativeInteger(value.case_count) ||
    value.case_count < 1 ||
    !isNonNegativeInteger(value.decoded_bytes) ||
    value.decoded_bytes < 1 ||
    !isTimezoneAwareIsoDate(value.created_at) ||
    !isTimezoneAwareIsoDate(value.expires_at) ||
    Date.parse(value.expires_at) <= Date.parse(value.created_at)
  ) {
    throw new Error('Invalid persisted evaluation dataset metadata');
  }

  return value as unknown as PersistedEvaluationDatasetMetadata;
}

export function decodePersistedEvaluationDatasets(
  value: unknown,
): PersistedEvaluationDatasetListResponse {
  if (
    !isRecord(value) ||
    (value.storage_mode !== 'session' && value.storage_mode !== 'postgres') ||
    typeof value.persistence_enabled !== 'boolean' ||
    !Array.isArray(value.items) ||
    !isNonNegativeInteger(value.total) ||
    !isNonNegativeInteger(value.offset) ||
    !isNonNegativeInteger(value.limit) ||
    value.limit < 1 ||
    value.limit > 100 ||
    typeof value.has_more !== 'boolean' ||
    !isRecord(value.limits) ||
    !isNonNegativeInteger(value.limits.default_retention_days) ||
    value.limits.default_retention_days < 1 ||
    !isNonNegativeInteger(value.limits.max_retention_days) ||
    value.limits.max_retention_days < 1 ||
    !isNonNegativeInteger(value.limits.max_persisted_per_namespace) ||
    value.limits.max_persisted_per_namespace < 1
  ) {
    throw new Error('Invalid persisted evaluation dataset catalog');
  }

  const items = value.items.map(persistedMetadata);
  if (
    value.persistence_enabled !== (value.storage_mode === 'postgres') ||
    items.length > value.limit ||
    value.has_more !== value.offset + items.length < value.total ||
    value.limits.default_retention_days > value.limits.max_retention_days ||
    (!value.persistence_enabled && (items.length > 0 || value.total > 0))
  ) {
    throw new Error('Invalid persisted evaluation dataset catalog accounting');
  }

  return {
    ...value,
    items,
  } as unknown as PersistedEvaluationDatasetListResponse;
}

export function decodePersistedEvaluationDatasetDetail(
  value: unknown,
): PersistedEvaluationDatasetDetail {
  const metadata = persistedMetadata(value);
  if (!isRecord(value) || !Array.isArray(value.cases)) {
    throw new Error('Invalid persisted evaluation dataset detail');
  }
  const cases = value.cases.map(importedCase);
  const caseIds = new Set<string>();
  for (const item of cases) {
    if (
      caseIds.has(item.case_id) ||
      (item.expected_match_case_id !== null &&
        !caseIds.has(item.expected_match_case_id))
    ) {
      throw new Error('Invalid persisted evaluation dataset case ordering');
    }
    caseIds.add(item.case_id);
  }
  if (cases.length !== metadata.case_count) {
    throw new Error('Invalid persisted evaluation dataset case count');
  }

  return { ...metadata, cases };
}

export function decodeDeletePersistedEvaluationDataset(
  value: unknown,
): DeletePersistedEvaluationDatasetResponse {
  if (
    !isRecord(value) ||
    value.deleted !== true ||
    typeof value.dataset_id !== 'string' ||
    !UUID_PATTERN.test(value.dataset_id) ||
    typeof value.namespace !== 'string' ||
    !isCacheNamespace(value.namespace)
  ) {
    throw new Error('Invalid persisted evaluation dataset deletion');
  }

  return value as unknown as DeletePersistedEvaluationDatasetResponse;
}
