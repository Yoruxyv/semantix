import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  deletePersistedEvaluationDataset,
  getBenchmarkDatasets,
  getPersistedEvaluationDataset,
  getPersistedEvaluationDatasets,
  persistEvaluationDataset,
  runBenchmark,
  validateEvaluationDataset,
} from '@/features/benchmark/api/benchmarkApi';
import { benchmarkResult, persistedDataset } from './support';

const dataset = {
  dataset_id: 'quick',
  dataset_source: 'builtin',
  schema_version: null,
  version: '1.0.0',
  digest: 'd'.repeat(64),
  name: 'Quick set',
  description: 'Controlled prompts',
  query_count: 1,
  expected_hits: 0,
  expected_misses: 1,
  categories: ['seed'],
};

describe('benchmark API client', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('decodes benchmark datasets', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          datasets: [dataset],
          default_dataset_id: 'quick',
        }),
        { status: 200 },
      ),
    );

    const response = await getBenchmarkDatasets();

    expect(response.ok).toBe(true);
    if (response.ok) {
      expect(response.data.datasets[0]?.query_count).toBe(1);
    }
  });

  it('submits explicit provider approval and preserves null scores', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(benchmarkResult), { status: 200 }),
    );

    const response = await runBenchmark({
      dataset_source: { kind: 'builtin', dataset_id: 'quick' },
      threshold: 0.9,
      evaluation_thresholds: [0.8, 0.9, 0.95],
      repetitions: 1,
      reset_cache_before_run: true,
      estimated_cost_per_request_usd: 0,
      estimated_cost_per_1k_tokens_usd: 0,
      allow_external_provider_calls: true,
    });

    expect(response.ok).toBe(true);
    if (response.ok) {
      expect(response.data.query_results[0]?.similarity_score).toBeNull();
    }
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/evaluations/runs'),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"allow_external_provider_calls":true'),
      }),
    );
  });

  it('validates inline data through the provider-free preview route', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: 1,
          dataset_id: 'custom:1234567890abcdef',
          digest: 'd'.repeat(64),
          name: 'Custom set',
          description: null,
          case_count: 1,
          expected_hits: 0,
          expected_misses: 1,
          categories: ['uncategorized'],
          decoded_bytes: 120,
          warnings: [],
          query_executions: 1,
          threshold_projection_evaluations: 3,
          maximum_provider_calls: 1,
          provider_calls_made: 0,
          limits: {
            max_cases: 50,
            max_decoded_bytes: 49_152,
            max_workload_queries: 250,
          },
        }),
        { status: 200 },
      ),
    );

    const response = await validateEvaluationDataset({
      dataset: { schema_version: 1 },
      repetitions: 1,
      threshold_count: 3,
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/evaluations/datasets/validate'),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('strictly decodes structured dataset validation issues', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: 'evaluation_dataset_invalid',
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
        }),
        { status: 422 },
      ),
    );

    const response = await validateEvaluationDataset({
      dataset: {},
      repetitions: 1,
      threshold_count: 2,
    });

    expect(response.ok).toBe(false);
    if (!response.ok) {
      expect(response.error.issues?.[0]).toEqual({
        code: 'duplicate_case_id',
        detail: 'Case IDs must be unique.',
        pointer: '/cases/1/case_id',
        case_id: 'duplicate',
        case_index: 1,
      });
    }
  });

  it('uses the scoped persisted catalog CRUD routes', async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            storage_mode: 'postgres',
            persistence_enabled: true,
            items: [persistedDataset],
            total: 1,
            offset: 0,
            limit: 20,
            has_more: false,
            limits: {
              default_retention_days: 30,
              max_retention_days: 365,
              max_persisted_per_namespace: 100,
            },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(persistedDataset), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(persistedDataset), { status: 201 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            deleted: true,
            dataset_id: persistedDataset.dataset_id,
            namespace: persistedDataset.namespace,
          }),
          { status: 200 },
        ),
      );

    const catalog = await getPersistedEvaluationDatasets({
      namespace: 'tenant-a',
    });
    const detail = await getPersistedEvaluationDataset(persistedDataset.dataset_id);
    const created = await persistEvaluationDataset({
      namespace: 'tenant-a',
      dataset: { schema_version: 1 },
      retention_days: 30,
    });
    const deleted = await deletePersistedEvaluationDataset(
      persistedDataset.dataset_id,
      'tenant-a',
    );

    expect(catalog.ok && catalog.data.total).toBe(1);
    expect(detail.ok && detail.data.cases[1]?.case_id).toBe('repeat');
    expect(created.ok && created.data.namespace).toBe('tenant-a');
    expect(deleted.ok && deleted.data.deleted).toBe(true);
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      'namespace=tenant-a&offset=0&limit=20',
    );
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"retention_days":30'),
      }),
    );
    expect(fetchMock.mock.calls[3]?.[0]).toContain(
      `/${persistedDataset.dataset_id}?namespace=tenant-a`,
    );
  });
});
