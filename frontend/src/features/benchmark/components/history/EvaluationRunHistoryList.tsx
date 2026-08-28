import type { JSX } from 'react';

import { Button, EmptyState, InlineConfirmation } from '@/shared/components/ui';
import {
  formatCount,
  formatLatency,
  formatPercent,
  formatTimestamp,
} from '@/shared/lib/formatters';

import type {
  EvaluationRunHistoryItem,
  EvaluationRunHistoryListResponse,
} from '@/features/benchmark/types';

const PAGE_SIZE = 12;

interface EvaluationRunHistoryListProps {
  canDelete: boolean;
  catalog: EvaluationRunHistoryListResponse;
  comparisonRunIds: readonly string[];
  deletingRunId: string | null;
  offset: number;
  pendingDelete: string | null;
  onDelete: (item: EvaluationRunHistoryItem) => void;
  onDeleteCancel: () => void;
  onDeleteRequest: (runId: string) => void;
  onOffsetChange: (offset: number) => void;
  onSelect: (runId: string) => void;
  onToggleComparison: (item: EvaluationRunHistoryItem) => void;
}

function stateClass(state: EvaluationRunHistoryItem['terminal_state']): string {
  if (state === 'completed') {
    return 'text-(--teal)';
  }
  if (state === 'timed_out') {
    return 'text-(--gold)';
  }
  return 'text-(--coral)';
}

function RunSummary({
  item,
}: Readonly<{ item: EvaluationRunHistoryItem }>): JSX.Element {
  if (item.metrics === null) {
    return (
      <p className="font-data mt-3 text-[10px]/5 text-(--text-muted)">
        {item.failure_code}
        {item.safe_failure_detail === null ? '' : ` · ${item.safe_failure_detail}`}
      </p>
    );
  }

  return (
    <dl className="font-data mt-3 grid grid-cols-3 gap-3 text-[10px]/5">
      <div>
        <dt className="text-(--text-faint)">Hit rate</dt>
        <dd className="mt-1 text-(--text-soft)">
          {formatPercent(item.metrics.hit_rate)}
        </dd>
      </div>
      <div>
        <dt className="text-(--text-faint)">F1</dt>
        <dd className="mt-1 text-(--text-soft)">
          {formatPercent(item.metrics.f1_score)}
        </dd>
      </div>
      <div>
        <dt className="text-(--text-faint)">Avg latency</dt>
        <dd className="mt-1 text-(--text-soft)">
          {formatLatency(item.metrics.average_latency_ms)}
        </dd>
      </div>
    </dl>
  );
}

function comparisonLabel(index: number): string {
  if (index === 0) {
    return 'Baseline selected';
  }
  if (index === 1) {
    return 'Candidate selected';
  }
  return 'Select to compare';
}

export function EvaluationRunHistoryList({
  canDelete,
  catalog,
  comparisonRunIds,
  deletingRunId,
  offset,
  pendingDelete,
  onDelete,
  onDeleteCancel,
  onDeleteRequest,
  onOffsetChange,
  onSelect,
  onToggleComparison,
}: Readonly<EvaluationRunHistoryListProps>): JSX.Element {
  if (catalog.items.length === 0) {
    return (
      <EmptyState
        className="mt-6 py-6"
        description="No unexpired terminal evaluation runs are retained in this namespace scope."
        title="No retained runs"
      />
    );
  }

  return (
    <>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {catalog.items.map((item) => {
          const comparisonIndex = comparisonRunIds.indexOf(item.run_id);
          const selectedForComparison = comparisonIndex >= 0;
          const comparisonFull = comparisonRunIds.length >= 2 && !selectedForComparison;

          return (
            <article
              className="min-w-0 border border-(--hairline) p-4"
              key={item.run_id}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className={`ui-label ${stateClass(item.terminal_state)}`}>
                    {item.terminal_state.replace('_', ' ')}
                  </p>
                  <h3 className="mt-2 wrap-break-word text-base text-(--text)">
                    {item.dataset.name}
                  </h3>
                  <code
                    className="font-data mt-1 block text-[10px] text-(--text-faint)"
                    title={item.run_id}
                  >
                    {item.run_id.slice(0, 12)}...
                  </code>
                </div>
                <span className="font-data wrap-break-word text-[10px] text-(--text-faint)">
                  {item.namespace}
                </span>
              </div>

              <RunSummary item={item} />

              <dl className="font-data mt-4 grid grid-cols-2 gap-3 border-t border-(--hairline) pt-3 text-[10px]/5">
                <div>
                  <dt className="text-(--text-faint)">Completed</dt>
                  <dd className="mt-1 text-(--text-soft)" title={item.completed_at}>
                    {formatTimestamp(item.completed_at)}
                  </dd>
                </div>
                <div>
                  <dt className="text-(--text-faint)">Expires</dt>
                  <dd className="mt-1 text-(--gold)" title={item.expires_at}>
                    {formatTimestamp(item.expires_at)}
                  </dd>
                </div>
              </dl>

              <div className="mt-4 flex flex-wrap gap-3">
                <Button
                  size="compact"
                  variant="secondary"
                  onClick={() => onSelect(item.run_id)}
                >
                  View details
                </Button>
                <Button
                  aria-pressed={selectedForComparison}
                  disabled={comparisonFull}
                  size="compact"
                  variant={selectedForComparison ? 'secondary' : 'link'}
                  onClick={() => onToggleComparison(item)}
                >
                  {comparisonLabel(comparisonIndex)}
                </Button>
                {canDelete && pendingDelete !== item.run_id && (
                  <Button
                    size="compact"
                    variant="link"
                    onClick={() => onDeleteRequest(item.run_id)}
                  >
                    Delete
                  </Button>
                )}
              </div>

              {comparisonFull && (
                <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
                  Two runs are already selected. Remove one to choose this run.
                </p>
              )}

              {pendingDelete === item.run_id && (
                <InlineConfirmation
                  ariaLabel={`Delete retained run ${item.run_id}`}
                  className="mt-4"
                  confirmLabel="Delete retained run"
                  isPending={deletingRunId === item.run_id}
                  message={
                    <>
                      Delete this retained aggregate from{' '}
                      <strong>{item.namespace}</strong>? This does not delete the source
                      dataset.
                    </>
                  }
                  onCancel={onDeleteCancel}
                  onConfirm={() => onDelete(item)}
                  pendingLabel="Deleting..."
                />
              )}
            </article>
          );
        })}
      </div>

      <nav
        aria-label="Evaluation run history pagination"
        className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-(--hairline) pt-4"
      >
        <p className="font-data text-[10px]/5 text-(--text-faint)">
          Showing {formatCount(offset + 1)}-{formatCount(offset + catalog.items.length)}{' '}
          of {formatCount(catalog.total)}
        </p>
        <div className="flex gap-3">
          <Button
            disabled={offset === 0}
            size="compact"
            variant="secondary"
            onClick={() => onOffsetChange(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Button>
          <Button
            disabled={!catalog.has_more}
            size="compact"
            variant="secondary"
            onClick={() => onOffsetChange(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      </nav>
    </>
  );
}
