import { CacheReadingsSkeleton } from '../components/CacheReadingsSkeleton';
import { FieldMetrics } from '../components/FieldMetrics';
import { QueryForm } from '../components/QueryForm';
import { QueryLog } from '../components/QueryLog';
import { ResponseSkeleton } from '../components/ResponseSkeleton';
import { SimilarityRadar } from '../components/similarity-radar/SimilarityRadar';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { canApplyGlobalThreshold } from '@/features/auth/permissions';
import { useCacheControl } from '@/features/cache/hooks/useCacheControl';
import { useMonitor } from '../hooks/useMonitor';
import { Alert } from '@/shared/components/ui';

import { lazy, Suspense, type JSX } from 'react';

const ResponseCard = lazy(() =>
  import('../components/ResponseCard').then((module) => ({
    default: module.ResponseCard,
  })),
);

export function MonitorPage(): JSX.Element {
  const { session, status } = useAuth();
  const {
    cacheState,
    commitThreshold,
    isApplyingThreshold,
    isRefreshingCacheState,
    previewThreshold,
    setPreviewThreshold,
  } = useCacheControl();
  const { latestEvidence, queryState, submitPrompt, traces } = useMonitor();
  const canApplyThreshold = canApplyGlobalThreshold(status, session);

  return (
    <>
      {cacheState.status === 'error' && (
        <Alert
          className="mb-8 border-y border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-5"
          role="alert"
          title="Cache controls unavailable"
          tone="error"
        >
          <p className="font-data mt-1 text-[11px]/5 text-(--text-soft)">
            {cacheState.error}
          </p>
        </Alert>
      )}

      <section className="mb-12 border-b border-(--hairline) pb-10">
        <QueryForm
          isLoading={queryState.status === 'loading'}
          onSubmit={submitPrompt}
        />

        {queryState.status === 'loading' && (
          <div className="mt-8">
            <ResponseSkeleton />
          </div>
        )}

        {queryState.status === 'error' && (
          <Alert
            className="mt-6 border-l-2 border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-3"
            role="alert"
            title="Query failed"
            tone="error"
          >
            <p className="font-data mt-1 text-[11px]/5 text-(--text-soft)">
              {queryState.error.detail ?? 'The provider returned no detail.'}
            </p>
          </Alert>
        )}

        {queryState.status === 'success' && (
          <div className="mt-8">
            <Suspense fallback={<ResponseSkeleton />}>
              <ResponseCard evidence={latestEvidence} result={queryState.data} />
            </Suspense>
          </div>
        )}
      </section>

      {cacheState.status === 'loading' && <CacheReadingsSkeleton />}

      {cacheState.status === 'ready' && previewThreshold !== null && (
        <>
          {isRefreshingCacheState && (
            <output aria-live="polite" className="ui-label mb-5 block text-(--gold)">
              Refreshing cache readings
            </output>
          )}

          <div className="grid grid-cols-1 gap-14 min-[760px]:grid-cols-[minmax(280px,3fr)_minmax(0,2fr)]">
            <FieldMetrics
              cacheStats={cacheState.data.cacheStats}
              threshold={previewThreshold}
              traces={traces}
            />

            <SimilarityRadar
              appliedThreshold={cacheState.data.appliedThreshold}
              canApplyThreshold={canApplyThreshold}
              isApplyingThreshold={isApplyingThreshold}
              traces={traces}
              threshold={previewThreshold}
              onThresholdApply={(value) => void commitThreshold(value)}
              onThresholdChange={setPreviewThreshold}
            />
          </div>

          <QueryLog traces={traces} threshold={previewThreshold} />
        </>
      )}
    </>
  );
}
