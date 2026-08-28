import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { EvaluationComparisonMetricDeltas } from '@/features/benchmark/comparisonTypes';
import { EvaluationRunComparisonMetrics } from '@/features/benchmark/components/history/EvaluationRunComparisonMetrics';

import { benchmarkResult } from './support';

describe('EvaluationRunComparisonMetrics', () => {
  it('keeps reuse and savings as contextual signals instead of quality judgments', () => {
    const baseline = {
      ...benchmarkResult.metrics,
      hit_rate: 0.5,
      f1_score: 0.8,
      provider_calls: 2,
      provider_calls_avoided: 0,
    };
    const candidate = {
      ...baseline,
      hit_rate: 0.7,
      f1_score: 0.9,
      provider_calls: 1,
      provider_calls_avoided: 1,
    };
    const deltas: EvaluationComparisonMetricDeltas = {
      measured_threshold: 0,
      total_queries: 0,
      cache_hits: 1,
      cache_misses: -1,
      provider_calls: -1,
      provider_calls_avoided: 1,
      hit_rate: 0.2,
      average_latency_ms: 0,
      median_latency_ms: 0,
      p95_latency_ms: 0,
      average_cache_hit_latency_ms: 0,
      average_cache_miss_latency_ms: 0,
      estimated_latency_saved_ms: 100,
      estimated_provider_cost_saved_usd: 0.01,
      estimated_tokens_saved: 100,
      true_positive_hits: 0,
      true_negative_misses: 0,
      false_positive_hits: 0,
      false_negative_misses: 0,
      precision: 0,
      recall: 0,
      f1_score: 0.1,
    };

    render(
      <EvaluationRunComparisonMetrics
        baseline={baseline}
        baselineThreshold={0.9}
        candidate={candidate}
        candidateThreshold={0.9}
        deltas={deltas}
      />,
    );

    const cards = screen.getAllByRole('article');
    const cardText = (label: string): string => {
      const card = cards.find((item) => item.textContent?.includes(label));
      if (card === undefined) {
        throw new Error(`Expected comparison card for ${label}.`);
      }
      return card.textContent ?? '';
    };

    expect(cardText('F1 score')).toContain('Improved · higher is better');
    expect(cardText('Hit rate')).toContain('Changed · no quality direction implied');
    expect(cardText('Hit rate')).not.toContain('Improved');
    expect(cardText('Provider calls')).toContain(
      'Changed · efficiency signal; assess with correctness metrics',
    );
    expect(cardText('Provider calls')).not.toContain('Improved');
    expect(cardText('Provider calls')).not.toContain('Regressed');
    expect(cardText('Estimated tokens saved')).toContain(
      'Changed · efficiency signal; assess with correctness metrics',
    );
  });
});
