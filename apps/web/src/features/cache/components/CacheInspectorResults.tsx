import { CacheEntryCard } from './CacheEntryCard';
import type { CacheInspectorController } from '../hooks/useCacheInspector';
import { Alert, Button, EmptyState } from '@/shared/components/ui';

import type { JSX } from 'react';

interface CacheInspectorResultsProps {
  inspector: CacheInspectorController;
}

export function CacheInspectorResults({
  inspector,
}: Readonly<CacheInspectorResultsProps>): JSX.Element {
  const {
    actionError,
    cancelDelete,
    confirmDeleteEntry,
    data,
    hasNext,
    hasPrevious,
    isLoading,
    isRefreshing,
    loadError,
    mutation,
    nextPage,
    pendingDelete,
    previousPage,
    refresh,
    refreshError,
    requestDelete,
    search,
    visibleEnd,
    visibleStart,
  } = inspector;

  return (
    <>
      {data === null && isLoading && (
        <output
          aria-label="Loading cache entries"
          aria-live="polite"
          className="mt-7 block animate-pulse border-y border-(--hairline)"
        >
          <span className="sr-only">Loading cached response metadata.</span>
          {[0, 1].map((item) => (
            <span
              className="block border-b border-[rgba(234,230,221,0.05)] px-1 py-5 last:border-b-0"
              key={item}
            >
              <span className="flex items-center justify-between gap-6">
                <span className="h-3 w-44 bg-[rgba(91,156,148,0.12)]" />
                <span className="h-3 w-14 bg-[rgba(194,96,74,0.1)]" />
              </span>
              <span className="mt-4 block h-4 w-3/5 bg-[rgba(234,230,221,0.08)]" />
              <span className="mt-3 block h-3 w-full bg-[rgba(234,230,221,0.05)]" />
              <span className="mt-2 block h-3 w-4/5 bg-[rgba(234,230,221,0.05)]" />
              <span className="mt-5 grid grid-cols-2 gap-4 min-[720px]:grid-cols-3">
                {[0, 1, 2, 3, 4, 5].map((metric) => (
                  <span
                    className="h-8 bg-[rgba(234,230,221,0.04)]"
                    data-skeleton-entry-metric
                    key={metric}
                  />
                ))}
              </span>
            </span>
          ))}
        </output>
      )}

      {actionError !== null && (
        <Alert
          className="font-data mt-5 border-l-2 border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-3 text-[11px]/5 text-(--coral-text)"
          role="alert"
          tone="error"
        >
          {actionError}
        </Alert>
      )}

      {refreshError !== null && (
        <Alert
          className="font-data mt-5 border-l border-(--coral) pl-4 text-[11px]/5 text-(--coral-text)"
          aria-live="polite"
          tone="error"
        >
          {refreshError} Cached entries remain visible.
        </Alert>
      )}

      {loadError !== null && (
        <Alert
          className="mt-6 border-l-2 border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-3"
          role="alert"
          tone="error"
        >
          <p className="text-sm text-(--text-soft)">{loadError}</p>
          <Button
            className="ui-label mt-3 min-h-9 text-(--teal) focus-visible:outline-(--teal)"
            variant="link"
            onClick={refresh}
          >
            Try again
          </Button>
        </Alert>
      )}

      {data !== null && loadError === null && data.items.length === 0 && (
        <EmptyState
          className="mt-7 py-8"
          description={
            search.trim() === ''
              ? 'Run a query to create the first inspectable entry.'
              : 'Try a broader prompt fragment or clear the search field.'
          }
          title={
            search.trim() === ''
              ? 'The cache is empty.'
              : 'No cached prompts match this search.'
          }
        />
      )}

      {data !== null && loadError === null && data.items.length > 0 && (
        <ol className="mt-6">
          {data.items.map((entry) => (
            <CacheEntryCard
              key={entry.cache_key}
              entry={entry}
              isDeleting={mutation === entry.cache_key}
              isPendingDelete={pendingDelete === entry.cache_key}
              onCancelDelete={cancelDelete}
              onConfirmDelete={() => void confirmDeleteEntry(entry.cache_key)}
              onRequestDelete={() => requestDelete(entry.cache_key)}
            />
          ))}
        </ol>
      )}

      {data !== null && loadError === null && (
        <footer className="font-data mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-(--hairline) pt-4 text-[10px] text-(--text-faint)">
          <span>
            {visibleStart}-{visibleEnd} of {data.total} entries
          </span>
          <div className="flex gap-5">
            <Button
              className="ui-label min-h-9 text-(--teal) focus-visible:outline-(--teal) disabled:text-(--text-faint)"
              disabled={!hasPrevious || isLoading || isRefreshing}
              variant="link"
              onClick={previousPage}
            >
              Previous
            </Button>
            <Button
              className="ui-label min-h-9 text-(--teal) focus-visible:outline-(--teal) disabled:text-(--text-faint)"
              disabled={!hasNext || isLoading || isRefreshing}
              variant="link"
              onClick={nextPage}
            >
              Next
            </Button>
          </div>
        </footer>
      )}
    </>
  );
}
