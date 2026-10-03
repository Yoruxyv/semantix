import type { JSX } from 'react';

import type { EvaluationRunComparisonController } from '@/features/benchmark/hooks/useEvaluationRunComparison';
import { Alert, Button } from '@/shared/components/ui';
import { apiErrorFromUnknown } from '@/shared/query/apiResult';

import { EvaluationRunComparisonResult } from './EvaluationRunComparisonResult';

function SelectionCard({
  label,
  run,
  onRemove,
}: Readonly<{
  label: 'Baseline' | 'Candidate';
  run: EvaluationRunComparisonController['selectedRuns'][number];
  onRemove: () => void;
}>): JSX.Element {
  return (
    <article className="min-w-0 border border-(--hairline) p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="ui-label text-(--gold)">{label}</p>
          <p className="mt-2 wrap-break-word text-sm text-(--text)">
            {run.dataset.name}
          </p>
          <code
            className="font-data mt-1 block text-[10px] text-(--text-faint)"
            title={run.run_id}
          >
            {run.run_id.slice(0, 12)}...
          </code>
        </div>
        <Button size="compact" variant="link" onClick={onRemove}>
          Remove
        </Button>
      </div>
      <p className="font-data mt-3 wrap-break-word text-[10px]/5 text-(--text-muted)">
        {run.namespace} · {run.terminal_state}
      </p>
    </article>
  );
}

export function EvaluationRunComparisonWorkspace({
  controller,
}: Readonly<{
  controller: EvaluationRunComparisonController;
}>): JSX.Element | null {
  if (controller.selectedRuns.length === 0) {
    return null;
  }

  const error =
    controller.error === null
      ? null
      : (apiErrorFromUnknown(controller.error).detail ??
        'The selected retained runs could not be compared.');

  return (
    <section
      aria-labelledby="comparison-workspace-heading"
      className="mt-6 border border-(--hairline) p-4 sm:p-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="ui-label text-(--gold)">Exactly two retained runs</p>
          <h3
            className="font-display mt-2 text-xl italic text-(--text)"
            id="comparison-workspace-heading"
          >
            Compare runs
          </h3>
          <p className="mt-2 max-w-3xl text-sm/6 text-(--text-muted)">
            The first selected run is the baseline. The second is the candidate.
            Compatibility is decided by the server before any delta is shown.
          </p>
        </div>
        <Button size="compact" variant="link" onClick={controller.clear}>
          Clear selection
        </Button>
      </header>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {controller.selectedRuns[0] !== undefined && (
          <SelectionCard
            label="Baseline"
            run={controller.selectedRuns[0]}
            onRemove={() =>
              controller.removeRun(controller.selectedRuns[0]?.run_id ?? '')
            }
          />
        )}
        {controller.selectedRuns[1] !== undefined ? (
          <SelectionCard
            label="Candidate"
            run={controller.selectedRuns[1]}
            onRemove={() =>
              controller.removeRun(controller.selectedRuns[1]?.run_id ?? '')
            }
          />
        ) : (
          <div className="border border-dashed border-(--hairline) p-4">
            <p className="ui-label text-(--text-faint)">Candidate</p>
            <p className="font-data mt-2 text-[10px]/5 text-(--text-muted)">
              Select one more retained run from the history list.
            </p>
          </div>
        )}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button disabled={!controller.canCompare} onClick={controller.compare}>
          {controller.isPending ? 'Comparing...' : 'Compare selected runs'}
        </Button>
        <p className="font-data text-[10px]/5 text-(--text-faint)">
          {controller.selectedRuns.length}/2 selected
        </p>
      </div>

      {controller.isPending && (
        <output
          aria-live="polite"
          className="font-data mt-4 block text-[10px]/5 text-(--text-muted)"
        >
          Checking compatibility and calculating aggregate deltas...
        </output>
      )}

      {error !== null && (
        <Alert
          className="mt-5"
          role="alert"
          title="Comparison unavailable"
          tone="error"
        >
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">{error}</p>
        </Alert>
      )}

      {controller.result !== undefined && (
        <EvaluationRunComparisonResult comparison={controller.result} />
      )}
    </section>
  );
}
