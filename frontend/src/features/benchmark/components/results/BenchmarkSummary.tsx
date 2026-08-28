import type { JSX } from 'react';

import {
  formatCount,
  formatDecimal,
  formatLatency,
  formatPercent,
  formatUsd,
} from '@/shared/lib/formatters';

import type { BenchmarkRunResponse } from '@/features/benchmark/types';

interface BenchmarkSummaryProps {
  result: BenchmarkRunResponse;
}

interface MetricProps {
  label: string;
  tone?: 'gold' | 'teal' | 'coral';
  value: string;
}

const TONE_CLASS: Record<NonNullable<MetricProps['tone']>, string> = {
  gold: 'text-(--gold)',
  teal: 'text-(--teal)',
  coral: 'text-(--coral-text)',
};

function Metric({ label, tone, value }: Readonly<MetricProps>): JSX.Element {
  const valueClass = tone === undefined ? 'text-(--text)' : TONE_CLASS[tone];

  return (
    <div className="border-t border-(--hairline) pt-3">
      <dt className="ui-label text-(--text-faint)">{label}</dt>
      <dd className={`font-data mt-2 text-lg tabular-nums ${valueClass}`}>{value}</dd>
    </div>
  );
}

export function BenchmarkSummary({
  result,
}: Readonly<BenchmarkSummaryProps>): JSX.Element {
  const { metrics } = result;
  const metricItems = [
    {
      label: 'Total queries',
      value: formatCount(metrics.total_queries),
    },
    {
      label: 'Cache hit rate',
      tone: 'gold',
      value: formatPercent(metrics.hit_rate),
    },
    {
      label: 'Provider calls',
      tone: 'coral',
      value: formatCount(metrics.provider_calls),
    },
    {
      label: 'Calls avoided',
      tone: 'teal',
      value: formatCount(metrics.provider_calls_avoided),
    },
    {
      label: 'True-positive hits',
      tone: 'teal',
      value: formatCount(metrics.true_positive_hits),
    },
    {
      label: 'True-negative misses',
      tone: 'teal',
      value: formatCount(metrics.true_negative_misses),
    },
    {
      label: 'False-positive hits',
      tone: 'coral',
      value: formatCount(metrics.false_positive_hits),
    },
    {
      label: 'False-negative misses',
      tone: 'coral',
      value: formatCount(metrics.false_negative_misses),
    },
    {
      label: 'Average latency',
      value: formatLatency(metrics.average_latency_ms),
    },
    {
      label: 'Median latency',
      value: formatLatency(metrics.median_latency_ms),
    },
    {
      label: 'P95 latency',
      value: formatLatency(metrics.p95_latency_ms),
    },
    {
      label: 'Hit / miss latency',
      value: `${formatLatency(
        metrics.average_cache_hit_latency_ms,
      )} / ${formatLatency(metrics.average_cache_miss_latency_ms)}`,
    },
    {
      label: 'Precision',
      value: formatPercent(metrics.precision),
    },
    {
      label: 'Recall',
      value: formatPercent(metrics.recall),
    },
    {
      label: 'F1 score',
      value: formatDecimal(metrics.f1_score, 3),
    },
    {
      label: 'Est. latency saved',
      value: formatLatency(metrics.estimated_latency_saved_ms),
    },
    {
      label: 'Est. tokens saved',
      value: formatCount(metrics.estimated_tokens_saved),
    },
    {
      label: 'Est. provider cost saved',
      tone: 'teal',
      value: formatUsd(metrics.estimated_provider_cost_saved_usd, 4),
    },
  ] satisfies MetricProps[];

  return (
    <section aria-labelledby="benchmark-summary-heading" className="mt-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="ui-label text-(--teal)">Measured run</p>
          <h2
            className="font-display mt-1 text-2xl italic"
            id="benchmark-summary-heading"
          >
            {result.dataset.name}
          </h2>
          <p className="font-data mt-2 text-xs text-(--text-muted)">
            Threshold {formatDecimal(result.threshold, 2)} -{' '}
            {formatCount(result.repetitions)} repetition
            {result.repetitions === 1 ? '' : 's'}
          </p>
        </div>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
        {metricItems.map((metric) => (
          <Metric
            key={metric.label}
            label={metric.label}
            value={metric.value}
            {...('tone' in metric ? { tone: metric.tone } : {})}
          />
        ))}
      </dl>

      <section
        aria-labelledby="benchmark-reproducibility-heading"
        className="mt-8 border-y border-(--hairline) py-5"
      >
        <h3
          className="ui-label text-(--text-muted)"
          id="benchmark-reproducibility-heading"
        >
          Run identity and safe reproducibility metadata
        </h3>
        <dl className="font-data mt-4 grid gap-x-8 gap-y-4 text-[10px]/5 sm:grid-cols-2">
          <div>
            <dt className="text-(--text-faint)">Run ID</dt>
            <dd className="mt-1 break-all text-(--text-soft)">{result.run_id}</dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Started / completed</dt>
            <dd className="mt-1 text-(--text-soft)">
              <time dateTime={result.started_at}>
                {new Date(result.started_at).toLocaleString()}
              </time>{' '}
              /{' '}
              <time dateTime={result.completed_at}>
                {new Date(result.completed_at).toLocaleString()}
              </time>
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Dataset identity</dt>
            <dd className="mt-1 break-all text-(--text-soft)">
              {result.dataset.dataset_id} · {result.dataset.dataset_source}
              {result.dataset.schema_version === null
                ? ''
                : ` schema v${result.dataset.schema_version}`}{' '}
              · dataset v{result.dataset.version} - {result.dataset.digest}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Measured configuration</dt>
            <dd className="mt-1 text-(--text-soft)">
              Threshold {formatDecimal(result.reproducibility.measured_threshold, 2)} -{' '}
              {result.repetitions} repetition
              {result.repetitions === 1 ? '' : 's'} - cache reset{' '}
              {result.reset_cache_before_run
                ? 'before every repetition'
                : 'disabled within this run'}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Provider categories</dt>
            <dd className="mt-1 text-(--text-soft)">
              {result.reproducibility.embedding_provider_category} embeddings
              {' / '}
              {result.reproducibility.generation_provider_category} generation
              {' - '}
              {result.reproducibility.embedding_dimensions} dimensions
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Normalization</dt>
            <dd className="mt-1 break-all text-(--text-soft)">
              {result.reproducibility.normalization_mode} -{' '}
              {result.reproducibility.normalization_fingerprint}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Embedding-space fingerprint</dt>
            <dd className="mt-1 break-all text-(--text-soft)">
              {result.reproducibility.embedding_space_fingerprint}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Configuration fingerprint</dt>
            <dd className="mt-1 break-all text-(--text-soft)">
              {result.reproducibility.configuration_fingerprint}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Application / timeout</dt>
            <dd className="mt-1 text-(--text-soft)">
              API {result.reproducibility.application_version} -{' '}
              {formatDecimal(result.reproducibility.evaluation_timeout_seconds, 0)} s
              wall-clock limit
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Threshold list</dt>
            <dd className="mt-1 text-(--text-soft)">
              {result.reproducibility.evaluation_thresholds
                .map((threshold) => formatDecimal(threshold, 2))
                .join(', ')}
            </dd>
          </div>
        </dl>
      </section>

      <p className="font-data mt-5 text-[10px]/5 text-(--text-faint)">
        Latency and classification values are measured. Latency saved, token count,
        provider cost savings, and threshold-series latency are estimates based on this
        run - not billing records or exact token usage.
      </p>
    </section>
  );
}
