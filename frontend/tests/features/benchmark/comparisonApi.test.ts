import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { compareEvaluationRuns } from '@/features/benchmark/api/comparisonApi';
import type { EvaluationRunHistoryDetail } from '@/features/benchmark/types';

import { benchmarkResult } from './support';

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

describe('comparison API client', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts exactly two retained run IDs to the canonical comparison endpoint', async () => {
    const baseline = detail('a'.repeat(32));
    const candidate = detail('b'.repeat(32));
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          baseline,
          candidate,
          compatibility: {
            status: 'compatible',
            can_compare: true,
            incompatibilities: [],
            warnings: [],
            case_evidence: 'not_retained',
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
        }),
        { status: 200 },
      ),
    );

    const response = await compareEvaluationRuns({
      baseline_run_id: baseline.run_id,
      candidate_run_id: candidate.run_id,
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/evaluations/runs/compare'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          baseline_run_id: baseline.run_id,
          candidate_run_id: candidate.run_id,
        }),
      }),
    );
  });
});
