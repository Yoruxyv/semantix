import { useMutation } from '@tanstack/react-query';
import { useCallback, useState } from 'react';

import { compareEvaluationRuns } from '../api/comparisonApi';
import type { EvaluationRunComparisonResponse } from '../comparisonTypes';
import type { EvaluationRunHistoryItem } from '../types';
import { dataFromApiResult } from '@/shared/query/apiResult';

export interface EvaluationRunComparisonController {
  selectedRuns: EvaluationRunHistoryItem[];
  result: EvaluationRunComparisonResponse | undefined;
  error: unknown;
  isPending: boolean;
  canCompare: boolean;
  toggleRun: (item: EvaluationRunHistoryItem) => void;
  removeRun: (runId: string) => void;
  clear: () => void;
  compare: () => void;
}

export function useEvaluationRunComparison(): EvaluationRunComparisonController {
  const [selectedRuns, setSelectedRuns] = useState<EvaluationRunHistoryItem[]>([]);

  const comparison = useMutation({
    mutationFn: async (
      runs: readonly [EvaluationRunHistoryItem, EvaluationRunHistoryItem],
    ) =>
      dataFromApiResult(
        await compareEvaluationRuns({
          baseline_run_id: runs[0].run_id,
          candidate_run_id: runs[1].run_id,
        }),
      ),
  });

  const resetResult = comparison.reset;

  const toggleRun = useCallback(
    (item: EvaluationRunHistoryItem) => {
      resetResult();
      setSelectedRuns((current) => {
        const existingIndex = current.findIndex(
          (selected) => selected.run_id === item.run_id,
        );
        if (existingIndex >= 0) {
          return current.filter((selected) => selected.run_id !== item.run_id);
        }
        if (current.length >= 2) {
          return current;
        }
        return [...current, item];
      });
    },
    [resetResult],
  );

  const removeRun = useCallback(
    (runId: string) => {
      resetResult();
      setSelectedRuns((current) =>
        current.filter((selected) => selected.run_id !== runId),
      );
    },
    [resetResult],
  );

  const clear = useCallback(() => {
    resetResult();
    setSelectedRuns([]);
  }, [resetResult]);

  const compare = useCallback(() => {
    if (selectedRuns.length !== 2) {
      return;
    }
    const baseline = selectedRuns[0];
    const candidate = selectedRuns[1];
    if (baseline === undefined || candidate === undefined) {
      return;
    }
    comparison.mutate([baseline, candidate]);
  }, [comparison, selectedRuns]);

  return {
    selectedRuns,
    result: comparison.data,
    error: comparison.error,
    isPending: comparison.isPending,
    canCompare: selectedRuns.length === 2 && !comparison.isPending,
    toggleRun,
    removeRun,
    clear,
    compare,
  };
}
