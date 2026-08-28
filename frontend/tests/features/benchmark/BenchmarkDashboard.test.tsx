import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BenchmarkDashboard } from '@/features/benchmark/components/BenchmarkDashboard';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import {
  deletePersistedEvaluationDataset,
  getBenchmarkDatasets,
  getPersistedEvaluationDataset,
  getPersistedEvaluationDatasets,
  persistEvaluationDataset,
  runBenchmark,
  validateEvaluationDataset,
} from '@/features/benchmark/api/benchmarkApi';
import { BENCHMARK_DATASET_STALE_TIME_MS } from '@/features/benchmark/hooks/useBenchmark';
import { benchmarkDatasetKeys } from '@/shared/query/queryKeys';
import { deferred } from '../support';
import {
  benchmarkDataset as dataset,
  benchmarkResult as result,
  persistedDataset,
} from './support';

vi.mock('../../../src/features/benchmark/api/benchmarkApi');

async function reviewAndConfirm(): Promise<void> {
  const reviewButton = await screen.findByRole('button', {
    name: 'Review benchmark run',
  });

  fireEvent.click(reviewButton);

  const confirmButton = await screen.findByRole('button', {
    name: 'Run benchmark now',
  });

  await act(async () => {
    fireEvent.click(confirmButton);

    await Promise.resolve();
  });
}

let queryClient: QueryClient;
const importedDefinition = {
  schema_version: 1,
  name: 'Imported <safety> set',
  cases: [
    {
      case_id: 'formula',
      prompt: '=SUM(A1:A2)',
      expected_cache_hit: false,
    },
  ],
};
const importedPreview = {
  schema_version: 1 as const,
  dataset_id: 'custom:1234567890abcdef',
  digest: '9'.repeat(64),
  name: 'Imported <safety> set',
  description: 'Synthetic imported evidence.',
  case_count: 1,
  expected_hits: 0,
  expected_misses: 1,
  categories: ['uncategorized'],
  decoded_bytes: 160,
  warnings: [
    {
      code: 'uncategorized_cases',
      detail: 'Cases without a category are grouped as uncategorized.',
      count: 1,
    },
  ],
  query_executions: 1,
  threshold_projection_evaluations: 7,
  maximum_provider_calls: 1,
  provider_calls_made: 0 as const,
  limits: {
    max_cases: 50,
    max_decoded_bytes: 49_152,
    max_workload_queries: 250,
  },
};

function renderDashboard() {
  return render(<BenchmarkDashboard />, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>{children}</QueryTestProvider>
    ),
  });
}

describe('BenchmarkDashboard', () => {
  beforeEach(() => {
    queryClient = createTestQueryClient();
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'default-operator',
        role: 'operator',
        namespaces: ['default'],
      },
      status: 'authenticated',
    });
    vi.mocked(getBenchmarkDatasets).mockResolvedValue({
      ok: true,
      data: {
        datasets: [
          {
            ...dataset,
            categories: [...dataset.categories],
          },
        ],
        default_dataset_id: 'quick',
      },
    });
    vi.mocked(runBenchmark).mockResolvedValue({ ok: true, data: result });
    vi.mocked(validateEvaluationDataset).mockResolvedValue({
      ok: true,
      data: importedPreview,
    });
    vi.mocked(getPersistedEvaluationDatasets).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'session',
        persistence_enabled: false,
        items: [],
        total: 0,
        offset: 0,
        limit: 12,
        has_more: false,
        limits: {
          default_retention_days: 30,
          max_retention_days: 365,
          max_persisted_per_namespace: 100,
        },
      },
    });
    vi.mocked(getPersistedEvaluationDataset).mockResolvedValue({
      ok: true,
      data: persistedDataset,
    });
    vi.mocked(persistEvaluationDataset).mockResolvedValue({
      ok: true,
      data: persistedDataset,
    });
    vi.mocked(deletePersistedEvaluationDataset).mockResolvedValue({
      ok: true,
      data: {
        deleted: true,
        dataset_id: persistedDataset.dataset_id,
        namespace: persistedDataset.namespace,
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('warns before provider calls and submits the selected threshold', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });

    fireEvent.change(screen.getByLabelText('Benchmark threshold'), {
      target: { value: '0.90' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review benchmark run' }));

    expect(runBenchmark).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog').textContent).toContain(
      'external generation calls',
    );

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', {
          name: 'Run benchmark now',
        }),
      );

      await Promise.resolve();
    });

    await waitFor(() =>
      expect(runBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          threshold: 0.9,
          dataset_source: { kind: 'builtin', dataset_id: 'quick' },
          evaluation_thresholds: [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.98],
          allow_external_provider_calls: true,
        }),
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText('Measured run')).toBeTruthy();
  });

  it('renders metrics, charts, and per-query evidence', async () => {
    renderDashboard();
    await reviewAndConfirm();

    expect(await screen.findByText('Measured run')).toBeTruthy();
    expect(screen.getByText('50.0%')).toBeTruthy();
    expect(
      screen.getByText('Hit rate vs. threshold (frozen-candidate projection)'),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'Precision / recall vs. threshold (frozen-candidate projection)',
      ),
    ).toBeTruthy();
    expect(screen.getByText('Similarity-score distribution')).toBeTruthy();
    expect(screen.getByText('Confusion matrix and case evidence')).toBeTruthy();
    const table = screen.getByRole('table', {
      name: 'Per-query benchmark results',
    });
    for (const header of [
      'Sequence',
      'Repetition',
      'Case ID',
      'Category',
      'Query',
      'Expected',
      'Actual',
      'Score',
      'Latency',
      'Outcome',
      'Inspect',
    ]) {
      expect(within(table).getByRole('columnheader', { name: header })).toBeTruthy();
    }
    expect(within(table).getByText('0.940')).toBeTruthy();
    expect(within(table).getByText('true positive')).toBeTruthy();
    expect(within(table).getByText('10.0 ms')).toBeTruthy();
    expect(within(table).getByText('n/a')).toBeTruthy();
  });

  it('shows loading and error states', async () => {
    let resolveRun:
      ((value: Awaited<ReturnType<typeof runBenchmark>>) => void) | undefined;
    vi.mocked(runBenchmark).mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      }),
    );
    renderDashboard();
    await reviewAndConfirm();

    expect(screen.getByLabelText('Loading benchmark results')).toBeTruthy();
    expect(document.querySelectorAll('[data-skeleton-result-metric]')).toHaveLength(18);
    expect(document.querySelectorAll('[data-skeleton-result-chart]')).toHaveLength(5);
    await act(async () => {
      resolveRun?.({
        ok: false,
        error: {
          code: 'upstream_error',
          detail: 'Provider unavailable',
          status: 502,
        },
      });

      await Promise.resolve();
    });

    expect((await screen.findByRole('alert')).textContent).toContain(
      'Provider unavailable',
    );
  });

  it('uses an accessible dataset skeleton only for initial catalog loading', () => {
    vi.mocked(getBenchmarkDatasets).mockReturnValue(new Promise(() => undefined));

    renderDashboard();

    expect(screen.getByLabelText('Loading benchmark datasets')).toBeTruthy();
    expect(screen.queryByLabelText('Loading benchmark results')).toBeNull();
    expect(document.querySelectorAll('[data-skeleton-control]')).toHaveLength(6);
    expect(screen.queryByLabelText('Benchmark dataset')).toBeNull();
  });

  it('keeps cached datasets visible during a background refresh', async () => {
    const cachedCatalog = {
      datasets: [
        {
          ...dataset,
          categories: [...dataset.categories],
        },
      ],
      default_dataset_id: 'quick' as const,
    };
    queryClient.setQueryData(benchmarkDatasetKeys.catalog(), cachedCatalog, {
      updatedAt: Date.now() - BENCHMARK_DATASET_STALE_TIME_MS - 1,
    });
    const refresh = deferred<Awaited<ReturnType<typeof getBenchmarkDatasets>>>();
    vi.mocked(getBenchmarkDatasets).mockReturnValue(refresh.promise);

    renderDashboard();

    expect(screen.getByLabelText('Benchmark dataset')).toBeTruthy();
    expect(screen.queryByLabelText('Loading benchmark datasets')).toBeNull();
    expect(screen.getByText('Refreshing dataset catalog')).toBeTruthy();
    await waitFor(() => expect(getBenchmarkDatasets).toHaveBeenCalledOnce());

    await act(async () => {
      refresh.resolve({
        ok: true,
        data: cachedCatalog,
      });
    });

    await waitFor(() => {
      expect(screen.queryByText('Refreshing dataset catalog')).toBeNull();
    });
  });

  it('compiles advanced sweep controls into an exact bounded list', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Advanced frozen-candidate sweep',
      }),
    );
    fireEvent.change(screen.getByLabelText('Threshold sweep start'), {
      target: { value: '0.80' },
    });
    fireEvent.change(screen.getByLabelText('Threshold sweep end'), {
      target: { value: '0.90' },
    });
    fireEvent.change(screen.getByLabelText('Threshold sweep step'), {
      target: { value: '0.05' },
    });

    await reviewAndConfirm();

    await waitFor(() =>
      expect(runBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          evaluation_thresholds: [0.8, 0.85, 0.9, 0.92],
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it('lets viewers inspect metadata but not initiate a run', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'reader',
        role: 'viewer',
        namespaces: ['default'],
      },
      status: 'authenticated',
    });

    renderDashboard();

    const review = await screen.findByRole('button', {
      name: 'Review benchmark run',
    });
    expect((review as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Operator access is required/)).toBeTruthy();
    expect(screen.getByText(/Dataset version 1.0.0/)).toBeTruthy();
    expect(runBenchmark).not.toHaveBeenCalled();
  });

  it('lets an authenticated operator complete the review flow', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'operator',
        role: 'operator',
        namespaces: ['default'],
      },
      status: 'authenticated',
    });

    renderDashboard();
    await reviewAndConfirm();

    await waitFor(() => expect(runBenchmark).toHaveBeenCalledOnce());
    expect(await screen.findByText(/Evaluation run completed/)).toBeTruthy();
  });

  it('parses, validates, previews, and removes a session-local JSON file', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    const input = screen.getByLabelText('JSON dataset file');
    const file = new File([JSON.stringify(importedDefinition)], 'safety-set.json', {
      type: 'application/json',
    });

    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText('Validated preview')).toBeTruthy();
    expect(screen.getByText('Imported <safety> set')).toBeTruthy();
    expect(screen.getByText(/Validation made 0 provider calls/)).toBeTruthy();
    expect(validateEvaluationDataset).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: importedDefinition }),
      expect.any(AbortSignal),
    );
    expect(runBenchmark).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Remove imported dataset' }));

    expect(screen.queryByText('Validated preview')).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it('shows the session-only fallback without saving during validation', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByRole('button', { name: 'Datasets' }));

    expect(await screen.findByText('Persistence is disabled')).toBeTruthy();
    expect(screen.getByText(/session-only evaluation datasets/)).toBeTruthy();
    expect(persistEvaluationDataset).not.toHaveBeenCalled();
  });

  it('saves only after an explicit action and selects persisted detail for a run', async () => {
    vi.mocked(getPersistedEvaluationDatasets).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        persistence_enabled: true,
        items: [persistedDataset],
        total: 1,
        offset: 0,
        limit: 12,
        has_more: false,
        limits: {
          default_retention_days: 30,
          max_retention_days: 365,
          max_persisted_per_namespace: 100,
        },
      },
    });
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    fireEvent.change(screen.getByLabelText('JSON dataset file'), {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'persist-me.json', {
            type: 'application/json',
          }),
        ],
      },
    });
    await screen.findByText('Validated preview');
    expect(persistEvaluationDataset).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Datasets' }));
    await screen.findByText('Save validated session dataset');
    fireEvent.click(screen.getByRole('button', { name: 'Save validated dataset' }));

    await waitFor(() =>
      expect(persistEvaluationDataset).toHaveBeenCalledWith(
        {
          namespace: 'default',
          dataset: importedDefinition,
          retention_days: 30,
        },
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText(/Saved Persisted/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'View details' }));
    expect(
      await screen.findByRole('button', { name: 'Use for benchmark' }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Use for benchmark' }));

    expect(
      screen.getByLabelText(`Persisted dataset: ${persistedDataset.name}`),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Review benchmark run' }));
    fireEvent.click(screen.getByRole('button', { name: 'Run benchmark now' }));

    await waitFor(() =>
      expect(runBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          dataset_source: {
            kind: 'persisted',
            dataset_id: persistedDataset.dataset_id,
            namespace: persistedDataset.namespace,
          },
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it('requires a namespace choice for a multi-namespace operator', async () => {
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
    vi.mocked(getPersistedEvaluationDatasets).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        persistence_enabled: true,
        items: [],
        total: 0,
        offset: 0,
        limit: 12,
        has_more: false,
        limits: {
          default_retention_days: 30,
          max_retention_days: 365,
          max_persisted_per_namespace: 100,
        },
      },
    });
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    fireEvent.change(screen.getByLabelText('JSON dataset file'), {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'multi.json', {
            type: 'application/json',
          }),
        ],
      },
    });
    await screen.findByText('Validated preview');
    fireEvent.click(screen.getByRole('button', { name: 'Datasets' }));

    const save = await screen.findByRole('button', {
      name: 'Save validated dataset',
    });
    await waitFor(() =>
      expect(getPersistedEvaluationDatasets).toHaveBeenCalledWith(
        {
          namespace: 'tenant-a',
          offset: 0,
          limit: 12,
        },
        expect.any(AbortSignal),
      ),
    );
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Catalog namespace'), {
      target: { value: 'tenant-b' },
    });
    await waitFor(() =>
      expect(getPersistedEvaluationDatasets).toHaveBeenCalledWith(
        {
          namespace: 'tenant-b',
          offset: 0,
          limit: 12,
        },
        expect.any(AbortSignal),
      ),
    );
    fireEvent.change(await screen.findByLabelText('Namespace'), {
      target: { value: 'tenant-b' },
    });
    expect(
      (await screen.findByRole('button', {
        name: 'Save validated dataset',
      })) as HTMLButtonElement,
    ).toHaveProperty('disabled', false);
  });

  it('keeps deletion admin-only and names the exact destructive scope', async () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'administrator',
        role: 'admin',
        namespaces: ['tenant-a'],
      },
      status: 'authenticated',
    });
    vi.mocked(getPersistedEvaluationDatasets).mockResolvedValue({
      ok: true,
      data: {
        storage_mode: 'postgres',
        persistence_enabled: true,
        items: [persistedDataset],
        total: 1,
        offset: 0,
        limit: 12,
        has_more: false,
        limits: {
          default_retention_days: 30,
          max_retention_days: 365,
          max_persisted_per_namespace: 100,
        },
      },
    });
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByRole('button', { name: 'Datasets' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete dataset' }));

    const confirmation = screen.getByRole('group', {
      name: `Confirm deletion of ${persistedDataset.name} from namespace ${persistedDataset.namespace}`,
    });
    expect(confirmation.textContent).toContain(persistedDataset.name);
    expect(confirmation.textContent).toContain(persistedDataset.namespace);
    expect(confirmation.textContent).toContain('2 cases');
    fireEvent.click(
      within(confirmation).getByRole('button', {
        name: `Confirm delete ${persistedDataset.name} from namespace ${persistedDataset.namespace}`,
      }),
    );
    await waitFor(() =>
      expect(deletePersistedEvaluationDataset).toHaveBeenCalledWith(
        persistedDataset.dataset_id,
        persistedDataset.namespace,
      ),
    );
  });

  it('ignores a stale local file read after a newer selection', async () => {
    const olderText = deferred<string>();
    const olderFile = {
      name: 'older.json',
      size: 64,
      text: () => olderText.promise,
      type: 'application/json',
    } as File;

    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    const input = screen.getByLabelText('JSON dataset file');

    fireEvent.change(input, { target: { files: [olderFile] } });
    fireEvent.change(input, {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'newer.json', {
            type: 'application/json',
          }),
        ],
      },
    });

    expect(await screen.findByText('Validated preview')).toBeTruthy();
    expect(screen.getByText('Selected: newer.json')).toBeTruthy();
    expect(validateEvaluationDataset).toHaveBeenCalledTimes(1);
    expect(validateEvaluationDataset).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: importedDefinition }),
      expect.any(AbortSignal),
    );

    await act(async () => {
      olderText.resolve(
        JSON.stringify({
          ...importedDefinition,
          name: 'Stale imported dataset',
        }),
      );
      await Promise.resolve();
    });

    expect(validateEvaluationDataset).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Selected: newer.json')).toBeTruthy();
  });

  it('keeps malformed JSON local and renders structured server references', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    const input = screen.getByLabelText('JSON dataset file');

    fireEvent.change(input, {
      target: {
        files: [
          new File(['{"schema_version":'], 'broken.json', {
            type: 'application/json',
          }),
        ],
      },
    });

    expect(
      await screen.findByText('The selected file is not valid JSON.'),
    ).toBeTruthy();
    expect(validateEvaluationDataset).not.toHaveBeenCalled();

    vi.mocked(validateEvaluationDataset).mockResolvedValueOnce({
      ok: false,
      error: {
        code: 'evaluation_dataset_invalid',
        detail: 'The imported evaluation dataset is invalid.',
        issues: [
          {
            code: 'duplicate_case_id',
            detail: 'Case IDs must be unique.',
            pointer: '/cases/1/case_id',
            case_id: 'duplicate',
            case_index: 1,
          },
        ],
        status: 422,
      },
    });
    fireEvent.change(input, {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'invalid.json', {
            type: 'application/json',
          }),
        ],
      },
    });

    expect(await screen.findByText(/duplicate_case_id/)).toBeTruthy();
    expect(screen.getByText(/\/cases\/1\/case_id/)).toBeTruthy();
  });

  it('revalidates imported content at review and submits inline execution', async () => {
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    fireEvent.change(screen.getByLabelText('JSON dataset file'), {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'inline.json', {
            type: 'application/json',
          }),
        ],
      },
    });
    await screen.findByText('Validated preview');

    fireEvent.click(screen.getByRole('button', { name: 'Review benchmark run' }));
    expect(await screen.findByRole('alertdialog')).toBeTruthy();
    expect(validateEvaluationDataset).toHaveBeenCalledTimes(2);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Run benchmark now' }));
      await Promise.resolve();
    });

    expect(runBenchmark).toHaveBeenCalledWith(
      expect.objectContaining({
        dataset_source: {
          kind: 'inline',
          definition: importedDefinition,
        },
      }),
      expect.any(AbortSignal),
    );
  });

  it('clears imported content when the authentication principal changes', async () => {
    const rendered = renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    fireEvent.change(screen.getByLabelText('JSON dataset file'), {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'principal-bound.json', {
            type: 'application/json',
          }),
        ],
      },
    });
    await screen.findByText('Validated preview');

    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'different-operator',
        role: 'operator',
        namespaces: ['default'],
      },
      status: 'authenticated',
    });
    rendered.rerender(<BenchmarkDashboard />);

    await waitFor(() => expect(screen.queryByText('Validated preview')).toBeNull());
    expect(screen.queryByText('Selected: principal-bound.json')).toBeNull();
  });

  it('does not persist imported content through browser storage APIs', async () => {
    const localStorageSet = vi.spyOn(Storage.prototype, 'setItem');
    renderDashboard();
    await screen.findByRole('button', { name: 'Review benchmark run' });
    fireEvent.click(screen.getByLabelText('Custom JSON dataset'));
    fireEvent.change(screen.getByLabelText('JSON dataset file'), {
      target: {
        files: [
          new File([JSON.stringify(importedDefinition)], 'memory-only.json', {
            type: 'application/json',
          }),
        ],
      },
    });

    await screen.findByText('Validated preview');
    expect(localStorageSet).not.toHaveBeenCalled();
  });
});
