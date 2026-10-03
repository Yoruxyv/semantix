import type { JSX } from 'react';

import type { AuthStatus } from '@/features/auth/context/AuthContext';
import { Button } from '@/shared/components/ui';

const HISTORY_CONTROL_CLASS =
  'font-data min-h-11 w-full border border-(--hairline) bg-(--surface) px-3 py-2 text-xs text-(--text) outline-none focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold)';

interface EvaluationRunHistoryFilterProps {
  authStatus: AuthStatus;
  hasGlobalNamespace: boolean;
  namespace: string;
  namespaceError: string | null;
  namespaceInput: string;
  namespaces: string[];
  onApplyNamespace: () => void;
  onNamespaceInputChange: (value: string) => void;
  onScopedNamespaceChange: (value: string) => void;
}

export function EvaluationRunHistoryFilter({
  authStatus,
  hasGlobalNamespace,
  namespace,
  namespaceError,
  namespaceInput,
  namespaces,
  onApplyNamespace,
  onNamespaceInputChange,
  onScopedNamespaceChange,
}: Readonly<EvaluationRunHistoryFilterProps>): JSX.Element {
  let namespaceControl: JSX.Element;

  if (authStatus === 'authenticated' && !hasGlobalNamespace && namespaces.length > 1) {
    namespaceControl = (
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1">
          <span className="sr-only">History namespace</span>
          <select
            aria-label="History namespace"
            className={HISTORY_CONTROL_CLASS}
            value={namespaceInput}
            onChange={(event) => onScopedNamespaceChange(event.target.value)}
          >
            {namespaces.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      </div>
    );
  } else if (authStatus === 'authenticated' && !hasGlobalNamespace) {
    namespaceControl = (
      <p className="font-data mt-3 text-xs text-(--text-soft)">
        {namespace || 'No authorized namespace'}
      </p>
    );
  } else {
    namespaceControl = (
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1">
          <span className="sr-only">History namespace filter</span>
          <input
            aria-describedby="history-namespace-guidance"
            aria-label="History namespace filter"
            className={HISTORY_CONTROL_CLASS}
            placeholder="All namespaces"
            value={namespaceInput}
            onChange={(event) => onNamespaceInputChange(event.target.value)}
          />
        </label>
        <Button size="compact" variant="secondary" onClick={onApplyNamespace}>
          Apply namespace
        </Button>
      </div>
    );
  }

  return (
    <section
      aria-labelledby="run-history-filter-heading"
      className="mt-5 border border-(--hairline) p-4"
    >
      <h3 className="ui-label text-(--text-muted)" id="run-history-filter-heading">
        Namespace scope
      </h3>

      {namespaceControl}

      <p
        className="font-data mt-2 text-[10px]/5 text-(--text-faint)"
        id="history-namespace-guidance"
      >
        Wildcard access may leave this blank to list all authorized history. Deletion
        always remains scoped to the run&apos;s retained namespace.
      </p>
      {namespaceError !== null && (
        <p className="font-data mt-2 text-[10px]/5 text-(--coral)" role="alert">
          {namespaceError}
        </p>
      )}
    </section>
  );
}
