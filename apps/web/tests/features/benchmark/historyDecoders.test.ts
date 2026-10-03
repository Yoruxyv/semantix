import { describe, expect, it } from 'vitest';

import {
  decodeDeleteEvaluationRunHistory,
  decodeEvaluationRunHistoryDetail,
  decodeEvaluationRunHistoryList,
} from '@/features/benchmark/api/historyDecoders';

import { benchmarkResult } from './support';

const historyItem = {
  run_id: benchmarkResult.run_id,
  namespace: 'tenant-a',
  terminal_state: 'completed' as const,
  accepted_at: '2026-07-17T09:59:59Z',
  started_at: benchmarkResult.started_at,
  completed_at: benchmarkResult.completed_at,
  expires_at: '2026-08-16T10:00:02Z',
  source_dataset_expires_at: null,
  dataset: benchmarkResult.dataset,
  reproducibility: benchmarkResult.reproducibility,
  metrics: benchmarkResult.metrics,
  failure_code: null,
  safe_failure_detail: null,
};

const historyDetail = {
  ...historyItem,
  threshold_evaluation_mode: 'frozen_candidate_projection' as const,
  threshold_evaluations: benchmarkResult.threshold_evaluations,
};

describe('evaluation run history decoders', () => {
  it('decodes a bounded retained history page and completed detail', () => {
    expect(
      decodeEvaluationRunHistoryList({
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [historyItem],
        total: 1,
        offset: 0,
        limit: 12,
        has_more: false,
      }),
    ).toEqual(
      expect.objectContaining({
        retention_enabled: true,
        items: [expect.objectContaining({ run_id: benchmarkResult.run_id })],
      }),
    );

    expect(decodeEvaluationRunHistoryDetail(historyDetail)).toEqual(
      expect.objectContaining({
        terminal_state: 'completed',
        threshold_evaluations: benchmarkResult.threshold_evaluations,
      }),
    );
  });

  it('accepts failed aggregate history only without metrics or thresholds', () => {
    const failed = {
      ...historyItem,
      terminal_state: 'failed' as const,
      metrics: null,
      failure_code: 'invalid_upstream_response',
      safe_failure_detail: 'The AI service returned an invalid response.',
      threshold_evaluation_mode: 'frozen_candidate_projection' as const,
      threshold_evaluations: [],
    };

    expect(decodeEvaluationRunHistoryDetail(failed)).toEqual(
      expect.objectContaining({
        terminal_state: 'failed',
        metrics: null,
        failure_code: 'invalid_upstream_response',
      }),
    );

    expect(() =>
      decodeEvaluationRunHistoryDetail({
        ...failed,
        metrics: benchmarkResult.metrics,
      }),
    ).toThrow(/history accounting/i);
  });

  it('rejects history whose retained expiry exceeds its persisted source', () => {
    const persisted = {
      ...historyItem,
      dataset: {
        ...historyItem.dataset,
        dataset_id: '123e4567-e89b-42d3-a456-426614174000',
        dataset_source: 'persisted' as const,
        schema_version: 1,
        version: '1',
      },
      reproducibility: {
        ...historyItem.reproducibility,
        dataset_id: '123e4567-e89b-42d3-a456-426614174000',
        dataset_source: 'persisted' as const,
        dataset_schema_version: 1,
        dataset_version: '1',
      },
      source_dataset_expires_at: '2026-07-20T10:00:00Z',
      expires_at: '2026-07-21T10:00:00Z',
    };

    expect(() =>
      decodeEvaluationRunHistoryList({
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [persisted],
        total: 1,
        offset: 0,
        limit: 12,
        has_more: false,
      }),
    ).toThrow(/history accounting/i);
  });

  it('decodes disabled history and namespace-scoped deletion contracts', () => {
    expect(
      decodeEvaluationRunHistoryList({
        storage_mode: 'disabled',
        retention_enabled: false,
        items: [],
        total: 0,
        offset: 0,
        limit: 12,
        has_more: false,
      }),
    ).toEqual({
      storage_mode: 'disabled',
      retention_enabled: false,
      items: [],
      total: 0,
      offset: 0,
      limit: 12,
      has_more: false,
    });

    expect(
      decodeDeleteEvaluationRunHistory({
        deleted: true,
        run_id: benchmarkResult.run_id,
        namespace: 'tenant-a',
      }),
    ).toEqual({
      deleted: true,
      run_id: benchmarkResult.run_id,
      namespace: 'tenant-a',
    });
  });
});
