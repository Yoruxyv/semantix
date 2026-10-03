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
  getBenchmarkDatasets,
  runBenchmark,
} from '@/features/benchmark/api/benchmarkApi';
import { BenchmarkDashboard } from '@/features/benchmark/components/BenchmarkDashboard';
import { useAuth } from '@/features/auth/hooks/useAuth';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { benchmarkDataset, benchmarkResult } from './support';

vi.mock('../../../src/features/benchmark/api/benchmarkApi');

let queryClient: QueryClient;

function renderDashboard() {
  return render(<BenchmarkDashboard />, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>{children}</QueryTestProvider>
    ),
  });
}

async function confirmReviewedRun(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: 'Review benchmark run' }));
  const confirm = await screen.findByRole('button', {
    name: 'Run benchmark now',
  });
  await act(async () => {
    fireEvent.click(confirm);
    await Promise.resolve();
  });
}

describe('built-in evaluation history namespace policy', () => {
  beforeEach(() => {
    queryClient = createTestQueryClient();
    vi.mocked(getBenchmarkDatasets).mockResolvedValue({
      ok: true,
      data: {
        datasets: [benchmarkDataset],
        default_dataset_id: 'quick',
      },
    });
    vi.mocked(runBenchmark).mockResolvedValue({
      ok: true,
      data: benchmarkResult,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires a concrete namespace when authentication is disabled', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'disabled',
    });

    renderDashboard();

    const review = await screen.findByRole('button', {
      name: 'Review benchmark run',
    });
    const namespace = screen.getByLabelText('Benchmark history namespace');

    expect((review as HTMLButtonElement).disabled).toBe(true);
    expect(namespace.getAttribute('aria-required')).toBe('true');
    expect(namespace.getAttribute('aria-invalid')).toBe('true');

    fireEvent.change(namespace, { target: { value: '*' } });
    expect((review as HTMLButtonElement).disabled).toBe(true);
    expect(namespace.getAttribute('aria-invalid')).toBe('true');

    fireEvent.change(namespace, { target: { value: 'tenant-local' } });
    expect((review as HTMLButtonElement).disabled).toBe(false);
    expect(namespace.getAttribute('aria-invalid')).toBe('false');

    await confirmReviewedRun();

    await waitFor(() =>
      expect(runBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          history_namespace: 'tenant-local',
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it('requires an explicit authorized choice for a multi-namespace operator', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'multi-operator',
        role: 'operator',
        namespaces: ['tenant-a', 'tenant-b'],
      },
      status: 'authenticated',
    });

    renderDashboard();

    const review = await screen.findByRole('button', {
      name: 'Review benchmark run',
    });
    const namespace = screen.getByLabelText('Benchmark history namespace');

    expect((review as HTMLButtonElement).disabled).toBe(true);
    expect(namespace.getAttribute('aria-required')).toBe('true');

    fireEvent.change(namespace, { target: { value: 'tenant-b' } });
    expect((review as HTMLButtonElement).disabled).toBe(false);

    await confirmReviewedRun();

    await waitFor(() =>
      expect(runBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          history_namespace: 'tenant-b',
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it('continues to infer a sole scoped namespace without serializing ownership', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'sole-operator',
        role: 'operator',
        namespaces: ['tenant-a'],
      },
      status: 'authenticated',
    });

    renderDashboard();

    const review = await screen.findByRole('button', {
      name: 'Review benchmark run',
    });
    expect((review as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByLabelText('Benchmark history namespace').textContent).toBe(
      'tenant-a',
    );

    await confirmReviewedRun();

    await waitFor(() => expect(runBenchmark).toHaveBeenCalledOnce());
    const payload = vi.mocked(runBenchmark).mock.calls[0]?.[0];
    expect(payload).toBeDefined();
    expect('history_namespace' in (payload ?? {})).toBe(false);
  });
});
