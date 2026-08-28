import { describe, expect, it } from 'vitest';

import {
  decodeBenchmarkDatasets,
  decodeBenchmarkRun,
  decodeEvaluationDatasetPreview,
  decodePersistedEvaluationDatasetDetail,
  decodePersistedEvaluationDatasets,
} from '@/features/benchmark/api/benchmarkDecoders';
import type { BenchmarkRunResponse } from '@/features/benchmark/types';
import {
  benchmarkAnalysisResult,
  benchmarkDataset,
  benchmarkResult,
  persistedDataset,
} from './support';

interface InvalidRunCase {
  mutate: (value: BenchmarkRunResponse) => void;
  name: string;
}

const INVALID_RUN_CASES: InvalidRunCase[] = [
  {
    name: 'an invalid run ID',
    mutate: (value) => {
      value.run_id = 'not-a-run-id';
    },
  },
  {
    name: 'zero repetitions',
    mutate: (value) => {
      value.repetitions = 0;
    },
  },
  {
    name: 'more than five repetitions',
    mutate: (value) => {
      value.repetitions = 6;
    },
  },
  {
    name: 'fewer than two threshold evaluations',
    mutate: (value) => {
      value.threshold_evaluations = value.threshold_evaluations.slice(0, 1);
    },
  },
  {
    name: 'an empty query-result workload',
    mutate: (value) => {
      value.query_results = [];
    },
  },
  {
    name: 'cache totals that do not cover every query',
    mutate: (value) => {
      value.metrics.cache_misses = 0;
    },
  },
  {
    name: 'provider totals that do not cover every query',
    mutate: (value) => {
      value.metrics.provider_calls_avoided = 0;
    },
  },
  {
    name: 'confusion totals that do not match query evidence',
    mutate: (value) => {
      value.metrics.true_positive_hits = 0;
      value.metrics.true_negative_misses = 2;
    },
  },
  {
    name: 'a cache hit without a matched key',
    mutate: (value) => {
      const hit = value.query_results.find((query) => query.actual_cache_hit);
      if (hit !== undefined) {
        hit.matched_cache_key = null;
      }
    },
  },
  {
    name: 'a missing measured threshold label',
    mutate: (value) => {
      for (const evaluation of value.threshold_evaluations) {
        evaluation.result_kind = 'projected';
      }
    },
  },
  {
    name: 'threshold confusion totals that do not cover the workload',
    mutate: (value) => {
      const evaluation = value.threshold_evaluations[0];
      if (evaluation !== undefined) {
        evaluation.true_negative_misses = 0;
      }
    },
  },
  {
    name: 'reproducibility metadata that differs from the run',
    mutate: (value) => {
      value.reproducibility.dataset_digest = 'e'.repeat(64);
    },
  },
  {
    name: 'a dataset source that differs from reproducibility metadata',
    mutate: (value) => {
      value.reproducibility.dataset_source = 'inline';
      value.reproducibility.dataset_schema_version = 1;
    },
  },
  {
    name: 'a missing reproducibility measured threshold',
    mutate: (value) => {
      Reflect.deleteProperty(value.reproducibility, 'measured_threshold');
    },
  },
  {
    name: 'a reproducibility measured threshold that differs from the run',
    mutate: (value) => {
      value.reproducibility.measured_threshold = 0.95;
    },
  },
  {
    name: 'an invalid generation configuration fingerprint',
    mutate: (value) => {
      value.reproducibility.generation_configuration_fingerprint = 'unsafe';
    },
  },
  {
    name: 'an invalid comparison contract version',
    mutate: (value) => {
      value.reproducibility.comparison_contract_version = 2 as never;
    },
  },
  {
    name: 'an invalid history retention state',
    mutate: (value) => {
      value.history_retention.state = 'unknown' as never;
    },
  },
  {
    name: 'completion before the start time',
    mutate: (value) => {
      value.completed_at = '2026-07-17T09:59:59Z';
    },
  },
  {
    name: 'a workload/result-count mismatch',
    mutate: (value) => {
      value.dataset.query_count = 3;
      value.dataset.expected_misses = 2;
    },
  },
  {
    name: 'a metrics/result-count mismatch',
    mutate: (value) => {
      value.metrics.total_queries = 3;
      value.metrics.cache_misses = 2;
      value.metrics.provider_calls = 2;
    },
  },
];

describe('benchmark decoders', () => {
  it('accepts a response that satisfies the backend contract', () => {
    expect(decodeBenchmarkRun(structuredClone(benchmarkResult))).toEqual(
      benchmarkResult,
    );
  });

  it('accepts reconciled evidence covering all four confusion outcomes', () => {
    expect(decodeBenchmarkRun(structuredClone(benchmarkAnalysisResult))).toEqual(
      benchmarkAnalysisResult,
    );
  });

  it.each(INVALID_RUN_CASES)('rejects $name', ({ mutate }) => {
    const value = structuredClone(benchmarkResult);
    mutate(value);

    expect(() => decodeBenchmarkRun(value)).toThrow();
  });

  it('rejects empty dataset names, descriptions, and categories', () => {
    for (const mutate of [
      (value: typeof benchmarkDataset) => {
        value.name = '';
      },
      (value: typeof benchmarkDataset) => {
        value.description = '';
      },
      (value: typeof benchmarkDataset) => {
        value.categories = [];
      },
    ]) {
      const value = structuredClone(benchmarkDataset);
      mutate(value);

      expect(() =>
        decodeBenchmarkDatasets({
          datasets: [value],
          default_dataset_id: value.dataset_id,
        }),
      ).toThrow();
    }
  });

  it('rejects zero or inconsistent dataset accounting', () => {
    const zeroCount = structuredClone(benchmarkDataset);
    zeroCount.query_count = 0;
    zeroCount.expected_hits = 0;
    zeroCount.expected_misses = 0;

    const inconsistent = structuredClone(benchmarkDataset);
    inconsistent.expected_misses = 0;

    for (const value of [zeroCount, inconsistent]) {
      expect(() =>
        decodeBenchmarkDatasets({
          datasets: [value],
          default_dataset_id: value.dataset_id,
        }),
      ).toThrow();
    }
  });

  it('rejects a default dataset that is absent from the response', () => {
    expect(() =>
      decodeBenchmarkDatasets({
        datasets: [benchmarkDataset],
        default_dataset_id: 'extended',
      }),
    ).toThrow();
  });

  it('accepts bounded custom categories and a strict imported preview', () => {
    const custom = structuredClone(benchmarkResult);
    custom.dataset = {
      ...custom.dataset,
      dataset_id: 'custom:1234567890abcdef',
      dataset_source: 'inline',
      schema_version: 1,
      categories: ['domain-specific'],
    };
    custom.reproducibility = {
      ...custom.reproducibility,
      dataset_id: custom.dataset.dataset_id,
      dataset_source: 'inline',
      dataset_schema_version: 1,
    };

    expect(decodeBenchmarkRun(custom).dataset.categories).toEqual(['domain-specific']);
    expect(
      decodeEvaluationDatasetPreview({
        schema_version: 1,
        dataset_id: 'custom:1234567890abcdef',
        digest: 'd'.repeat(64),
        name: 'Custom set',
        description: null,
        case_count: 1,
        expected_hits: 0,
        expected_misses: 1,
        categories: ['domain-specific'],
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
      }).provider_calls_made,
    ).toBe(0);
  });

  it('strictly decodes persisted catalog metadata and ordered detail', () => {
    const catalog = {
      storage_mode: 'postgres',
      persistence_enabled: true,
      items: [
        {
          ...persistedDataset,
          cases: undefined,
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
      has_more: false,
      limits: {
        default_retention_days: 30,
        max_retention_days: 365,
        max_persisted_per_namespace: 100,
      },
    };

    expect(decodePersistedEvaluationDatasets(catalog).items[0]?.name).toBe(
      persistedDataset.name,
    );
    expect(
      decodePersistedEvaluationDatasetDetail(persistedDataset).cases[1]
        ?.expected_match_case_id,
    ).toBe('seed');
  });

  it('rejects inconsistent catalog capability, expiry, and case ordering', () => {
    expect(() =>
      decodePersistedEvaluationDatasets({
        storage_mode: 'session',
        persistence_enabled: false,
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
    ).toThrow();

    expect(() =>
      decodePersistedEvaluationDatasetDetail({
        ...persistedDataset,
        expires_at: persistedDataset.created_at,
      }),
    ).toThrow();

    const reordered = structuredClone(persistedDataset);
    reordered.cases.reverse();
    expect(() => decodePersistedEvaluationDatasetDetail(reordered)).toThrow();
  });

  it('rejects inconsistent preview limits and provider-call accounting', () => {
    const preview = {
      schema_version: 1,
      dataset_id: 'custom:1234567890abcdef',
      digest: 'd'.repeat(64),
      name: 'Custom set',
      description: null,
      case_count: 1,
      expected_hits: 0,
      expected_misses: 1,
      categories: ['domain-specific'],
      decoded_bytes: 120,
      warnings: [],
      query_executions: 1,
      threshold_projection_evaluations: 3,
      maximum_provider_calls: 2,
      provider_calls_made: 0,
      limits: {
        max_cases: 50,
        max_decoded_bytes: 49_152,
        max_workload_queries: 250,
      },
    };

    expect(() => decodeEvaluationDatasetPreview(preview)).toThrow();
  });
});
