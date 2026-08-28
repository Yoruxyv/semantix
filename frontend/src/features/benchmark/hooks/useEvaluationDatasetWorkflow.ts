import { useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import type { ApiValidationIssue } from '@/shared/api/types';
import { benchmarkDatasetKeys } from '@/shared/query/queryKeys';

import {
  persistEvaluationDataset,
  validateEvaluationDataset,
} from '../api/benchmarkApi';
import type { ThresholdSweep } from '../lib/thresholdSweep';
import type {
  BenchmarkRunResponse,
  EvaluationDatasetPreview,
  PersistedEvaluationDatasetDetail,
} from '../types';
import {
  EVALUATION_IMPORT_FILE_MAX_BYTES,
  type BenchmarkForm,
} from './benchmarkController';

interface EvaluationDatasetWorkflowOptions {
  authIdentity: string;
  canSaveImport: boolean;
  form: BenchmarkForm;
  setError: Dispatch<SetStateAction<string | null>>;
  setForm: Dispatch<SetStateAction<BenchmarkForm>>;
  setResult: Dispatch<SetStateAction<BenchmarkRunResponse | null>>;
  setShowWarning: Dispatch<SetStateAction<boolean>>;
  setStatusMessage: Dispatch<SetStateAction<string>>;
  sweep: ThresholdSweep;
}

interface EvaluationDatasetWorkflow {
  importedDefinition: unknown;
  importError: string | null;
  importFileName: string | null;
  importIssues: ApiValidationIssue[];
  isSavingImport: boolean;
  isValidatingImport: boolean;
  persistedDataset: PersistedEvaluationDatasetDetail | null;
  preview: EvaluationDatasetPreview | null;
  clearImport: () => void;
  clearPersistedSelection: (datasetId: string) => void;
  saveImport: (
    namespace: string | undefined,
    retentionDays: number,
  ) => Promise<PersistedEvaluationDatasetDetail | null>;
  selectImportFile: (file: File) => Promise<void>;
  selectPersistedDataset: (dataset: PersistedEvaluationDatasetDetail) => void;
  validateDefinition: (definition: unknown) => Promise<EvaluationDatasetPreview | null>;
}

export function useEvaluationDatasetWorkflow({
  authIdentity,
  canSaveImport,
  form,
  setError,
  setForm,
  setResult,
  setShowWarning,
  setStatusMessage,
  sweep,
}: EvaluationDatasetWorkflowOptions): EvaluationDatasetWorkflow {
  const queryClient = useQueryClient();
  const [importedDefinition, setImportedDefinition] = useState<unknown>(null);
  const [importFileName, setImportFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<EvaluationDatasetPreview | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importIssues, setImportIssues] = useState<ApiValidationIssue[]>([]);
  const [isValidatingImport, setIsValidatingImport] = useState(false);
  const [isSavingImport, setIsSavingImport] = useState(false);
  const [persistedDataset, setPersistedDataset] =
    useState<PersistedEvaluationDatasetDetail | null>(null);
  const activeSave = useRef<AbortController | null>(null);
  const activeValidation = useRef<AbortController | null>(null);
  const saveSequence = useRef(0);
  const validationSequence = useRef(0);
  const previousPrincipal = useRef<string | null>(null);

  function clearImport(): void {
    validationSequence.current += 1;
    activeValidation.current?.abort();
    activeValidation.current = null;
    setImportedDefinition(null);
    setImportFileName(null);
    setPreview(null);
    setImportError(null);
    setImportIssues([]);
    setIsValidatingImport(false);
    setShowWarning(false);
    setResult(null);
  }

  useEffect(() => {
    if (previousPrincipal.current === null) {
      previousPrincipal.current = authIdentity;
      return;
    }
    if (previousPrincipal.current !== authIdentity) {
      previousPrincipal.current = authIdentity;
      saveSequence.current += 1;
      validationSequence.current += 1;
      activeSave.current?.abort();
      activeValidation.current?.abort();
      activeSave.current = null;
      activeValidation.current = null;
      setIsSavingImport(false);
      setImportedDefinition(null);
      setImportFileName(null);
      setPreview(null);
      setImportError(null);
      setImportIssues([]);
      setIsValidatingImport(false);
      setShowWarning(false);
      setResult(null);
      setPersistedDataset(null);
    }
  }, [authIdentity, setResult, setShowWarning]);

  useEffect(
    () => () => {
      saveSequence.current += 1;
      validationSequence.current += 1;
      activeSave.current?.abort();
      activeValidation.current?.abort();
      activeSave.current = null;
      activeValidation.current = null;
    },
    [],
  );

  async function validateDefinition(
    definition: unknown,
  ): Promise<EvaluationDatasetPreview | null> {
    const controller = new AbortController();
    const validationId = validationSequence.current + 1;
    validationSequence.current = validationId;
    activeValidation.current?.abort();
    activeValidation.current = controller;
    setIsValidatingImport(true);
    setImportError(null);
    setImportIssues([]);

    try {
      const response = await validateEvaluationDataset(
        {
          dataset: definition,
          repetitions: form.repetitions,
          threshold_count: sweep.thresholds.length,
        },
        controller.signal,
      );
      if (controller.signal.aborted || validationId !== validationSequence.current) {
        return null;
      }
      if (!response.ok) {
        setPreview(null);
        setImportError(response.error.detail ?? 'The imported dataset is invalid.');
        setImportIssues(response.error.issues ?? []);
        return null;
      }
      setPreview(response.data);
      return response.data;
    } finally {
      if (validationId === validationSequence.current) {
        activeValidation.current = null;
        setIsValidatingImport(false);
      }
    }
  }

  async function selectImportFile(file: File): Promise<void> {
    clearImport();
    const selectionId = validationSequence.current;
    setImportFileName(file.name);
    setForm((current) => ({ ...current, datasetSource: 'custom' }));
    if (!file.name.toLowerCase().endsWith('.json')) {
      setImportError('Choose a JSON file with a .json extension.');
      return;
    }
    if (file.size > EVALUATION_IMPORT_FILE_MAX_BYTES) {
      setImportError(
        `The selected file exceeds ${EVALUATION_IMPORT_FILE_MAX_BYTES.toLocaleString()} bytes.`,
      );
      return;
    }

    let definition: unknown;
    try {
      definition = JSON.parse(await file.text()) as unknown;
    } catch {
      if (selectionId !== validationSequence.current) {
        return;
      }
      setImportError('The selected file is not valid JSON.');
      return;
    }
    if (selectionId !== validationSequence.current) {
      return;
    }
    setImportedDefinition(definition);
    await validateDefinition(definition);
  }

  async function saveImport(
    namespace: string | undefined,
    retentionDays: number,
  ): Promise<PersistedEvaluationDatasetDetail | null> {
    if (
      !canSaveImport ||
      importedDefinition === null ||
      preview === null ||
      !Number.isSafeInteger(retentionDays) ||
      retentionDays < 1
    ) {
      return null;
    }
    const controller = new AbortController();
    const saveId = saveSequence.current + 1;
    saveSequence.current = saveId;
    activeSave.current?.abort();
    activeSave.current = controller;
    setIsSavingImport(true);
    setError(null);
    setStatusMessage('Saving the validated dataset...');
    try {
      const response = await persistEvaluationDataset(
        {
          ...(namespace === undefined ? {} : { namespace }),
          dataset: importedDefinition,
          retention_days: retentionDays,
        },
        controller.signal,
      );
      if (controller.signal.aborted || saveId !== saveSequence.current) {
        return null;
      }
      if (!response.ok) {
        setError(response.error.detail ?? 'The validated dataset could not be saved.');
        setStatusMessage('Dataset save failed.');
        return null;
      }
      await queryClient.invalidateQueries({
        queryKey: benchmarkDatasetKeys.persisted(),
      });
      if (controller.signal.aborted || saveId !== saveSequence.current) {
        return null;
      }
      setStatusMessage(
        `Saved ${response.data.name} in namespace ${response.data.namespace}.`,
      );
      return response.data;
    } finally {
      if (saveId === saveSequence.current) {
        activeSave.current = null;
        setIsSavingImport(false);
      }
    }
  }

  function selectPersistedDataset(dataset: PersistedEvaluationDatasetDetail): void {
    setPersistedDataset(dataset);
    setForm((current) => ({
      ...current,
      datasetSource: 'persisted',
      persistedDatasetId: dataset.dataset_id,
      persistedNamespace: dataset.namespace,
    }));
    setResult(null);
    setShowWarning(false);
    setError(null);
    setStatusMessage(`Selected persisted dataset ${dataset.name} for the next run.`);
  }

  function clearPersistedSelection(datasetId: string): void {
    setPersistedDataset((current) =>
      current?.dataset_id === datasetId ? null : current,
    );
    setForm((current) =>
      current.persistedDatasetId === datasetId
        ? {
            ...current,
            datasetSource: 'builtin',
            persistedDatasetId: '',
            persistedNamespace: '',
          }
        : current,
    );
    setShowWarning(false);
  }

  return {
    importedDefinition,
    importError,
    importFileName,
    importIssues,
    isSavingImport,
    isValidatingImport,
    persistedDataset,
    preview,
    clearImport,
    clearPersistedSelection,
    saveImport,
    selectImportFile,
    selectPersistedDataset,
    validateDefinition,
  };
}
