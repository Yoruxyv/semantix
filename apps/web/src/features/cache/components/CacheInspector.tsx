import { CacheInspectorControls } from './CacheInspectorControls';
import { CacheInspectorResults } from './CacheInspectorResults';
import { useCacheInspector, type CacheMutation } from '../hooks/useCacheInspector';

import type { JSX } from 'react';

export type { CacheMutation };

interface CacheInspectorProps {
  onMutation: (mutation: CacheMutation) => void | Promise<void>;
}

export function CacheInspector({
  onMutation,
}: Readonly<CacheInspectorProps>): JSX.Element {
  const inspector = useCacheInspector({ onMutation });

  return (
    <section
      aria-labelledby="cache-inspector-heading"
      className="border-t border-(--hairline) pt-8"
    >
      <CacheInspectorControls
        canClear={inspector.data !== null}
        confirmClear={inspector.confirmClear}
        isClearing={inspector.isClearing}
        isLoading={inspector.isLoading}
        isMutating={inspector.isMutating}
        isRefreshing={inspector.isRefreshing}
        namespace={inspector.namespace}
        search={inspector.search}
        sort={inspector.sort}
        onCancelClear={inspector.cancelClear}
        onConfirmClear={() => void inspector.confirmClearCache()}
        onRefresh={inspector.refresh}
        onRequestClear={inspector.requestClear}
        onNamespaceChange={inspector.setNamespace}
        onSearchChange={inspector.setSearch}
        onSortChange={inspector.setSort}
      />
      <CacheInspectorResults inspector={inspector} />
    </section>
  );
}
