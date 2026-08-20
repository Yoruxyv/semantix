import { useState } from 'react';
import type { ReactNode, JSX } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router';

import { APP_PATHS } from '@/app/navigation/navigationConfig';
import { getCacheEntry } from '../api/cacheApi';
import { MarkdownContent } from '@/shared/components/markdown/MarkdownContent';
import { Alert, InlineConfirmation } from '@/shared/components/ui';
import {
  formatCompactDuration,
  formatCount,
  formatTimestamp,
} from '@/shared/lib/formatters';
import {
  apiErrorFromUnknown,
  dataFromApiResult,
} from '@/shared/query/apiResult';
import { cacheEntryKeys } from '@/shared/query/queryKeys';
import type { CacheEntryMetadata } from '../types';

interface CacheEntryCardProps {
  entry: CacheEntryMetadata;
  isDeleting: boolean;
  isPendingDelete: boolean;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  onRequestDelete: () => void;
}

interface EntryMetric {
  label: string;
  value: ReactNode;
  valueClassName: string;
}

function shortCacheKey(cacheKey: string): string {
  return `${cacheKey.slice(0, 10)}...${cacheKey.slice(-6)}`;
}

function EntryMetricItem({
  label,
  value,
  valueClassName,
}: Readonly<EntryMetric>): JSX.Element {
  return (
    <div>
      <dt className="ui-label text-(--text-faint)">{label}</dt>
      <dd className={valueClassName}>{value}</dd>
    </div>
  );
}

export function CacheEntryCard({
  entry,
  isDeleting,
  isPendingDelete,
  onCancelDelete,
  onConfirmDelete,
  onRequestDelete,
}: Readonly<CacheEntryCardProps>): JSX.Element {
  const location = useLocation();
  const [isResponseExpanded, setIsResponseExpanded] = useState(false);
  const responseRegionId = `cache-response-${entry.cache_key}`;
  const detailQuery = useQuery({
    queryKey: cacheEntryKeys.detail(entry.cache_key),
    queryFn: async ({ signal }) =>
      dataFromApiResult(await getCacheEntry(entry.cache_key, signal)),
    enabled: isResponseExpanded && entry.response_preview_truncated,
    staleTime: 20_000,
    gcTime: 5 * 60_000,
  });
  const status = entry.is_expired
    ? {
        color: 'var(--coral-text)',
        label: 'Expired',
      }
    : {
        color: 'var(--teal)',
        label: 'Active',
      };

  const entryMetrics = [
    {
      label: 'Created',
      value: formatTimestamp(entry.created_at),
      valueClassName: 'font-data mt-1 text-[10px] text-(--text-muted)',
    },
    {
      label: 'Expires',
      value: formatTimestamp(entry.expires_at, 'No expiry'),
      valueClassName: 'font-data mt-1 text-[10px] text-(--text-muted)',
    },
    {
      label: 'TTL remaining',
      value: formatCompactDuration(entry.remaining_ttl_seconds, {
        fallback: 'No expiry',
      }),
      valueClassName: 'font-data mt-1 text-[10px] text-(--gold)',
    },
    {
      label: 'Entry hits',
      value: formatCount(entry.hit_count),
      valueClassName: 'font-data mt-1 text-xs text-(--text-soft)',
    },
    {
      label: 'Last accessed',
      value: formatTimestamp(entry.last_accessed_at),
      valueClassName: 'font-data mt-1 text-[10px] text-(--text-muted)',
    },
    {
      label: 'Recency rank',
      value: `#${formatCount(entry.recency_rank)}`,
      valueClassName: 'font-data mt-1 text-xs text-(--text-soft)',
    },
  ] satisfies EntryMetric[];

  return (
    <li className="border-t border-(--hairline) py-5 transition-colors hover:bg-[rgba(234,230,221,0.025)]">
      <article>
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <span className="ui-label" style={{ color: status.color }}>
                {status.label}
              </span>

              <code
                className="font-data text-[10px] text-(--text-faint)"
                title={entry.cache_key}
              >
                {shortCacheKey(entry.cache_key)}
              </code>

              <span className="font-data text-[10px] text-(--text-muted)">
                namespace / {entry.namespace}
              </span>
            </div>

            <h3 className="mt-2 wrap-break-word text-base text-(--text)">
              {entry.prompt}
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <Link
              className="ui-label min-h-9 border-b border-(--teal) px-1 py-2 text-(--teal) transition-colors hover:text-(--text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--teal)"
              state={{ cacheReturnSearch: location.search }}
              to={`${APP_PATHS.cache}/entries/${entry.cache_key}`}
            >
              View entry details
            </Link>

            {!isPendingDelete && (
              <button
                aria-label={`Delete ${entry.prompt}`}
                className="ui-label min-h-9 border-b border-(--coral) px-1 py-2 text-(--coral-text) transition-colors hover:text-(--text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--coral) active:translate-y-px disabled:opacity-50"
                disabled={isDeleting}
                type="button"
                onClick={onRequestDelete}
              >
                Delete
              </button>
            )}
          </div>
        </header>

        {entry.response_preview_truncated ? (
          <div className="mt-3 min-w-0">
            <p className="text-sm/6 text-(--text-muted)">
              Response preview withheld to preserve complete Markdown syntax.
            </p>
            <button
              aria-controls={responseRegionId}
              aria-expanded={isResponseExpanded}
              className="ui-label mt-2 min-h-9 border-b border-(--teal) px-1 py-2 text-(--teal) transition-colors hover:text-(--text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--teal)"
              type="button"
              onClick={() => setIsResponseExpanded((current) => !current)}
            >
              {isResponseExpanded
                ? 'Hide complete response'
                : 'Inspect complete response'}
            </button>

            {isResponseExpanded && (
              <section
                aria-label={`Complete cached response for ${entry.prompt}`}
                className="mt-3 min-w-0"
                id={responseRegionId}
              >
                {detailQuery.isPending && (
                  <output
                    aria-live="polite"
                    className="font-data text-[11px] text-(--text-faint)"
                  >
                    Loading complete response...
                  </output>
                )}

                {detailQuery.isError && (
                  <Alert
                    className="border-l border-(--coral) pl-3 text-xs text-(--coral-text)"
                    role="alert"
                    tone="error"
                  >
                    {apiErrorFromUnknown(detailQuery.error).detail ??
                      'The complete cached response could not be loaded.'}
                  </Alert>
                )}

                {detailQuery.data !== undefined &&
                  detailQuery.data.response === null && (
                    <Alert
                      className="border-l border-(--coral) pl-3 text-xs text-(--coral-text)"
                      role="alert"
                      tone="error"
                    >
                      The complete response is unavailable from this backend
                      version.
                    </Alert>
                  )}

                {detailQuery.data?.response !== null &&
                  detailQuery.data?.response !== undefined && (
                    <MarkdownContent
                      className="min-w-0 text-sm text-(--text-muted)"
                      density="compact"
                      markdown={detailQuery.data.response}
                    />
                  )}
              </section>
            )}
          </div>
        ) : (
          <MarkdownContent
            className="mt-3 min-w-0 text-sm text-(--text-muted)"
            density="compact"
            markdown={entry.response_preview}
          />
        )}

        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 min-[720px]:grid-cols-3">
          {entryMetrics.map((metric) => (
            <EntryMetricItem key={metric.label} {...metric} />
          ))}
        </dl>

        {isPendingDelete && (
          <InlineConfirmation
            ariaLabel={`Confirm deletion of ${entry.prompt}`}
            className="mt-4"
            confirmAriaLabel={`Confirm delete ${entry.prompt}`}
            confirmLabel="Confirm delete"
            isPending={isDeleting}
            message="Delete this entry? Cached responses using it will no longer be reused."
            messageClassName="text-xs"
            pendingLabel="Deleting"
            onCancel={onCancelDelete}
            onConfirm={onConfirmDelete}
          />
        )}
      </article>
    </li>
  );
}
