import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  canPersistEvaluationDatasets,
  canRunBenchmarks,
} from '@/features/auth/permissions';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { benchmarkDatasetKeys } from '@/shared/query/queryKeys';

import { getBenchmarkDatasets } from '../api/benchmarkApi';
import { compileThresholdSweep } from '../lib/thresholdSweep';
import type { BenchmarkDatasetSummary, BenchmarkRunResponse } from '../types';
import {
  BENCHMARK_DATASET_GC_TIME_MS,
  BENCHMARK_DATASET_STALE_TIME_MS,
  DEFAULT_BENCHMARK_FORM,
  customSummary,
  historyNamespacePolicy,
  persistedSummary,
  type BenchmarkController,
  type BenchmarkForm,
} from './benchmarkController';
import { useEvaluationDatasetWorkflow } from './useEvaluationDatasetWorkflow';
import { useEvaluationRunWorkflow } from './useEvaluationRunWorkflow';

export {
  BENCHMARK_DATASET_GC_TIME_MS,
  BENCHMARK_DATASET_STALE_TIME_MS,
  EVALUATION_IMPORT_FILE_MAX_BYTES,
} from './benchmarkController';
export type { BenchmarkController, BenchmarkForm } from './benchmarkController';

export function useBenchmark(): BenchmarkController {
  const auth = useAuth();
  const [form, setForm] = useState<BenchmarkForm>(DEFAULT_BENCHMARK_FORM);
  const [result, setResult] = useState<BenchmarkRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWarning, setShowWarning] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const hasAppliedDefaultDataset = useRef(false);
  const previousPrincipal = useRef<string | null>(null);

  const datasetQuery = useQuery({
    queryKey: benchmarkDatasetKeys.catalog(),
    queryFn: async ({ signal }) =>
      dataFromApiResult(await getBenchmarkDatasets(signal)),
    staleTime: BENCHMARK_DATASET_STALE_TIME_MS,
    gcTime: BENCHMARK_DATASET_GC_TIME_MS,
  });

  useEffect(() => {
    if (datasetQuery.data === undefined || hasAppliedDefaultDataset.current) {
      return;
    }

    hasAppliedDefaultDataset.current = true;
    setForm((current) => ({
      ...current,
      datasetId: datasetQuery.data.default_dataset_id,
    }));
  }, [datasetQuery.data]);

  const authIdentity = useMemo(
    () =>
      `${auth.status}:${auth.session?.name ?? ''}:${
        auth.session?.role ?? ''
      }:${auth.session?.namespaces.join(',') ?? ''}`,
    [auth.session, auth.status],
  );

  useEffect(() => {
    if (previousPrincipal.current === null) {
      previousPrincipal.current = authIdentity;
      return;
    }
    if (previousPrincipal.current !== authIdentity) {
      previousPrincipal.current = authIdentity;
      setForm((current) => ({
        ...current,
        datasetSource: 'builtin',
        persistedDatasetId: '',
        persistedNamespace: '',
        historyNamespace: '',
      }));
    }
  }, [authIdentity]);

  const datasets = datasetQuery.data?.datasets ?? [];
  const datasetsLoading = datasetQuery.data === undefined && datasetQuery.isPending;
  const datasetError = datasetQuery.isError
    ? (apiErrorFromUnknown(datasetQuery.error).detail ??
      'Evaluation datasets could not be loaded.')
    : null;
  const canRun = canRunBenchmarks(auth.status, auth.session);
  const canSaveImport = canPersistEvaluationDatasets(auth.status, auth.session);

  const { required: historyNamespaceRequired, valid: historyNamespaceValid } =
    historyNamespacePolicy(
      auth.status,
      auth.session?.namespaces ?? [],
      form.datasetSource,
      form.historyNamespace,
    );

  const sweep = compileThresholdSweep(
    form.sweepStart,
    form.sweepEnd,
    form.sweepStep,
    form.threshold,
  );

  const datasetWorkflow = useEvaluationDatasetWorkflow({
    authIdentity,
    canSaveImport,
    form,
    setError,
    setForm,
    setResult,
    setShowWarning,
    setStatusMessage,
    sweep,
  });

  const builtinDataset =
    datasets.find((dataset) => dataset.dataset_id === form.datasetId) ?? null;
  let selectedDataset: BenchmarkDatasetSummary | null = builtinDataset;
  if (form.datasetSource === 'custom') {
    selectedDataset =
      datasetWorkflow.preview === null ? null : customSummary(datasetWorkflow.preview);
  } else if (form.datasetSource === 'persisted') {
    selectedDataset =
      datasetWorkflow.persistedDataset === null
        ? null
        : persistedSummary(datasetWorkflow.persistedDataset);
  }

  let hasRunnableDataset = builtinDataset !== null;
  if (form.datasetSource === 'custom') {
    hasRunnableDataset =
      datasetWorkflow.importedDefinition !== null && datasetWorkflow.preview !== null;
  } else if (form.datasetSource === 'persisted') {
    hasRunnableDataset =
      datasetWorkflow.persistedDataset !== null &&
      datasetWorkflow.persistedDataset.dataset_id === form.persistedDatasetId &&
      datasetWorkflow.persistedDataset.namespace === form.persistedNamespace;
  }

  const runWorkflow = useEvaluationRunWorkflow({
    authIdentity,
    canRun,
    form,
    hasRunnableDataset,
    historyNamespaceValid,
    importedDefinition: datasetWorkflow.importedDefinition,
    setError,
    setResult,
    setShowWarning,
    setStatusMessage,
    sweep,
    validateDefinition: datasetWorkflow.validateDefinition,
  });

  return {
    datasets,
    datasetsLoading,
    datasetsRefreshing: datasetQuery.data !== undefined && datasetQuery.isFetching,
    canRun,
    canSaveImport,
    error: error ?? datasetError,
    form,
    historyNamespaceRequired,
    historyNamespaceValid,
    importError: datasetWorkflow.importError,
    importFileName: datasetWorkflow.importFileName,
    importIssues: datasetWorkflow.importIssues,
    isRunning: runWorkflow.isRunning,
    isSavingImport: datasetWorkflow.isSavingImport,
    isValidatingImport: datasetWorkflow.isValidatingImport,
    preview: datasetWorkflow.preview,
    persistedDataset: datasetWorkflow.persistedDataset,
    result,
    selectedDataset,
    showWarning,
    statusMessage,
    sweep,
    cancelRun: runWorkflow.cancelRun,
    clearPersistedSelection: datasetWorkflow.clearPersistedSelection,
    confirmRun: runWorkflow.confirmRun,
    removeImport: datasetWorkflow.clearImport,
    reviewRun: runWorkflow.reviewRun,
    saveImport: datasetWorkflow.saveImport,
    selectPersistedDataset: datasetWorkflow.selectPersistedDataset,
    selectImportFile: datasetWorkflow.selectImportFile,
    setForm,
  };
}
