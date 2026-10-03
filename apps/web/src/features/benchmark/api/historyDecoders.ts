import { isCacheNamespace } from '@/features/cache/namespace';
import { isIsoDate, isNonNegativeInteger, isRecord } from '@/shared/api/validators';

import type {
  DeleteEvaluationRunHistoryResponse,
  EvaluationRunHistoryDetail,
  EvaluationRunHistoryItem,
  EvaluationRunHistoryListResponse,
  EvaluationRunTerminalState,
} from '../types';
import {
  decodeBenchmarkDatasetSummaryValue,
  decodeBenchmarkMetricsValue,
  decodeBenchmarkReproducibilityValue,
  decodeThresholdEvaluationValue,
} from './benchmarkDecoders';

const RUN_ID_PATTERN = /^[a-f0-9]{32}$/;
const TIMEZONE_SUFFIX_PATTERN = /(Z|[+-]\d{2}:\d{2})$/i;
const TERMINAL_STATES: readonly EvaluationRunTerminalState[] = [
  'completed',
  'failed',
  'timed_out',
];

function isTimezoneAwareIsoDate(value: unknown): value is string {
  return isIsoDate(value) && TIMEZONE_SUFFIX_PATTERN.test(value);
}

function isTerminalState(value: unknown): value is EvaluationRunTerminalState {
  return (
    typeof value === 'string' &&
    TERMINAL_STATES.includes(value as EvaluationRunTerminalState)
  );
}

function isNullableBoundedString(
  value: unknown,
  maximumLength: number,
): value is string | null {
  return value === null || (typeof value === 'string' && value.length <= maximumLength);
}

function historyItem(value: unknown): EvaluationRunHistoryItem {
  if (
    !isRecord(value) ||
    typeof value.run_id !== 'string' ||
    !RUN_ID_PATTERN.test(value.run_id) ||
    typeof value.namespace !== 'string' ||
    !isCacheNamespace(value.namespace) ||
    !isTerminalState(value.terminal_state) ||
    !isTimezoneAwareIsoDate(value.accepted_at) ||
    !isTimezoneAwareIsoDate(value.started_at) ||
    !isTimezoneAwareIsoDate(value.completed_at) ||
    !isTimezoneAwareIsoDate(value.expires_at) ||
    !(
      value.source_dataset_expires_at === null ||
      isTimezoneAwareIsoDate(value.source_dataset_expires_at)
    ) ||
    !isNullableBoundedString(value.failure_code, 100) ||
    !isNullableBoundedString(value.safe_failure_detail, 300)
  ) {
    throw new Error('Invalid evaluation run history item');
  }

  const decodedDataset = decodeBenchmarkDatasetSummaryValue(value.dataset);
  const decodedReproducibility = decodeBenchmarkReproducibilityValue(
    value.reproducibility,
  );
  const decodedMetrics =
    value.metrics === null ? null : decodeBenchmarkMetricsValue(value.metrics);

  const acceptedAt = Date.parse(value.accepted_at);
  const startedAt = Date.parse(value.started_at);
  const completedAt = Date.parse(value.completed_at);
  const expiresAt = Date.parse(value.expires_at);
  const sourceExpiresAt =
    value.source_dataset_expires_at === null
      ? null
      : Date.parse(value.source_dataset_expires_at);

  const datasetContractMatches =
    decodedReproducibility.dataset_id === decodedDataset.dataset_id &&
    decodedReproducibility.dataset_source === decodedDataset.dataset_source &&
    decodedReproducibility.dataset_schema_version === decodedDataset.schema_version &&
    decodedReproducibility.dataset_version === decodedDataset.version &&
    decodedReproducibility.dataset_digest === decodedDataset.digest;

  const persistedExpiryValid =
    decodedDataset.dataset_source !== 'persisted'
      ? value.source_dataset_expires_at === null
      : sourceExpiresAt !== null && expiresAt <= sourceExpiresAt;

  const terminalContractValid =
    value.terminal_state === 'completed'
      ? decodedMetrics !== null &&
        value.failure_code === null &&
        value.safe_failure_detail === null
      : decodedMetrics === null && value.failure_code !== null;

  if (
    decodedDataset.dataset_source === 'inline' ||
    acceptedAt > startedAt ||
    startedAt > completedAt ||
    completedAt >= expiresAt ||
    !datasetContractMatches ||
    !persistedExpiryValid ||
    !terminalContractValid
  ) {
    throw new Error('Invalid evaluation run history accounting');
  }

  return {
    run_id: value.run_id,
    namespace: value.namespace,
    terminal_state: value.terminal_state,
    accepted_at: value.accepted_at,
    started_at: value.started_at,
    completed_at: value.completed_at,
    expires_at: value.expires_at,
    source_dataset_expires_at: value.source_dataset_expires_at,
    dataset: decodedDataset,
    reproducibility: decodedReproducibility,
    metrics: decodedMetrics,
    failure_code: value.failure_code,
    safe_failure_detail: value.safe_failure_detail,
  };
}

export function decodeEvaluationRunHistoryList(
  value: unknown,
): EvaluationRunHistoryListResponse {
  if (
    !isRecord(value) ||
    (value.storage_mode !== 'disabled' && value.storage_mode !== 'postgres') ||
    typeof value.retention_enabled !== 'boolean' ||
    !Array.isArray(value.items) ||
    !isNonNegativeInteger(value.total) ||
    !isNonNegativeInteger(value.offset) ||
    !isNonNegativeInteger(value.limit) ||
    value.limit < 1 ||
    value.limit > 100 ||
    typeof value.has_more !== 'boolean'
  ) {
    throw new Error('Invalid evaluation run history list');
  }

  const items = value.items.map(historyItem);
  if (
    value.retention_enabled !== (value.storage_mode === 'postgres') ||
    items.length > value.limit ||
    value.has_more !== value.offset + items.length < value.total ||
    (!value.retention_enabled && (items.length > 0 || value.total > 0))
  ) {
    throw new Error('Invalid evaluation run history pagination');
  }

  return {
    storage_mode: value.storage_mode,
    retention_enabled: value.retention_enabled,
    items,
    total: value.total,
    offset: value.offset,
    limit: value.limit,
    has_more: value.has_more,
  };
}

export function decodeEvaluationRunHistoryDetail(
  value: unknown,
): EvaluationRunHistoryDetail {
  const item = historyItem(value);
  if (
    !isRecord(value) ||
    value.threshold_evaluation_mode !== 'frozen_candidate_projection' ||
    !Array.isArray(value.threshold_evaluations) ||
    value.threshold_evaluations.length > 15
  ) {
    throw new Error('Invalid evaluation run history detail');
  }

  const thresholdEvaluations = value.threshold_evaluations.map(
    decodeThresholdEvaluationValue,
  );

  if (item.terminal_state !== 'completed') {
    if (thresholdEvaluations.length !== 0) {
      throw new Error('Failed evaluation history cannot contain thresholds');
    }
  } else {
    const thresholds = thresholdEvaluations.map((evaluation) => evaluation.threshold);
    const measured = thresholdEvaluations.filter(
      (evaluation) => evaluation.result_kind === 'measured',
    );

    if (
      item.metrics === null ||
      thresholdEvaluations.length < 2 ||
      item.metrics.total_queries !==
        item.dataset.query_count * item.reproducibility.repetitions ||
      thresholds.length !== item.reproducibility.evaluation_thresholds.length ||
      thresholds.some(
        (threshold, index) =>
          threshold !== item.reproducibility.evaluation_thresholds[index],
      ) ||
      measured.length !== 1 ||
      measured[0]?.threshold !== item.reproducibility.measured_threshold
    ) {
      throw new Error('Invalid completed evaluation run history detail');
    }
  }

  return {
    ...item,
    threshold_evaluation_mode: value.threshold_evaluation_mode,
    threshold_evaluations: thresholdEvaluations,
  };
}

export function decodeDeleteEvaluationRunHistory(
  value: unknown,
): DeleteEvaluationRunHistoryResponse {
  if (
    !isRecord(value) ||
    value.deleted !== true ||
    typeof value.run_id !== 'string' ||
    !RUN_ID_PATTERN.test(value.run_id) ||
    typeof value.namespace !== 'string' ||
    !isCacheNamespace(value.namespace)
  ) {
    throw new Error('Invalid evaluation run history deletion');
  }

  return {
    deleted: true,
    run_id: value.run_id,
    namespace: value.namespace,
  };
}
