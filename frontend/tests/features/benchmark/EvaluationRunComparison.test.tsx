import type { QueryClient } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { compareEvaluationRuns } from '@/features/benchmark/api/comparisonApi';
import type { EvaluationRunComparisonResponse } from '@/features/benchmark/comparisonTypes';
import {
  deleteEvaluationRunHistory,
  getEvaluationRunHistory,
  getEvaluationRunHistoryDetail,
} from '@/features/benchmark/api/benchmarkApi';
import { EvaluationRunHistory } from '@/features/benchmark/components/history/EvaluationRunHistory';
import type { EvaluationRunHistoryDetail } from '@/features/benchmark/types';
import { useAuth } from '@/features/auth/hooks/useAuth';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { benchmarkResult } from './support';

vi.mock('../../../src/features/benchmark/api/benchmarkApi');
vi.mock('../../../src/features/benchmark/api/comparisonApi');
vi.mock('../../../src/features/auth/hooks/useAuth');

function detail(runId: string): EvaluationRunHistoryDetail {
  return {
    run_id: runId,
    namespace: 'tenant-a',
    terminal_state: 'completed',
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
    threshold_evaluation_mode: 'frozen_candidate_projection',
    threshold_evaluations: benchmarkResult.threshold_evaluations,
  };
}

function comparisonResponse(
  baseline: EvaluationRunHistoryDetail,
  candidate: EvaluationRunHistoryDetail,
): EvaluationRunComparisonResponse {
  return {
    baseline,
    candidate,
    compatibility: {
      status: 'compatible' as const,
      can_compare: true,
      incompatibilities: [],
      warnings: [],
      case_evidence: 'not_retained' as const,
      opaque_configuration_fingerprint_matches: true,
    },
    metric_deltas: {
      measured_threshold: 0,
      total_queries: 0,
      cache_hits: 0,
      cache_misses: 0,
      provider_calls: 0,
      provider_calls_avoided: 0,
      hit_rate: 0,
      average_latency_ms: 0,
      median_latency_ms: 0,
      p95_latency_ms: 0,
      average_cache_hit_latency_ms: 0,
      average_cache_miss_latency_ms: 0,
      estimated_latency_saved_ms: 0,
      estimated_provider_cost_saved_usd: 0,
      estimated_tokens_saved: 0,
      true_positive_hits: 0,
      true_negative_misses: 0,
      false_positive_hits: 0,
      false_negative_misses: 0,
      precision: 0,
      recall: 0,
      f1_score: 0,
    },
    threshold_deltas: benchmarkResult.threshold_evaluations.map((evaluation) => ({
      threshold: evaluation.threshold,
      baseline_result_kind: evaluation.result_kind,
      candidate_result_kind: evaluation.result_kind,
      hit_rate: 0,
      precision: 0,
      recall: 0,
      f1_score: 0,
      average_latency_ms: 0,
      provider_calls_avoided: 0,
      true_positive_hits: 0,
      true_negative_misses: 0,
      false_positive_hits: 0,
      false_negative_misses: 0,
    })),
  };
}

let queryClient: QueryClient;

function renderHistory() {
  return render(<EvaluationRunHistory />, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>{children}</QueryTestProvider>
    ),
  });
}

describe('evaluation run comparison UI', () => {
  beforeEach(() => {
    queryClient = createTestQueryClient();
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'comparison-viewer',
        role: 'viewer',
        namespaces: ['tenant-a'],
      },
      status: 'authenticated',
    });

    const baseline = detail('a'.repeat(32));
    const candidate = detail('b'.repeat(32));

    vi.mocked(getEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [baseline, candidate],
        total: 2,
        offset: 0,
        limit: 12,
        has_more: false,
      },
    });
    vi.mocked(getEvaluationRunHistoryDetail).mockResolvedValue({
      ok: true,
      data: baseline,
    });
    vi.mocked(deleteEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        deleted: true,
        run_id: baseline.run_id,
        namespace: baseline.namespace,
      },
    });
    vi.mocked(compareEvaluationRuns).mockResolvedValue({
      ok: true,
      data: comparisonResponse(baseline, candidate),
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('selects baseline then candidate and renders server-backed deltas', async () => {
    renderHistory();

    const selectButtons = await screen.findAllByRole('button', {
      name: 'Select to compare',
    });
    expect(selectButtons).toHaveLength(2);

    fireEvent.click(selectButtons[0]!);
    expect(screen.getByRole('button', { name: 'Baseline selected' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Select to compare' }));
    expect(screen.getByRole('button', { name: 'Candidate selected' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Compare selected runs' }));

    await waitFor(() =>
      expect(compareEvaluationRuns).toHaveBeenCalledWith({
        baseline_run_id: 'a'.repeat(32),
        candidate_run_id: 'b'.repeat(32),
      }),
    );

    expect(await screen.findByText('Comparison result')).toBeTruthy();
    expect(screen.getByText('Compatible comparison')).toBeTruthy();
    expect(screen.getByText('Aggregate metric deltas')).toBeTruthy();
    expect(screen.getByText('Shared threshold projections')).toBeTruthy();
    expect(screen.getByText(/candidate minus baseline/i)).toBeTruthy();
  });

  it('keeps warned comparisons visible with explicit caveats', async () => {
    const baseline = detail('a'.repeat(32));
    const candidate = detail('b'.repeat(32));
    const warned = comparisonResponse(baseline, candidate);
    warned.compatibility = {
      ...warned.compatibility,
      status: 'warning',
      warnings: [
        {
          code: 'generation_configuration_changed',
          detail: 'Safe generation configuration fingerprints differ.',
        },
      ],
    };
    vi.mocked(compareEvaluationRuns).mockResolvedValue({
      ok: true,
      data: warned,
    });

    renderHistory();

    const selectButtons = await screen.findAllByRole('button', {
      name: 'Select to compare',
    });
    fireEvent.click(selectButtons[0]!);
    fireEvent.click(screen.getByRole('button', { name: 'Select to compare' }));
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected runs' }));

    expect(await screen.findByText('Comparison caveats')).toBeTruthy();
    expect(screen.getByText(/generation_configuration_changed/)).toBeTruthy();
    expect(screen.getByText('Aggregate metric deltas')).toBeTruthy();
  });

  it('shows server blockers without rendering metric deltas', async () => {
    const baseline = detail('a'.repeat(32));
    const candidate = {
      ...detail('b'.repeat(32)),
      namespace: 'tenant-b',
    };
    vi.mocked(getEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [baseline, candidate],
        total: 2,
        offset: 0,
        limit: 12,
        has_more: false,
      },
    });
    vi.mocked(compareEvaluationRuns).mockResolvedValue({
      ok: true,
      data: {
        baseline,
        candidate,
        compatibility: {
          status: 'incompatible',
          can_compare: false,
          incompatibilities: [
            {
              code: 'namespace_mismatch',
              detail: 'Run namespaces differ; cross-namespace comparison is blocked.',
            },
          ],
          warnings: [],
          case_evidence: 'not_retained',
          opaque_configuration_fingerprint_matches: true,
        },
        metric_deltas: null,
        threshold_deltas: [],
      },
    });

    renderHistory();

    const selectButtons = await screen.findAllByRole('button', {
      name: 'Select to compare',
    });
    fireEvent.click(selectButtons[0]!);
    fireEvent.click(screen.getByRole('button', { name: 'Select to compare' }));
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected runs' }));

    expect(await screen.findByText('Comparison blocked')).toBeTruthy();
    expect(screen.getByText(/namespace_mismatch/)).toBeTruthy();
    expect(screen.queryByText('Aggregate metric deltas')).toBeNull();
  });
});
