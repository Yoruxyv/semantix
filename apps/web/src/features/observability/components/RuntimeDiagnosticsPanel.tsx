import { Alert, Button } from '@/shared/components/ui';
import { formatBytes, formatCount, formatTimestamp } from '@/shared/lib/formatters';

import { useRuntimeDiagnostics } from '../hooks/useRuntimeDiagnostics';
import type { RuntimeDiagnostics } from '../types';

import type { JSX, ReactNode } from 'react';

interface DiagnosticItem {
  label: string;
  value: ReactNode;
}

interface DiagnosticGroup {
  items: DiagnosticItem[];
  title: string;
}

function fingerprint(value: string): JSX.Element {
  return <span className="font-data break-all text-xs">{value}</span>;
}

function enabled(value: boolean): string {
  return value ? 'Enabled' : 'Disabled';
}

function groups(data: RuntimeDiagnostics): DiagnosticGroup[] {
  return [
    {
      title: 'Provider and cache environment',
      items: [
        { label: 'Embedding provider', value: data.embedding_provider_category },
        { label: 'Generation provider', value: data.generation_provider_category },
        {
          label: 'Embedding dimensions',
          value: formatCount(data.embedding_dimensions),
        },
        { label: 'Cache backend', value: data.cache_backend },
      ],
    },
    {
      title: 'Matching configuration',
      items: [
        {
          label: 'Embedding-space fingerprint',
          value: fingerprint(data.embedding_space_fingerprint),
        },
        {
          label: 'Generation configuration fingerprint',
          value: fingerprint(data.generation_configuration_fingerprint),
        },
        {
          label: 'Prompt normalization',
          value: `${data.normalization_mode === 'typo_correction' ? 'Enabled' : 'Disabled'} · ${data.normalization_algorithm_version}`,
        },
        {
          label: 'Normalization fingerprint',
          value: fingerprint(data.normalization_fingerprint),
        },
      ],
    },
    {
      title: 'Evaluation safety limits',
      items: [
        {
          label: 'Run timeout',
          value: `${formatCount(data.evaluation_timeout_seconds)} seconds`,
        },
        { label: 'Maximum cases', value: formatCount(data.evaluation_max_cases) },
        {
          label: 'Maximum repetitions',
          value: formatCount(data.evaluation_max_repetitions),
        },
        {
          label: 'Maximum thresholds',
          value: formatCount(data.evaluation_max_thresholds),
        },
        {
          label: 'Maximum request size',
          value: formatBytes(data.evaluation_max_request_bytes),
        },
      ],
    },
    {
      title: 'Process scope and readiness',
      items: [
        { label: 'Scope', value: 'One backend process' },
        {
          label: 'Cache readiness',
          value: data.cache_readiness === 'ready' ? 'Ready' : 'Unavailable',
        },
        { label: 'Application version', value: data.application_version },
        {
          label: 'Dataset persistence',
          value: enabled(data.evaluation_dataset_persistence_enabled),
        },
        {
          label: 'Run-history persistence',
          value: enabled(data.evaluation_history_persistence_enabled),
        },
        { label: 'Observed', value: formatTimestamp(data.observed_at) },
      ],
    },
  ];
}

export function RuntimeDiagnosticsPanel(): JSX.Element {
  const { isRefreshing, isStale, refreshError, state, refresh } =
    useRuntimeDiagnostics();

  return (
    <section
      aria-labelledby="runtime-diagnostics-heading"
      className="mt-12 border-t border-(--hairline) pt-8"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="font-display text-3xl italic" id="runtime-diagnostics-heading">
            Runtime diagnostics
          </h2>
          <p className="mt-2 text-sm/6 text-(--text-muted)">
            Safe, read-only evidence for comparing evaluation environments. The values
            describe this backend process only.
          </p>
        </div>

        <Button
          aria-busy={isRefreshing}
          disabled={isRefreshing || state.status === 'loading'}
          size="large"
          variant="secondary"
          onClick={refresh}
        >
          Refresh diagnostics
        </Button>
      </div>

      {state.status === 'loading' && (
        <output
          aria-label="Loading runtime diagnostics"
          className="mt-6 block border border-(--hairline) bg-(--surface) p-6 text-sm text-(--text-muted)"
        >
          Loading runtime diagnostics
        </output>
      )}

      {state.status === 'error' && (
        <Alert
          className="mt-6 border border-(--coral) bg-(--surface) p-6"
          role="alert"
          title="Diagnostics unavailable"
          tone="error"
        >
          <p className="mt-3 text-sm text-(--text-muted)">
            {state.error.detail ??
              'The runtime diagnostics endpoint could not be reached.'}
          </p>
        </Alert>
      )}

      {state.status === 'ready' && (
        <>
          {(refreshError !== null || isStale) && (
            <Alert
              aria-live="polite"
              className="mt-6 border border-(--hairline) bg-(--surface) p-4"
              title="Diagnostics may be stale"
              tone={refreshError === null ? 'info' : 'error'}
            >
              <p className="mt-2 text-sm text-(--text-muted)">
                {refreshError?.detail ??
                  'Refresh to confirm the current process configuration.'}
              </p>
            </Alert>
          )}

          {isRefreshing && (
            <output aria-live="polite" className="ui-label mt-6 block text-(--gold)">
              Refreshing runtime diagnostics
            </output>
          )}

          <output aria-live="polite" className="sr-only">
            Runtime diagnostics observed {formatTimestamp(state.data.observed_at)}
          </output>

          <div
            className="mt-6 grid grid-cols-1 gap-px border border-(--hairline) bg-(--hairline) lg:grid-cols-2"
            data-runtime-diagnostics-grid
          >
            {groups(state.data).map((group) => (
              <section className="min-w-0 bg-(--surface) p-5" key={group.title}>
                <h3 className="ui-label text-(--gold)">{group.title}</h3>
                <dl className="mt-4 space-y-4">
                  {group.items.map((item) => (
                    <div className="min-w-0" key={item.label}>
                      <dt className="text-xs text-(--text-faint)">{item.label}</dt>
                      <dd className="mt-1 min-w-0 text-sm text-(--text-soft)">
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
