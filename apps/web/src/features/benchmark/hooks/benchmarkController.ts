import type { Dispatch, SetStateAction } from 'react';

import type { AuthStatus } from '@/features/auth/context/AuthContext';
import { isCacheNamespace } from '@/features/cache/namespace';
import type { ApiValidationIssue } from '@/shared/api/types';

import type { ThresholdSweep } from '../lib/thresholdSweep';
import type {
  BenchmarkDatasetId,
  BenchmarkDatasetSummary,
  BenchmarkRunResponse,
  EvaluationDatasetPreview,
  EvaluationRunRequest,
  PersistedEvaluationDatasetDetail,
} from '../types';

export const BENCHMARK_DATASET_STALE_TIME_MS = 10 * 60 * 1_000;
export const BENCHMARK_DATASET_GC_TIME_MS = 30 * 60 * 1_000;
export const EVALUATION_IMPORT_FILE_MAX_BYTES = 65_536;

export interface BenchmarkForm {
  datasetId: BenchmarkDatasetId;
  datasetSource: 'builtin' | 'custom' | 'persisted';
  persistedDatasetId: string;
  persistedNamespace: string;
  historyNamespace: string;
  threshold: number;
  repetitions: number;
  resetCacheBeforeRun: boolean;
  costPerRequestUsd: number;
  costPer1kTokensUsd: number;
  sweepStart: number;
  sweepEnd: number;
  sweepStep: number;
}

export interface BenchmarkController {
  datasets: BenchmarkDatasetSummary[];
  datasetsLoading: boolean;
  datasetsRefreshing: boolean;
  canRun: boolean;
  canSaveImport: boolean;
  error: string | null;
  form: BenchmarkForm;
  historyNamespaceRequired: boolean;
  historyNamespaceValid: boolean;
  importError: string | null;
  importFileName: string | null;
  importIssues: ApiValidationIssue[];
  isRunning: boolean;
  isSavingImport: boolean;
  isValidatingImport: boolean;
  preview: EvaluationDatasetPreview | null;
  persistedDataset: PersistedEvaluationDatasetDetail | null;
  result: BenchmarkRunResponse | null;
  selectedDataset: BenchmarkDatasetSummary | null;
  showWarning: boolean;
  statusMessage: string;
  sweep: ThresholdSweep;
  cancelRun: () => void;
  clearPersistedSelection: (datasetId: string) => void;
  confirmRun: () => Promise<void>;
  removeImport: () => void;
  reviewRun: () => Promise<void>;
  saveImport: (
    namespace: string | undefined,
    retentionDays: number,
  ) => Promise<PersistedEvaluationDatasetDetail | null>;
  selectPersistedDataset: (dataset: PersistedEvaluationDatasetDetail) => void;
  selectImportFile: (file: File) => Promise<void>;
  setForm: Dispatch<SetStateAction<BenchmarkForm>>;
}

interface HistoryNamespacePolicy {
  required: boolean;
  valid: boolean;
}

export function historyNamespacePolicy(
  authStatus: AuthStatus,
  namespaces: readonly string[],
  datasetSource: BenchmarkForm['datasetSource'],
  requestedNamespace: string,
): HistoryNamespacePolicy {
  if (datasetSource !== 'builtin') {
    return { required: false, valid: true };
  }

  const concreteNamespaces = namespaces.filter((namespace) => namespace !== '*');
  const hasGlobalNamespace = namespaces.includes('*');
  const required =
    authStatus === 'disabled' ||
    (authStatus === 'authenticated' &&
      (hasGlobalNamespace || concreteNamespaces.length !== 1));
  const requested = requestedNamespace.trim();

  if (requested === '') {
    return { required, valid: !required };
  }

  if (!isCacheNamespace(requested)) {
    return { required, valid: false };
  }

  if (
    authStatus === 'authenticated' &&
    !hasGlobalNamespace &&
    !concreteNamespaces.includes(requested)
  ) {
    return { required, valid: false };
  }

  return { required, valid: true };
}

export const DEFAULT_BENCHMARK_FORM: BenchmarkForm = {
  datasetId: 'quick',
  datasetSource: 'builtin',
  persistedDatasetId: '',
  persistedNamespace: '',
  historyNamespace: '',
  threshold: 0.92,
  repetitions: 1,
  resetCacheBeforeRun: true,
  costPerRequestUsd: 0,
  costPer1kTokensUsd: 0,
  sweepStart: 0.7,
  sweepEnd: 0.98,
  sweepStep: 0.05,
};

export function customSummary(
  preview: EvaluationDatasetPreview,
): BenchmarkDatasetSummary {
  return {
    dataset_id: preview.dataset_id,
    dataset_source: 'inline',
    schema_version: preview.schema_version,
    version: String(preview.schema_version),
    digest: preview.digest,
    name: preview.name,
    description: preview.description ?? 'Session-local imported evaluation dataset.',
    query_count: preview.case_count,
    expected_hits: preview.expected_hits,
    expected_misses: preview.expected_misses,
    categories: preview.categories,
  };
}

export function persistedSummary(
  detail: PersistedEvaluationDatasetDetail,
): BenchmarkDatasetSummary {
  const expectedHits = detail.cases.filter((item) => item.expected_cache_hit).length;
  const categories = [
    ...new Set(detail.cases.map((item) => item.category ?? 'uncategorized')),
  ];
  return {
    dataset_id: detail.dataset_id,
    dataset_source: 'persisted',
    schema_version: detail.schema_version,
    version: String(detail.schema_version),
    digest: detail.digest,
    name: detail.name,
    description: detail.description ?? 'Persisted imported evaluation dataset.',
    query_count: detail.case_count,
    expected_hits: expectedHits,
    expected_misses: detail.case_count - expectedHits,
    categories,
  };
}

export function requestFromForm(
  form: BenchmarkForm,
  evaluationThresholds: number[],
  importedDefinition: unknown,
): EvaluationRunRequest {
  let datasetSource: EvaluationRunRequest['dataset_source'];
  if (form.datasetSource === 'custom') {
    datasetSource = { kind: 'inline', definition: importedDefinition };
  } else if (form.datasetSource === 'persisted') {
    datasetSource = {
      kind: 'persisted',
      dataset_id: form.persistedDatasetId,
      namespace: form.persistedNamespace,
    };
  } else {
    datasetSource = { kind: 'builtin', dataset_id: form.datasetId };
  }

  return {
    ...(form.datasetSource === 'builtin' && form.historyNamespace.trim() !== ''
      ? { history_namespace: form.historyNamespace.trim() }
      : {}),
    dataset_source: datasetSource,
    threshold: form.threshold,
    evaluation_thresholds: evaluationThresholds,
    repetitions: form.repetitions,
    reset_cache_before_run: form.resetCacheBeforeRun,
    estimated_cost_per_request_usd: form.costPerRequestUsd,
    estimated_cost_per_1k_tokens_usd: form.costPer1kTokensUsd,
    allow_external_provider_calls: true,
  };
}
