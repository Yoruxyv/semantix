import type { JSX } from 'react';

import type { EvaluationComparisonMetricDeltas } from '@/features/benchmark/comparisonTypes';
import type { BenchmarkMetrics } from '@/features/benchmark/types';
import {
  formatCount,
  formatLatency,
  formatPercent,
  formatUsd,
} from '@/shared/lib/formatters';

type Objective = 'higher' | 'lower' | 'changed' | 'efficiency';
type MetricKind = 'measured' | 'estimated';

interface MetricDefinition {
  label: string;
  kind: MetricKind;
  objective: Objective;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  formatValue: (value: number) => string;
  formatDelta: (value: number) => string;
}

function signed(value: number, suffix = ''): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}${suffix}`;
}

function signedCount(value: number): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatCount(value)}`;
}

function signedPercentPoints(value: number): string {
  const points = value * 100;
  const prefix = points > 0 ? '+' : '';
  return `${prefix}${points.toFixed(1)} pp`;
}

function signedUsd(value: number): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatUsd(value)}`;
}

function outcome(delta: number | null, objective: Objective): string {
  if (delta === null || delta === 0) {
    return 'Unchanged';
  }
  if (objective === 'changed' || objective === 'efficiency') {
    return 'Changed';
  }
  const improved =
    (objective === 'higher' && delta > 0) || (objective === 'lower' && delta < 0);
  return improved ? 'Improved' : 'Regressed';
}

function objectiveDescription(objective: Objective): string {
  if (objective === 'higher') {
    return 'higher is better';
  }
  if (objective === 'lower') {
    return 'lower is better';
  }
  if (objective === 'efficiency') {
    return 'efficiency signal; assess with correctness metrics';
  }
  return 'no quality direction implied';
}

function MetricCard({ metric }: Readonly<{ metric: MetricDefinition }>): JSX.Element {
  return (
    <article className="border border-(--hairline) p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h5 className="text-sm text-(--text)">{metric.label}</h5>
        <span className="ui-label text-(--text-faint)">{metric.kind}</span>
      </div>
      <dl className="font-data mt-3 grid gap-3 text-[10px]/5 lg:grid-cols-3">
        <div>
          <dt className="text-(--text-faint)">Baseline</dt>
          <dd className="mt-1 text-(--text-soft)">
            {metric.baseline === null ? 'n/a' : metric.formatValue(metric.baseline)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Candidate</dt>
          <dd className="mt-1 text-(--text-soft)">
            {metric.candidate === null ? 'n/a' : metric.formatValue(metric.candidate)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Candidate − baseline</dt>
          <dd className="mt-1 text-(--text)">
            <span className="block">
              {metric.delta === null ? 'n/a' : metric.formatDelta(metric.delta)}
            </span>
            <span className="mt-1 block text-(--text-muted)">
              {outcome(metric.delta, metric.objective)} ·{' '}
              {objectiveDescription(metric.objective)}
            </span>
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function EvaluationRunComparisonMetrics({
  baseline,
  candidate,
  deltas,
  baselineThreshold,
  candidateThreshold,
}: Readonly<{
  baseline: BenchmarkMetrics;
  candidate: BenchmarkMetrics;
  deltas: EvaluationComparisonMetricDeltas;
  baselineThreshold: number;
  candidateThreshold: number;
}>): JSX.Element {
  const metrics: MetricDefinition[] = [
    {
      label: 'Measured threshold',
      kind: 'measured',
      objective: 'changed',
      baseline: baselineThreshold,
      candidate: candidateThreshold,
      delta: deltas.measured_threshold,
      formatValue: (value) => value.toFixed(2),
      formatDelta: (value) => signed(value),
    },
    {
      label: 'Precision',
      kind: 'measured',
      objective: 'higher',
      baseline: baseline.precision,
      candidate: candidate.precision,
      delta: deltas.precision,
      formatValue: formatPercent,
      formatDelta: signedPercentPoints,
    },
    {
      label: 'Recall',
      kind: 'measured',
      objective: 'higher',
      baseline: baseline.recall,
      candidate: candidate.recall,
      delta: deltas.recall,
      formatValue: formatPercent,
      formatDelta: signedPercentPoints,
    },
    {
      label: 'F1 score',
      kind: 'measured',
      objective: 'higher',
      baseline: baseline.f1_score,
      candidate: candidate.f1_score,
      delta: deltas.f1_score,
      formatValue: formatPercent,
      formatDelta: signedPercentPoints,
    },
    {
      label: 'Hit rate',
      kind: 'measured',
      objective: 'changed',
      baseline: baseline.hit_rate,
      candidate: candidate.hit_rate,
      delta: deltas.hit_rate,
      formatValue: formatPercent,
      formatDelta: signedPercentPoints,
    },
    {
      label: 'True positives',
      kind: 'measured',
      objective: 'higher',
      baseline: baseline.true_positive_hits,
      candidate: candidate.true_positive_hits,
      delta: deltas.true_positive_hits,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'True negatives',
      kind: 'measured',
      objective: 'higher',
      baseline: baseline.true_negative_misses,
      candidate: candidate.true_negative_misses,
      delta: deltas.true_negative_misses,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'False positives',
      kind: 'measured',
      objective: 'lower',
      baseline: baseline.false_positive_hits,
      candidate: candidate.false_positive_hits,
      delta: deltas.false_positive_hits,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'False negatives',
      kind: 'measured',
      objective: 'lower',
      baseline: baseline.false_negative_misses,
      candidate: candidate.false_negative_misses,
      delta: deltas.false_negative_misses,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'Provider calls',
      kind: 'measured',
      objective: 'efficiency',
      baseline: baseline.provider_calls,
      candidate: candidate.provider_calls,
      delta: deltas.provider_calls,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'Provider calls avoided',
      kind: 'measured',
      objective: 'efficiency',
      baseline: baseline.provider_calls_avoided,
      candidate: candidate.provider_calls_avoided,
      delta: deltas.provider_calls_avoided,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'Average latency',
      kind: 'measured',
      objective: 'lower',
      baseline: baseline.average_latency_ms,
      candidate: candidate.average_latency_ms,
      delta: deltas.average_latency_ms,
      formatValue: formatLatency,
      formatDelta: (value) => signed(value, ' ms'),
    },
    {
      label: 'Median latency',
      kind: 'measured',
      objective: 'lower',
      baseline: baseline.median_latency_ms,
      candidate: candidate.median_latency_ms,
      delta: deltas.median_latency_ms,
      formatValue: formatLatency,
      formatDelta: (value) => signed(value, ' ms'),
    },
    {
      label: 'P95 latency',
      kind: 'measured',
      objective: 'lower',
      baseline: baseline.p95_latency_ms,
      candidate: candidate.p95_latency_ms,
      delta: deltas.p95_latency_ms,
      formatValue: formatLatency,
      formatDelta: (value) => signed(value, ' ms'),
    },
    {
      label: 'Estimated latency saved',
      kind: 'estimated',
      objective: 'efficiency',
      baseline: baseline.estimated_latency_saved_ms,
      candidate: candidate.estimated_latency_saved_ms,
      delta: deltas.estimated_latency_saved_ms,
      formatValue: formatLatency,
      formatDelta: (value) => signed(value, ' ms'),
    },
    {
      label: 'Estimated tokens saved',
      kind: 'estimated',
      objective: 'efficiency',
      baseline: baseline.estimated_tokens_saved,
      candidate: candidate.estimated_tokens_saved,
      delta: deltas.estimated_tokens_saved,
      formatValue: formatCount,
      formatDelta: signedCount,
    },
    {
      label: 'Estimated provider cost saved',
      kind: 'estimated',
      objective: 'efficiency',
      baseline: baseline.estimated_provider_cost_saved_usd,
      candidate: candidate.estimated_provider_cost_saved_usd,
      delta: deltas.estimated_provider_cost_saved_usd,
      formatValue: formatUsd,
      formatDelta: signedUsd,
    },
  ];

  return (
    <section aria-labelledby="comparison-metrics-heading" className="mt-6">
      <h4 className="ui-label text-(--teal)" id="comparison-metrics-heading">
        Aggregate metric deltas
      </h4>
      <p className="font-data mt-2 text-[10px]/5 text-(--text-muted)">
        Every delta is candidate minus baseline. Improvement labels state the metric
        objective explicitly; threshold changes are never labeled optimal.
      </p>
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </div>
    </section>
  );
}
