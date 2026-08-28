import type { CacheStatsResponse } from '@/features/cache/types';
import { formatCount, formatLatency, formatPercent } from '@/shared/lib/formatters';
import {
  hasSimilarityScore,
  meetsSimilarityThreshold,
} from '@/shared/domain/similarity';
import type { QueryTrace } from '../types';

import type { JSX } from 'react';

interface FieldMetricsProps {
  cacheStats: CacheStatsResponse | null;
  threshold: number;
  traces: QueryTrace[];
}

interface MetricRowProps {
  detail: string;
  label: string;
  value: string;
  tone?: 'gold' | 'teal' | 'coral';
}

const TONE_COLOR: Record<NonNullable<MetricRowProps['tone']>, string> = {
  gold: 'var(--gold)',
  teal: 'var(--teal)',
  coral: 'var(--coral-text)',
};

function MetricRow({
  detail,
  label,
  value,
  tone,
}: Readonly<MetricRowProps>): JSX.Element {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-(--hairline) py-4">
      <dt className="ui-label text-(--text-muted)">
        {label}
        <span className="mt-1 block max-w-sm text-[11px]/4 font-normal normal-case tracking-normal text-(--text-faint)">
          {detail}
        </span>
      </dt>
      <dd
        className="font-data shrink-0 text-right text-lg tabular-nums"
        style={tone === undefined ? undefined : { color: TONE_COLOR[tone] }}
      >
        {value}
      </dd>
    </div>
  );
}

export function FieldMetrics({
  cacheStats,
  threshold,
  traces,
}: Readonly<FieldMetricsProps>): JSX.Element {
  const scoredTraces = traces.filter(
    (trace): trace is QueryTrace & { similarity: number } =>
      hasSimilarityScore(trace.similarity),
  );
  const unscoredCount = traces.length - scoredTraces.length;
  const projectedHits = scoredTraces.filter((trace) =>
    meetsSimilarityThreshold(trace.similarity, threshold),
  ).length;
  const projectedHitRate =
    scoredTraces.length === 0 ? null : projectedHits / scoredTraces.length;
  const meanLatency =
    traces.length === 0
      ? null
      : traces.reduce((total, trace) => total + trace.latencyMs, 0) / traces.length;
  const providerCalls = traces.filter((trace) => trace.providerCalled).length;
  const backendRequestCount =
    cacheStats === null ? 0 : cacheStats.hits + cacheStats.misses;
  const backendHitRate =
    cacheStats === null || backendRequestCount === 0
      ? null
      : cacheStats.hits / backendRequestCount;
  const metricItems = [
    {
      detail: 'scored visible traces at or above threshold ÷ scored visible traces',
      label: 'Frontend projected hit rate',
      tone: 'gold',
      value: formatPercent(projectedHitRate),
    },
    {
      detail: 'backend hits ÷ (backend hits + backend misses), since the last reset',
      label: 'Actual backend hit rate',
      value: formatPercent(backendHitRate),
    },
    {
      detail: 'visible traces with a score ÷ visible traces without a score',
      label: 'Scored / unscored queries',
      value: `${formatCount(scoredTraces.length)} / ${formatCount(unscoredCount)}`,
    },
    {
      detail: 'sum of visible trace latency ÷ visible traces',
      label: 'Mean latency',
      tone: 'teal',
      value: formatLatency(meanLatency),
    },
    {
      detail: 'visible successful traces where backend cache_hit is false',
      label: 'Provider calls (visible)',
      tone: 'coral',
      value: formatCount(providerCalls),
    },
    {
      detail: 'current number of entries reported by the backend cache',
      label: 'Cache entries',
      value: formatCount(cacheStats?.size),
    },
  ] satisfies MetricRowProps[];

  return (
    <aside aria-labelledby="metrics-heading">
      <header className="mb-5">
        <h2 className="font-display text-2xl italic" id="metrics-heading">
          Field readings
        </h2>
        <p className="ui-label mt-1 text-(--text-faint)">
          Primary evidence / formulas shown
        </p>
      </header>

      <dl className="border-t border-(--hairline)">
        {metricItems.map((metric) => (
          <MetricRow
            key={metric.label}
            detail={metric.detail}
            label={metric.label}
            value={metric.value}
            {...('tone' in metric ? { tone: metric.tone } : {})}
          />
        ))}
      </dl>

      <p className="mt-5 text-xs/5 text-(--text-muted)">
        Projection changes with the selected threshold and excludes unscored traces.
        Backend hit rate remains the historical accounting record.
      </p>
    </aside>
  );
}
