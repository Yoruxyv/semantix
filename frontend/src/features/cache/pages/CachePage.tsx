import { CacheInspector, type CacheMutation } from '../components/CacheInspector';
import { useLocation } from 'react-router';
import { useCacheControl } from '../hooks/useCacheControl';
import { useMonitor } from '@/features/monitor/hooks/useMonitor';
import { Alert, PageHeader } from '@/shared/components/ui';

import type { JSX } from 'react';

function cacheMutationNotice(state: unknown): string | null {
  if (
    typeof state === 'object' &&
    state !== null &&
    'cacheMutationNotice' in state &&
    typeof state.cacheMutationNotice === 'string'
  ) {
    return state.cacheMutationNotice;
  }
  return null;
}

export function CachePage(): JSX.Element {
  const location = useLocation();
  const mutationNotice = cacheMutationNotice(location.state);
  const { refreshCacheState } = useCacheControl();
  const { clearTraces } = useMonitor();

  async function handleMutation(mutation: CacheMutation): Promise<void> {
    if (mutation === 'clear') {
      clearTraces();
    }
    await refreshCacheState(false);
  }

  return (
    <>
      <PageHeader
        className="mb-9"
        description="Search safe entry metadata, inspect reuse activity and expiry, or remove stale responses without exposing stored embeddings."
        eyebrow="Storage controls"
        title="Cache inspector"
      />

      {mutationNotice !== null && (
        <Alert
          aria-live="polite"
          className="font-data mb-6 border-l border-(--teal) pl-4 text-[11px]/5"
        >
          {mutationNotice}
        </Alert>
      )}

      <CacheInspector onMutation={(mutation) => void handleMutation(mutation)} />
    </>
  );
}
