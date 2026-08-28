import { useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';

import { runBenchmark } from '../api/benchmarkApi';
import type { ThresholdSweep } from '../lib/thresholdSweep';
import type { BenchmarkRunResponse, EvaluationDatasetPreview } from '../types';
import { requestFromForm, type BenchmarkForm } from './benchmarkController';

interface EvaluationRunWorkflowOptions {
  authIdentity: string;
  canRun: boolean;
  form: BenchmarkForm;
  hasRunnableDataset: boolean;
  historyNamespaceValid: boolean;
  importedDefinition: unknown;
  setError: Dispatch<SetStateAction<string | null>>;
  setResult: Dispatch<SetStateAction<BenchmarkRunResponse | null>>;
  setShowWarning: Dispatch<SetStateAction<boolean>>;
  setStatusMessage: Dispatch<SetStateAction<string>>;
  sweep: ThresholdSweep;
  validateDefinition: (definition: unknown) => Promise<EvaluationDatasetPreview | null>;
}

interface EvaluationRunWorkflow {
  isRunning: boolean;
  cancelRun: () => void;
  confirmRun: () => Promise<void>;
  reviewRun: () => Promise<void>;
}

export function useEvaluationRunWorkflow({
  authIdentity,
  canRun,
  form,
  hasRunnableDataset,
  historyNamespaceValid,
  importedDefinition,
  setError,
  setResult,
  setShowWarning,
  setStatusMessage,
  sweep,
  validateDefinition,
}: EvaluationRunWorkflowOptions): EvaluationRunWorkflow {
  const [isRunning, setIsRunning] = useState(false);
  const activeRun = useRef<AbortController | null>(null);
  const runSequence = useRef(0);
  const previousPrincipal = useRef<string | null>(null);

  useEffect(() => {
    if (previousPrincipal.current === null) {
      previousPrincipal.current = authIdentity;
      return;
    }
    if (previousPrincipal.current !== authIdentity) {
      previousPrincipal.current = authIdentity;
      runSequence.current += 1;
      activeRun.current?.abort();
      activeRun.current = null;
      setIsRunning(false);
      setResult(null);
      setShowWarning(false);
      setError(null);
      setStatusMessage('');
    }
  }, [authIdentity, setError, setResult, setShowWarning, setStatusMessage]);

  useEffect(
    () => () => {
      runSequence.current += 1;
      activeRun.current?.abort();
      activeRun.current = null;
    },
    [],
  );

  async function reviewRun(): Promise<void> {
    if (
      !canRun ||
      sweep.error !== null ||
      !hasRunnableDataset ||
      !historyNamespaceValid
    ) {
      return;
    }
    if (form.datasetSource === 'custom') {
      if (importedDefinition === null) {
        return;
      }
      const validated = await validateDefinition(importedDefinition);
      if (validated === null) {
        return;
      }
    }
    setShowWarning(true);
  }

  async function confirmRun(): Promise<void> {
    if (
      !canRun ||
      !hasRunnableDataset ||
      !historyNamespaceValid ||
      sweep.error !== null ||
      (form.datasetSource === 'custom' && importedDefinition === null)
    ) {
      return;
    }
    const controller = new AbortController();
    const runId = runSequence.current + 1;
    runSequence.current = runId;
    activeRun.current?.abort();
    activeRun.current = controller;
    setShowWarning(false);
    setIsRunning(true);
    setError(null);
    setStatusMessage('Evaluation run started.');

    try {
      const response = await runBenchmark(
        requestFromForm(form, sweep.thresholds, importedDefinition),
        controller.signal,
      );
      if (controller.signal.aborted || runId !== runSequence.current) {
        return;
      }

      if (!response.ok) {
        setError(response.error.detail ?? 'The evaluation run failed.');
        setStatusMessage('Evaluation run failed.');
        return;
      }
      setResult(response.data);
      setStatusMessage('Evaluation run completed. Results are available below.');
    } finally {
      if (runId === runSequence.current) {
        activeRun.current = null;
        setIsRunning(false);
      }
    }
  }

  return {
    isRunning,
    cancelRun: () => setShowWarning(false),
    confirmRun,
    reviewRun,
  };
}
