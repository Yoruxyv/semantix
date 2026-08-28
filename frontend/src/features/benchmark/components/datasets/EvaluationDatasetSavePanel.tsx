import type { JSX } from 'react';

import type { AuthStatus } from '@/features/auth/context/AuthContext';
import { Button } from '@/shared/components/ui';
import { formatCount } from '@/shared/lib/formatters';

import { EVALUATION_DATASET_CONTROL_CLASS } from './datasetCatalogShared';

interface SaveNamespaceControlProps {
  authStatus: AuthStatus;
  hasGlobalNamespace: boolean;
  namespaces: string[];
  saveNamespace: string;
  setSaveNamespace: (value: string) => void;
}

interface EvaluationDatasetSavePanelProps extends SaveNamespaceControlProps {
  isSaving: boolean;
  maxRetentionDays: number;
  retentionDays: number;
  saveNamespaceValid: boolean;
  setRetentionDays: (value: number) => void;
  onSave: () => void;
}

function SaveNamespaceControl({
  authStatus,
  hasGlobalNamespace,
  namespaces,
  saveNamespace,
  setSaveNamespace,
}: Readonly<SaveNamespaceControlProps>): JSX.Element {
  if (authStatus === 'disabled' || hasGlobalNamespace) {
    const guidance =
      authStatus === 'disabled'
        ? 'Local development uses an explicit namespace; default is preselected.'
        : 'Wildcard access requires an explicit namespace.';
    return (
      <label>
        <span className="ui-label text-(--text-muted)">Namespace</span>
        <input
          aria-describedby="save-namespace-guidance"
          className={EVALUATION_DATASET_CONTROL_CLASS}
          placeholder="Authorized namespace"
          value={saveNamespace}
          onChange={(event) => setSaveNamespace(event.target.value)}
        />
        <span
          className="font-data mt-2 block text-[10px]/5 text-(--text-faint)"
          id="save-namespace-guidance"
        >
          {guidance}
        </span>
      </label>
    );
  }

  if (namespaces.length > 1) {
    return (
      <label>
        <span className="ui-label text-(--text-muted)">Namespace</span>
        <select
          className={EVALUATION_DATASET_CONTROL_CLASS}
          value={saveNamespace}
          onChange={(event) => setSaveNamespace(event.target.value)}
        >
          <option value="">Choose a namespace</option>
          {namespaces.map((namespace) => (
            <option key={namespace} value={namespace}>
              {namespace}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <div>
      <p className="ui-label text-(--text-muted)">Namespace</p>
      <p className="font-data mt-2 wrap-break-word text-xs text-(--text-soft)">
        {namespaces[0] ?? 'No authorized namespace'}
      </p>
    </div>
  );
}

export function EvaluationDatasetSavePanel({
  authStatus,
  hasGlobalNamespace,
  isSaving,
  maxRetentionDays,
  namespaces,
  retentionDays,
  saveNamespace,
  saveNamespaceValid,
  setRetentionDays,
  setSaveNamespace,
  onSave,
}: Readonly<EvaluationDatasetSavePanelProps>): JSX.Element {
  return (
    <section
      aria-labelledby="save-dataset-heading"
      className="mt-6 border border-(--hairline) p-4 sm:p-5"
    >
      <h3 className="ui-label text-(--teal)" id="save-dataset-heading">
        Save validated session dataset
      </h3>
      <p className="font-data mt-2 text-[10px]/5 text-(--text-muted)">
        Saving is explicit. Validation by itself never writes dataset content to
        PostgreSQL.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <SaveNamespaceControl
          authStatus={authStatus}
          hasGlobalNamespace={hasGlobalNamespace}
          namespaces={namespaces}
          saveNamespace={saveNamespace}
          setSaveNamespace={setSaveNamespace}
        />
        <label>
          <span className="ui-label text-(--text-muted)">Retention days</span>
          <input
            className={EVALUATION_DATASET_CONTROL_CLASS}
            max={maxRetentionDays}
            min="1"
            type="number"
            value={retentionDays}
            onChange={(event) => setRetentionDays(Number(event.target.value))}
          />
          <span className="font-data mt-2 block text-[10px]/5 text-(--text-faint)">
            Maximum {formatCount(maxRetentionDays)} days.
          </span>
        </label>
      </div>
      <Button
        className="mt-4"
        disabled={
          isSaving ||
          !saveNamespaceValid ||
          !Number.isSafeInteger(retentionDays) ||
          retentionDays < 1 ||
          retentionDays > maxRetentionDays
        }
        variant="primary"
        onClick={onSave}
      >
        {isSaving ? 'Saving validated dataset...' : 'Save validated dataset'}
      </Button>
    </section>
  );
}
