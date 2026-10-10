import { CacheInspector, type CacheMutation } from '../components/CacheInspector';
import { useLocation } from 'react-router';
import { useCacheControl } from '../hooks/useCacheControl';
import { useMonitor } from '@/features/monitor/hooks/useMonitor';
import { Alert, PageHeader } from '@/shared/components/ui';

import type { JSX } from 'react';

/** Route-state text is a presentation hint, not durable mutation/audit evidence. */
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

  /**
   * Inspector reports the mutation; clear removes only local Monitor traces.
   * Both actions request cache-state refresh. The JSX wrapper discards this promise,
   * so the inspector cannot await this refresh or catch its rejection.
   */
  async function handleMutation(mutation: CacheMutation): Promise<void> {
    if (mutation === 'clear') {
      clearTraces();
    }
    await refreshCacheState(false);
  }

  return (
    <>
      <PageHeader
        className="mb-6"
        description="Inspect this server's persisted cache entries, reuse activity, and expiry. Search within an authorized namespace or remove stale responses; stored embeddings remain excluded."
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
