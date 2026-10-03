import { describe, expect, it } from 'vitest';

import { decodeEvaluationRunComparison } from '@/features/benchmark/api/comparisonDecoders';
import type { EvaluationRunHistoryDetail } from '@/features/benchmark/types';

import { benchmarkResult } from './support';

function retainedDetail(runId: string): EvaluationRunHistoryDetail {
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

function compatiblePayload() {
  const baseline = retainedDetail('a'.repeat(32));
  const candidate = retainedDetail('b'.repeat(32));
  return {
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
  };
}

describe('comparison decoder', () => {
  it('decodes aggregate-only compatible comparison evidence', () => {
    const decoded = decodeEvaluationRunComparison(compatiblePayload());

    expect(decoded.compatibility.status).toBe('compatible');
    expect(decoded.metric_deltas?.provider_calls).toBe(0);
    expect(decoded.threshold_deltas).toHaveLength(3);
    expect(decoded.compatibility.case_evidence).toBe('not_retained');
  });

  it('rejects inconsistent compatibility status and deltas', () => {
    const payload = compatiblePayload();
    payload.compatibility.status = 'incompatible';

    expect(() => decodeEvaluationRunComparison(payload)).toThrow(
      'Invalid evaluation comparison compatibility accounting',
    );
  });

  it('rejects query-level evidence hidden inside comparison runs', () => {
    const payload = compatiblePayload();
    Object.assign(payload.baseline, {
      query_results: benchmarkResult.query_results,
    });

    expect(() => decodeEvaluationRunComparison(payload)).toThrow(
      'Invalid evaluation run comparison',
    );
  });

  it('rejects threshold delta kinds that disagree with retained evidence', () => {
    const payload = compatiblePayload();
    const firstDelta = payload.threshold_deltas[0];
    if (firstDelta === undefined) {
      throw new Error('Expected a threshold comparison delta fixture.');
    }

    payload.threshold_deltas[0] = {
      ...firstDelta,
      baseline_result_kind: 'measured',
    };

    expect(() => decodeEvaluationRunComparison(payload)).toThrow(
      'Invalid evaluation comparison threshold accounting',
    );
  });
});
