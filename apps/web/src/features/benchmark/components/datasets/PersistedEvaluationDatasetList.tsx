import type { JSX } from 'react';

import { Button, EmptyState, InlineConfirmation } from '@/shared/components/ui';
import { formatCount } from '@/shared/lib/formatters';

import type {
  PersistedEvaluationDatasetListResponse,
  PersistedEvaluationDatasetMetadata,
} from '@/features/benchmark/types';
import { EvaluationDatasetMetadata } from './EvaluationDatasetMetadata';
import {
  EVALUATION_DATASET_CONTROL_CLASS,
  EVALUATION_DATASET_PAGE_SIZE,
} from './datasetCatalogShared';

interface PersistedEvaluationDatasetListProps {
  canDelete: boolean;
  catalog: PersistedEvaluationDatasetListResponse;
  deletingId: string | null;
  hasGlobalNamespace: boolean;
  listNamespace: string;
  namespaces: string[];
  offset: number;
  pendingDelete: string | null;
  onDelete: (dataset: PersistedEvaluationDatasetMetadata) => void;
  onDeleteCancel: () => void;
  onDeleteRequest: (datasetId: string) => void;
  onNamespaceChange: (namespace: string) => void;
  onOffsetChange: (offset: number) => void;
  onSelect: (datasetId: string) => void;
}

export function PersistedEvaluationDatasetList({
  canDelete,
  catalog,
  deletingId,
  hasGlobalNamespace,
  listNamespace,
  namespaces,
  offset,
  pendingDelete,
  onDelete,
  onDeleteCancel,
  onDeleteRequest,
  onNamespaceChange,
  onOffsetChange,
  onSelect,
}: Readonly<PersistedEvaluationDatasetListProps>): JSX.Element {
  return (
    <section aria-labelledby="persisted-datasets-heading" className="mt-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h3 className="ui-label text-(--text-muted)" id="persisted-datasets-heading">
            Persisted catalog
          </h3>
          <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
            {formatCount(catalog.total)} active dataset
            {catalog.total === 1 ? '' : 's'} · maximum{' '}
            {formatCount(catalog.limits.max_persisted_per_namespace)} per namespace
          </p>
        </div>
        {namespaces.length > 1 && !hasGlobalNamespace && (
          <label className="w-full sm:w-64">
            <span className="ui-label text-(--text-muted)">Catalog namespace</span>
            <select
              className={EVALUATION_DATASET_CONTROL_CLASS}
              value={listNamespace}
              onChange={(event) => onNamespaceChange(event.target.value)}
            >
              {namespaces.map((namespace) => (
                <option key={namespace} value={namespace}>
                  {namespace}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {catalog.items.length === 0 ? (
        <EmptyState
          className="mt-5"
          description="Save a validated session dataset to make it available for later evaluation runs."
          title="No persisted datasets"
        />
      ) : (
        <ul className="mt-4 grid gap-4 lg:grid-cols-2">
          {catalog.items.map((dataset) => (
            <li
              key={dataset.dataset_id}
              className="min-w-0 border border-(--hairline) p-4 sm:p-5"
            >
              <article>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="ui-label text-(--teal)">Persisted</p>
                    <h4 className="mt-2 wrap-break-word text-lg text-(--text)">
                      {dataset.name}
                    </h4>
                  </div>
                  <Button
                    size="compact"
                    variant="secondary"
                    onClick={() => onSelect(dataset.dataset_id)}
                  >
                    View details
                  </Button>
                </div>
                {dataset.description !== null && (
                  <p className="mt-3 whitespace-pre-wrap wrap-break-word text-sm/6 text-(--text-muted)">
                    {dataset.description}
                  </p>
                )}
                <EvaluationDatasetMetadata dataset={dataset} />
                {canDelete && pendingDelete !== dataset.dataset_id && (
                  <Button
                    className="mt-4 text-(--coral-text)"
                    size="compact"
                    variant="link"
                    onClick={() => onDeleteRequest(dataset.dataset_id)}
                  >
                    Delete dataset
                  </Button>
                )}
                {canDelete && pendingDelete === dataset.dataset_id && (
                  <InlineConfirmation
                    ariaLabel={`Confirm deletion of ${dataset.name} from namespace ${dataset.namespace}`}
                    className="mt-4"
                    confirmAriaLabel={`Confirm delete ${dataset.name} from namespace ${dataset.namespace}`}
                    confirmLabel="Confirm delete"
                    isPending={deletingId === dataset.dataset_id}
                    message={
                      <>
                        Delete <strong>{dataset.name}</strong> from namespace{' '}
                        <strong>{dataset.namespace}</strong>? Its{' '}
                        {formatCount(dataset.case_count)} cases will no longer be
                        available for evaluation runs.
                      </>
                    }
                    pendingLabel="Deleting dataset"
                    onCancel={onDeleteCancel}
                    onConfirm={() => onDelete(dataset)}
                  />
                )}
              </article>
            </li>
          ))}
        </ul>
      )}

      {(offset > 0 || catalog.has_more) && (
        <nav
          aria-label="Persisted dataset pages"
          className="mt-5 flex flex-wrap items-center gap-4"
        >
          <Button
            disabled={offset === 0}
            size="compact"
            variant="secondary"
            onClick={() =>
              onOffsetChange(Math.max(0, offset - EVALUATION_DATASET_PAGE_SIZE))
            }
          >
            Previous
          </Button>
          <span className="font-data text-[10px] text-(--text-muted)">
            Showing {formatCount(offset + 1)}–
            {formatCount(offset + catalog.items.length)} of {formatCount(catalog.total)}
          </span>
          <Button
            disabled={!catalog.has_more}
            size="compact"
            variant="secondary"
            onClick={() => onOffsetChange(offset + EVALUATION_DATASET_PAGE_SIZE)}
          >
            Next
          </Button>
        </nav>
      )}
    </section>
  );
}
