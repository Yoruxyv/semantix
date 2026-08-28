import type { JSX } from 'react';

import type { EvaluationThresholdComparisonDelta } from '@/features/benchmark/comparisonTypes';
import type { ThresholdEvaluation } from '@/features/benchmark/types';
import { formatCount, formatLatency, formatPercent } from '@/shared/lib/formatters';

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

interface DeltaValue {
  label: string;
  baseline: string;
  candidate: string;
  delta: string;
}

function values(
  baseline: ThresholdEvaluation,
  candidate: ThresholdEvaluation,
  delta: EvaluationThresholdComparisonDelta,
): DeltaValue[] {
  return [
    {
      label: 'Hit rate',
      baseline: formatPercent(baseline.hit_rate),
      candidate: formatPercent(candidate.hit_rate),
      delta: signedPercentPoints(delta.hit_rate),
    },
    {
      label: 'Precision',
      baseline: formatPercent(baseline.precision),
      candidate: formatPercent(candidate.precision),
      delta: signedPercentPoints(delta.precision),
    },
    {
      label: 'Recall',
      baseline: formatPercent(baseline.recall),
      candidate: formatPercent(candidate.recall),
      delta: signedPercentPoints(delta.recall),
    },
    {
      label: 'F1',
      baseline: formatPercent(baseline.f1_score),
      candidate: formatPercent(candidate.f1_score),
      delta: signedPercentPoints(delta.f1_score),
    },
    {
      label: 'Average latency',
      baseline: formatLatency(baseline.average_latency_ms),
      candidate: formatLatency(candidate.average_latency_ms),
      delta: signed(delta.average_latency_ms, ' ms'),
    },
    {
      label: 'Calls avoided',
      baseline: formatCount(baseline.provider_calls_avoided),
      candidate: formatCount(candidate.provider_calls_avoided),
      delta: signedCount(delta.provider_calls_avoided),
    },
    {
      label: 'TP / TN',
      baseline: `${formatCount(baseline.true_positive_hits)} / ${formatCount(
        baseline.true_negative_misses,
      )}`,
      candidate: `${formatCount(candidate.true_positive_hits)} / ${formatCount(
        candidate.true_negative_misses,
      )}`,
      delta: `${signedCount(delta.true_positive_hits)} / ${signedCount(
        delta.true_negative_misses,
      )}`,
    },
    {
      label: 'FP / FN',
      baseline: `${formatCount(baseline.false_positive_hits)} / ${formatCount(
        baseline.false_negative_misses,
      )}`,
      candidate: `${formatCount(candidate.false_positive_hits)} / ${formatCount(
        candidate.false_negative_misses,
      )}`,
      delta: `${signedCount(delta.false_positive_hits)} / ${signedCount(
        delta.false_negative_misses,
      )}`,
    },
  ];
}

export function EvaluationRunComparisonThresholds({
  baseline,
  candidate,
  deltas,
}: Readonly<{
  baseline: ThresholdEvaluation[];
  candidate: ThresholdEvaluation[];
  deltas: EvaluationThresholdComparisonDelta[];
}>): JSX.Element {
  const baselineByThreshold = new Map(
    baseline.map((evaluation) => [evaluation.threshold, evaluation]),
  );
  const candidateByThreshold = new Map(
    candidate.map((evaluation) => [evaluation.threshold, evaluation]),
  );

  return (
    <section aria-labelledby="comparison-threshold-heading" className="mt-6">
      <h4 className="ui-label text-(--gold)" id="comparison-threshold-heading">
        Shared threshold projections
      </h4>
      <p className="font-data mt-2 text-[10px]/5 text-(--text-muted)">
        Only thresholds retained by both runs are shown. Projection-list differences
        remain an explicit comparison warning.
      </p>
      <div className="mt-4 grid gap-4">
        {deltas.map((delta) => {
          const baselineEvaluation = baselineByThreshold.get(delta.threshold);
          const candidateEvaluation = candidateByThreshold.get(delta.threshold);
          if (baselineEvaluation === undefined || candidateEvaluation === undefined) {
            return null;
          }

          return (
            <article className="border border-(--hairline) p-4" key={delta.threshold}>
              <header className="flex flex-wrap items-baseline justify-between gap-3">
                <h5 className="text-sm text-(--text)">
                  Threshold {delta.threshold.toFixed(2)}
                </h5>
                <p className="font-data text-[10px]/5 text-(--text-faint)">
                  baseline {delta.baseline_result_kind} · candidate{' '}
                  {delta.candidate_result_kind}
                </p>
              </header>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {values(baselineEvaluation, candidateEvaluation, delta).map((item) => (
                  <dl
                    className="font-data border-t border-(--hairline) pt-3 text-[10px]/5"
                    key={item.label}
                  >
                    <dt className="text-(--text-faint)">{item.label}</dt>
                    <dd className="mt-2 grid gap-2 lg:grid-cols-3">
                      <span>
                        <span className="block text-(--text-faint)">Baseline</span>
                        <span className="text-(--text-soft)">{item.baseline}</span>
                      </span>
                      <span>
                        <span className="block text-(--text-faint)">Candidate</span>
                        <span className="text-(--text-soft)">{item.candidate}</span>
                      </span>
                      <span>
                        <span className="block text-(--text-faint)">Delta</span>
                        <span className="text-(--text)">{item.delta}</span>
                      </span>
                    </dd>
                  </dl>
                ))}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
