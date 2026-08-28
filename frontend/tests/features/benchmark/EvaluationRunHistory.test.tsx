import type { QueryClient } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  deleteEvaluationRunHistory,
  getEvaluationRunHistory,
  getEvaluationRunHistoryDetail,
} from '@/features/benchmark/api/benchmarkApi';
import { EvaluationRunHistory } from '@/features/benchmark/components/history/EvaluationRunHistory';
import { useAuth } from '@/features/auth/hooks/useAuth';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { benchmarkResult } from './support';

vi.mock('../../../src/features/benchmark/api/benchmarkApi');
vi.mock('../../../src/features/auth/hooks/useAuth');

const retainedItem = {
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

const retainedDetail = {
  ...retainedItem,
  threshold_evaluation_mode: 'frozen_candidate_projection' as const,
  threshold_evaluations: benchmarkResult.threshold_evaluations,
};

let queryClient: QueryClient;

function renderHistory() {
  return render(<EvaluationRunHistory />, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>{children}</QueryTestProvider>
    ),
  });
}

function adminAuth() {
  vi.mocked(useAuth).mockReturnValue({
    authenticate: vi.fn(async () => false),
    error: null,
    lockedUntil: null,
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
    session: {
      name: 'history-admin',
      role: 'admin',
      namespaces: ['tenant-a'],
    },
    status: 'authenticated',
  });
}

describe('EvaluationRunHistory', () => {
  beforeEach(() => {
    queryClient = createTestQueryClient();
    adminAuth();
    vi.mocked(getEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [retainedItem],
        total: 1,
        offset: 0,
        limit: 12,
        has_more: false,
      },
    });
    vi.mocked(getEvaluationRunHistoryDetail).mockResolvedValue({
      ok: true,
      data: retainedDetail,
    });
    vi.mocked(deleteEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        deleted: true,
        run_id: retainedItem.run_id,
        namespace: retainedItem.namespace,
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('lists retained aggregate runs and loads detail on demand', async () => {
    renderHistory();

    expect(await screen.findByText(benchmarkResult.dataset.name)).toBeTruthy();
    expect(screen.getByText('50.0%')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'View details' }));

    expect(
      await screen.findByRole('table', {
        name: 'Retained threshold evaluations',
      }),
    ).toBeTruthy();
    expect(screen.getByText(/Per-query prompts, generated responses/)).toBeTruthy();
    expect(getEvaluationRunHistoryDetail).toHaveBeenCalledWith(
      retainedItem.run_id,
      expect.any(AbortSignal),
    );
  });

  it('shows the explicit disabled-history state', async () => {
    vi.mocked(getEvaluationRunHistory).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'disabled',
        retention_enabled: false,
        items: [],
        total: 0,
        offset: 0,
        limit: 12,
        has_more: false,
      },
    });

    renderHistory();

    expect(await screen.findByText('Durable history is disabled')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'View details' })).toBeNull();
  });

  it('keeps deletion admin-only and namespace scoped', async () => {
    renderHistory();

    await screen.findByText(benchmarkResult.dataset.name);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Delete retained run' }));
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(deleteEvaluationRunHistory).toHaveBeenCalledWith(
        retainedItem.run_id,
        retainedItem.namespace,
      ),
    );
  });
});
