import { Alert, Button, PageHeader } from '@/shared/components/ui';
import {
  formatCount,
  formatHoursMinutesDuration,
  formatLatency,
  formatTimestamp,
} from '@/shared/lib/formatters';
import {
  RUNTIME_METRICS_REFRESH_INTERVAL_MS,
  useRuntimeMetrics,
} from '../hooks/useRuntimeMetrics';
import { RuntimeDiagnosticsPanel } from './RuntimeDiagnosticsPanel';
import { MetricsSkeleton } from './MetricsSkeleton';
import { MetricTile } from './MetricTile';

import type { JSX } from 'react';

interface MetricItem {
  description: string;
  label: string;
  value: string;
}

interface MetricGroupProps {
  items: MetricItem[];
  title: string;
}

function MetricGroup({ items, title }: Readonly<MetricGroupProps>): JSX.Element {
  return (
    <section>
      <h2 className="ui-label text-(--gold)">{title}</h2>

      <dl className="mt-3 flex flex-wrap gap-px border border-(--hairline) bg-(--hairline)">
        {items.map((item) => (
          <MetricTile
            key={item.label}
            description={item.description}
            label={item.label}
            value={item.value}
          />
        ))}
      </dl>
    </section>
  );
}

export function ObservabilityDashboard(): JSX.Element {
  const { isRefreshing, refreshError, state, refresh } = useRuntimeMetrics();

  const metricGroups: MetricGroupProps[] =
    state.status === 'ready'
      ? [
          {
            title: 'Traffic',
            items: [
              {
                description: 'Interactive query requests accepted.',
                label: 'Requests',
                value: formatCount(state.data.request_count),
              },
              {
                description: 'Query workflows that ended with an error.',
                label: 'Errors',
                value: formatCount(state.data.error_count),
              },
              {
                description: 'Generation attempts made on cache misses.',
                label: 'Provider calls',
                value: formatCount(state.data.provider_calls),
              },
              {
                description: 'Followers currently sharing an in-flight request.',
                label: 'Coalesced now',
                value: formatCount(state.data.in_flight_coalesced_requests),
              },
            ],
          },
          {
            title: 'Cache',
            items: [
              {
                description: 'Entries in the active embedding space.',
                label: 'Entries',
                value: formatCount(state.data.cache_size),
              },
              {
                description: 'Lookups served from cache.',
                label: 'Hits',
                value: formatCount(state.data.cache_hits),
              },
              {
                description: 'Lookups that required generation.',
                label: 'Misses',
                value: formatCount(state.data.cache_misses),
              },
              {
                description: 'Entries removed by the size limit.',
                label: 'Evictions',
                value: formatCount(state.data.evictions),
              },
              {
                description: 'Entries removed after TTL expiry.',
                label: 'Expirations',
                value: formatCount(state.data.expirations),
              },
            ],
          },
          {
            title: 'Latency',
            items: [
              {
                description: 'Mean latency across completed requests.',
                label: 'Average',
                value: formatLatency(state.data.average_latency_ms),
              },
              {
                description: '95th percentile of the bounded recent sample.',
                label: 'P95',
                value: formatLatency(state.data.p95_latency_ms),
              },
              {
                description: 'Completed requests in the P95 sample window.',
                label: 'Sample size',
                value: formatCount(state.data.latency_sample_size),
              },
            ],
          },
        ]
      : [];

  return (
    <div>
      <PageHeader
        actions={
          <Button
            aria-busy={isRefreshing}
            className="border-(--hairline) bg-(--surface) text-(--text-soft) hover:border-(--gold) hover:text-(--gold) focus-visible:outline-(--gold)"
            disabled={isRefreshing || state.status === 'loading'}
            variant="secondary"
            onClick={refresh}
          >
            Refresh metrics
          </Button>
        }
        className="border-b border-(--hairline) pb-6"
        description="Query traffic, cache decisions, generation attempts, coalescing, and latency from one server process. This workbench does not collect snapshots from embedded application caches."
        eyebrow="Live process telemetry"
        title="Observability"
        tone="teal"
      />

      <div className="mt-8">
        {state.status === 'loading' && <MetricsSkeleton />}

        {state.status === 'error' && (
          <Alert
            className="border border-(--coral) bg-(--surface) p-6"
            title="Metrics unavailable"
            tone="error"
          >
            <p className="mt-3 text-sm text-(--text-muted)">
              {state.error.detail ??
                'The runtime metrics endpoint could not be reached.'}
            </p>
          </Alert>
        )}

        {state.status === 'ready' && refreshError !== null && (
          <Alert
            className="mb-6 border border-(--hairline) bg-(--surface) p-4"
            title="Metrics refresh failed"
            aria-live="polite"
            tone="error"
          >
            <p className="mt-2 text-sm text-(--text-muted)">
              {refreshError.detail ?? 'The metrics endpoint could not be reached.'}
            </p>
            <p className="mt-2 text-xs/5 text-(--text-soft)">
              Showing the last successful observation:{' '}
              {formatTimestamp(state.data.observed_at)}. Counts may be stale; refresh to
              confirm the current process state.
            </p>
          </Alert>
        )}

        {state.status === 'ready' && (
          <div className="space-y-8">
            <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-(--hairline) pb-4 text-xs text-(--text-faint)">
              <span>
                Observed:{' '}
                <time dateTime={state.data.observed_at}>
                  {formatTimestamp(state.data.observed_at)}
                </time>
              </span>

              <span>
                Auto-refresh: {formatCount(RUNTIME_METRICS_REFRESH_INTERVAL_MS / 1_000)}{' '}
                seconds
              </span>

              <span>
                Process uptime: {formatHoursMinutesDuration(state.data.uptime_seconds)}
              </span>

              <span>Samples: {formatCount(state.data.latency_sample_size)}</span>

              {isRefreshing && (
                <output aria-live="polite" className="ui-label text-(--gold)">
                  Refreshing runtime metrics
                </output>
              )}
            </div>

            {metricGroups.map((group) => (
              <MetricGroup key={group.title} items={group.items} title={group.title} />
            ))}
          </div>
        )}
      </div>

      <RuntimeDiagnosticsPanel />
    </div>
  );
}
