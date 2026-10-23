import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { BenchmarkDashboard } from '@/features/benchmark/components/BenchmarkDashboard';
import { useBenchmark } from '@/features/benchmark/hooks/useBenchmark';
import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { deferred } from '../support';
import { benchmarkDataset, benchmarkResult, persistedDataset } from './support';

const heading = 'Evaluation limit reached';
const explanation =
  'This evaluation exceeds the maximum number of queries allowed per run.';
const guidance =
  'Reduce the number of repetitions or select a smaller dataset, then try again.';
const limit = {
  error: 'evaluation_workload_limit_exceeded',
  detail:
    'Cases multiplied by repetitions exceed the configured evaluation workload limit.',
};
const inlineLimit = {
  error: 'evaluation_dataset_invalid',
  detail: 'The imported evaluation dataset is invalid.',
  issues: [
    { code: 'workload_limit_exceeded', detail: limit.detail, pointer: '/cases' },
  ],
};
let client = createTestQueryClient();
let outcome: unknown;
let status: number;
let posts: number;
let pending: ReturnType<typeof deferred<Response>> | null;
const json = (data: unknown, responseStatus = 200) =>
  new Response(JSON.stringify(data), { status: responseStatus });
function wrapper({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <MemoryRouter>
      <QueryTestProvider client={client}>{children}</QueryTestProvider>
    </MemoryRouter>
  );
}
async function submit() {
  fireEvent.click(await screen.findByRole('button', { name: 'Review benchmark run' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Run benchmark now' }));
}

beforeEach(() => {
  client = createTestQueryClient();
  outcome = limit;
  status = 422;
  posts = 0;
  pending = null;
  vi.mocked(useAuth).mockReturnValue({
    authenticate: vi.fn(async () => true),
    error: null,
    lockedUntil: null,
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
    status: 'authenticated',
    session: { name: 'operator', role: 'operator', namespaces: ['default'] },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      let address: string;
      if (typeof input === 'string') address = input;
      else address = input instanceof URL ? input.href : input.url;
      const path = new URL(address).pathname;
      if (path.endsWith('/runs') && init?.method === 'POST') {
        posts += 1;
        return pending === null ? json(outcome, status) : pending.promise;
      }
      if (path.endsWith('/datasets'))
        return json({ datasets: [benchmarkDataset], default_dataset_id: 'quick' });
      if (path.endsWith('/datasets/validate'))
        return json({
          schema_version: 1,
          dataset_id: 'custom:1234567890abcdef',
          digest: '9'.repeat(64),
          name: 'Inline budget',
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
            max_decoded_bytes: 49152,
            max_workload_queries: 250,
          },
        });
      throw new Error(`Unexpected evaluation fixture request: ${path}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('evaluation admission feedback', () => {
  it.each([
    ['run budget', limit],
    ['inline budget issue', inlineLimit],
  ] as const)(
    'renders exact friendly content for %s through the production HTTP decoder',
    async (_name, error) => {
      outcome = {
        ...error,
        traceback: 'PrivateBackendException /srv/private.py',
        exception: 'PrivateBackendException',
      };
      render(<BenchmarkDashboard />, { wrapper });
      await submit();
      const alert = await screen.findByRole('alert');
      expect(within(alert).getByText(heading)).toBeTruthy();
      expect(within(alert).getByText(explanation)).toBeTruthy();
      expect(within(alert).getByText(guidance)).toBeTruthy();
      expect(screen.queryByText('Evaluation failed')).toBeNull();
      expect(screen.queryByText('Evaluation run failed.')).toBeNull();
      expect(screen.queryByText(/PrivateBackendException|srv\/private/)).toBeNull();
      expect(posts).toBe(1);
    },
  );

  it.each([
    [
      422,
      {
        error: 'evaluation_dataset_invalid',
        detail: 'Case IDs must be unique.',
        issues: [
          { code: 'duplicate_case_id', detail: 'Duplicate ID.', pointer: '/cases/1' },
        ],
      },
    ],
    [422, { error: 'validation_error', detail: limit.detail }],
    [403, { error: 'permission_denied', detail: 'This operation is not allowed.' }],
    [
      503,
      {
        error: 'evaluation_failed',
        detail: 'The provider is temporarily unavailable.',
      },
    ],
  ])('keeps unrelated HTTP %s failures distinct', async (responseStatus, error) => {
    status = responseStatus;
    outcome = error;
    render(<BenchmarkDashboard />, { wrapper });
    await submit();
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('Evaluation failed')).toBeTruthy();
    expect(within(alert).getByText(error.detail)).toBeTruthy();
    expect(screen.queryByText(heading)).toBeNull();
    expect(posts).toBe(1);
  });

  it('rejects a malformed error envelope without exposing internal fields', async () => {
    outcome = {
      error: 'evaluation_dataset_invalid',
      detail: 'Safe outer text',
      issues: [{ code: 'workload_limit_exceeded', detail: 'PrivateBackendException' }],
      traceback: '/srv/private.py',
    };
    render(<BenchmarkDashboard />, { wrapper });
    await submit();
    expect(
      await screen.findByText('The server returned an unexpected response.'),
    ).toBeTruthy();
    expect(screen.queryByText(heading)).toBeNull();
    expect(screen.queryByText(/PrivateBackendException|srv\/private/)).toBeNull();
  });

  it('keeps successful measured results and clears a prior limit warning', async () => {
    render(<BenchmarkDashboard />, { wrapper });
    await submit();
    await screen.findByText(heading);
    outcome = benchmarkResult;
    status = 200;
    await submit();
    expect(
      await screen.findByText('Evaluation run completed. Results are available below.'),
    ).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(posts).toBe(2);
  });

  it('classifies a persisted run without changing its request', async () => {
    const { result } = renderHook(() => useBenchmark(), { wrapper });
    await waitFor(() => expect(result.current.datasetsLoading).toBe(false));
    act(() => result.current.selectPersistedDataset(persistedDataset));
    await act(() => result.current.confirmRun());
    expect(result.current.error).toEqual({
      kind: 'workload_limit',
      message: explanation,
    });
    const call = vi
      .mocked(fetch)
      .mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      dataset_source: {
        kind: 'persisted',
        dataset_id: persistedDataset.dataset_id,
        namespace: persistedDataset.namespace,
      },
    });
    expect(posts).toBe(1);
  });

  it('classifies a validated inline run budget issue using its issue code', async () => {
    outcome = inlineLimit;
    const { result } = renderHook(() => useBenchmark(), { wrapper });
    await waitFor(() => expect(result.current.datasetsLoading).toBe(false));
    const definition = {
      schema_version: 1,
      name: 'Inline budget',
      cases: [
        {
          case_id: 'seed',
          prompt: 'Synthetic inline budget prompt',
          expected_cache_hit: false,
        },
      ],
    };
    const file = new File([JSON.stringify(definition)], 'inline.json', {
      type: 'application/json',
    });
    Object.defineProperty(file, 'text', {
      value: async () => JSON.stringify(definition),
    });
    await act(() => result.current.selectImportFile(file));
    await act(() => result.current.confirmRun());
    expect(result.current.error).toEqual({
      kind: 'workload_limit',
      message: explanation,
    });
    const call = vi
      .mocked(fetch)
      .mock.calls.find(([input]) => String(input).endsWith('/runs'));
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      dataset_source: { kind: 'inline', definition },
    });
    expect(posts).toBe(1);
  });

  it.each(['principal', 'unmount', 'supersede'] as const)(
    'ignores stale limit results after %s',
    async (change) => {
      pending = deferred<Response>();
      const request = pending;
      const view = renderHook(() => useBenchmark(), { wrapper });
      await waitFor(() => expect(view.result.current.datasetsLoading).toBe(false));
      let completion: Promise<void> | undefined;
      act(() => {
        completion = view.result.current.confirmRun();
      });
      const signal = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.signal;
      if (change === 'unmount') view.unmount();
      else if (change === 'principal') {
        vi.mocked(useAuth).mockReturnValue({
          ...vi.mocked(useAuth)(),
          session: { name: 'another', role: 'operator', namespaces: ['other'] },
        });
        view.rerender();
      } else {
        pending = null;
        outcome = benchmarkResult;
        status = 200;
        await act(() => view.result.current.confirmRun());
      }
      expect(signal?.aborted).toBe(true);
      await act(async () => {
        request.resolve(json(limit, 422));
        await completion;
      });
      expect(view.result.current.error).toBeNull();
      if (change === 'supersede')
        expect(view.result.current.result?.run_id).toBe(benchmarkResult.run_id);
    },
  );
});
