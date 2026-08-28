import type { QueryClient } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import {
  getBenchmarkDatasets,
  persistEvaluationDataset,
  runBenchmark,
  validateEvaluationDataset,
} from '@/features/benchmark/api/benchmarkApi';
import type { AuthContextValue } from '@/features/auth/context/AuthContext';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { useBenchmark } from '@/features/benchmark/hooks/useBenchmark';
import { deferred } from '../support';
import { benchmarkDataset, benchmarkResult, persistedDataset } from './support';

vi.mock('@/features/benchmark/api/benchmarkApi');

function renderBenchmarkHook(client: QueryClient) {
  return renderHook(() => useBenchmark(), {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={client}>{children}</QueryTestProvider>
    ),
  });
}

const principalA: AuthContextValue = {
  authenticate: vi.fn(async () => false),
  error: null,
  lockedUntil: null,
  logout: vi.fn(),
  retryAccessPolicy: vi.fn(),
  session: {
    name: 'operator-a',
    role: 'operator',
    namespaces: ['tenant-a'],
  },
  status: 'authenticated',
};

const principalB: AuthContextValue = {
  ...principalA,
  session: {
    name: 'operator-b',
    role: 'operator',
    namespaces: ['tenant-b'],
  },
};

const importedDefinition = {
  schema_version: 1,
  name: 'Principal-bound dataset',
  cases: [
    {
      case_id: 'seed',
      prompt: 'Synthetic principal-bound prompt',
      expected_cache_hit: false,
    },
  ],
};

describe('useBenchmark', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    vi.mocked(useAuth).mockReturnValue(principalA);
    vi.mocked(getBenchmarkDatasets).mockResolvedValue({
      ok: true,
      data: {
        datasets: [benchmarkDataset],
        default_dataset_id: 'quick',
      },
    });
    vi.mocked(validateEvaluationDataset).mockResolvedValue({
      ok: true,
      data: {
        schema_version: 1,
        dataset_id: 'custom:1234567890abcdef',
        digest: '9'.repeat(64),
        name: 'Principal-bound dataset',
        description: null,
        case_count: 1,
        expected_hits: 0,
        expected_misses: 1,
        categories: ['uncategorized'],
        decoded_bytes: 160,
        warnings: [],
        query_executions: 1,
        threshold_projection_evaluations: 7,
        maximum_provider_calls: 1,
        provider_calls_made: 0,
        limits: {
          max_cases: 50,
          max_decoded_bytes: 49_152,
          max_workload_queries: 250,
        },
      },
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the result from the run started last', async () => {
    const olderRun = deferred<Awaited<ReturnType<typeof runBenchmark>>>();
    const newerRun = deferred<Awaited<ReturnType<typeof runBenchmark>>>();
    vi.mocked(runBenchmark)
      .mockReturnValueOnce(olderRun.promise)
      .mockReturnValueOnce(newerRun.promise);
    const { result } = renderBenchmarkHook(queryClient);

    await waitFor(() => expect(result.current.datasetsLoading).toBe(false));

    let olderCompletion: Promise<void> | undefined;
    act(() => {
      olderCompletion = result.current.confirmRun();
    });
    let newerCompletion: Promise<void> | undefined;
    act(() => {
      newerCompletion = result.current.confirmRun();
    });

    const olderSignal = vi.mocked(runBenchmark).mock.calls[0]?.[1];
    expect(olderSignal?.aborted).toBe(true);

    await act(async () => {
      newerRun.resolve({
        ok: true,
        data: {
          ...benchmarkResult,
          run_id: 'b'.repeat(32),
        },
      });
      await newerCompletion;
    });
    expect(result.current.result?.run_id).toBe('b'.repeat(32));

    await act(async () => {
      olderRun.resolve({
        ok: true,
        data: benchmarkResult,
      });
      await olderCompletion;
    });
    expect(result.current.result?.run_id).toBe('b'.repeat(32));
  });

  it('aborts an active run when the hook unmounts', async () => {
    const pendingRun = deferred<Awaited<ReturnType<typeof runBenchmark>>>();
    vi.mocked(runBenchmark).mockReturnValue(pendingRun.promise);
    const { result, unmount } = renderBenchmarkHook(queryClient);

    await waitFor(() => expect(result.current.datasetsLoading).toBe(false));

    let completion: Promise<void> | undefined;
    act(() => {
      completion = result.current.confirmRun();
    });
    const signal = vi.mocked(runBenchmark).mock.calls[0]?.[1];

    unmount();

    expect(signal?.aborted).toBe(true);
    pendingRun.resolve({
      ok: true,
      data: benchmarkResult,
    });
    await completion;
  });

  it.each([
    ['a different principal', principalB],
    [
      'logout',
      {
        ...principalA,
        session: null,
        status: 'unauthenticated',
      } satisfies AuthContextValue,
    ],
    [
      'authentication becoming disabled',
      {
        ...principalA,
        session: null,
        status: 'disabled',
      } satisfies AuthContextValue,
    ],
  ])(
    'invalidates an active run on %s and ignores its late response',
    async (_transition, nextAuth) => {
      vi.mocked(useAuth).mockReturnValue(principalA);
      const pendingRun = deferred<Awaited<ReturnType<typeof runBenchmark>>>();
      vi.mocked(runBenchmark).mockReturnValue(pendingRun.promise);
      const rendered = renderBenchmarkHook(queryClient);

      await waitFor(() => expect(rendered.result.current.datasetsLoading).toBe(false));

      act(() => {
        rendered.result.current.selectPersistedDataset(persistedDataset);
      });
      await waitFor(() =>
        expect(rendered.result.current.form.datasetSource).toBe('persisted'),
      );

      let completion: Promise<void> | undefined;
      act(() => {
        completion = rendered.result.current.confirmRun();
      });
      await waitFor(() => expect(rendered.result.current.isRunning).toBe(true));
      const signal = vi.mocked(runBenchmark).mock.calls[0]?.[1];

      vi.mocked(useAuth).mockReturnValue(nextAuth);
      rendered.rerender();

      await waitFor(() => {
        expect(signal?.aborted).toBe(true);
        expect(rendered.result.current.isRunning).toBe(false);
        expect(rendered.result.current.form.datasetSource).toBe('builtin');
      });
      expect(rendered.result.current.persistedDataset).toBeNull();
      expect(rendered.result.current.result).toBeNull();
      expect(rendered.result.current.error).toBeNull();
      expect(rendered.result.current.statusMessage).toBe('');

      await act(async () => {
        pendingRun.resolve({
          ok: true,
          data: benchmarkResult,
        });
        await completion;
      });

      expect(rendered.result.current.persistedDataset).toBeNull();
      expect(rendered.result.current.result).toBeNull();
      expect(rendered.result.current.error).toBeNull();
      expect(rendered.result.current.statusMessage).toBe('');
    },
  );

  it('invalidates an active save on principal change and ignores its late response', async () => {
    vi.mocked(useAuth).mockReturnValue(principalA);
    const pendingSave =
      deferred<Awaited<ReturnType<typeof persistEvaluationDataset>>>();
    vi.mocked(persistEvaluationDataset).mockReturnValue(pendingSave.promise);
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries');
    const rendered = renderBenchmarkHook(queryClient);

    await waitFor(() => expect(rendered.result.current.datasetsLoading).toBe(false));
    await act(async () => {
      await rendered.result.current.selectImportFile(
        new File([JSON.stringify(importedDefinition)], 'principal-bound.json', {
          type: 'application/json',
        }),
      );
    });
    expect(rendered.result.current.preview).not.toBeNull();

    let completion: Promise<typeof persistedDataset | null> | undefined;
    act(() => {
      completion = rendered.result.current.saveImport('tenant-a', 30);
    });
    await waitFor(() => expect(rendered.result.current.isSavingImport).toBe(true));
    const signal = vi.mocked(persistEvaluationDataset).mock.calls[0]?.[1];

    vi.mocked(useAuth).mockReturnValue(principalB);
    rendered.rerender();

    await waitFor(() => {
      expect(signal?.aborted).toBe(true);
      expect(rendered.result.current.isSavingImport).toBe(false);
      expect(rendered.result.current.form.datasetSource).toBe('builtin');
    });
    expect(rendered.result.current.preview).toBeNull();
    expect(rendered.result.current.persistedDataset).toBeNull();
    expect(rendered.result.current.error).toBeNull();
    expect(rendered.result.current.statusMessage).toBe('');

    let saved: typeof persistedDataset | null | undefined;
    await act(async () => {
      pendingSave.resolve({
        ok: true,
        data: persistedDataset,
      });
      saved = await completion;
    });

    expect(saved).toBeNull();
    expect(invalidateQueries).not.toHaveBeenCalled();
    expect(rendered.result.current.preview).toBeNull();
    expect(rendered.result.current.persistedDataset).toBeNull();
    expect(rendered.result.current.error).toBeNull();
    expect(rendered.result.current.statusMessage).toBe('');
  });

  it('reuses a fresh dataset catalog when the hook remounts', async () => {
    const first = renderBenchmarkHook(queryClient);
    await waitFor(() => expect(first.result.current.datasetsLoading).toBe(false));
    expect(getBenchmarkDatasets).toHaveBeenCalledOnce();
    first.unmount();

    const second = renderBenchmarkHook(queryClient);
    expect(second.result.current.datasets).toEqual([benchmarkDataset]);
    expect(second.result.current.datasetsLoading).toBe(false);
    expect(getBenchmarkDatasets).toHaveBeenCalledOnce();

    second.unmount();
  });
});
