import { Button } from '@/shared/components/ui';
import { formatCount, formatUsd } from '@/shared/lib/formatters';
import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';

import type { JSX } from 'react';

interface BenchmarkRunWarningProps {
  controller: BenchmarkController;
}

export function BenchmarkRunWarning({
  controller,
}: Readonly<BenchmarkRunWarningProps>): JSX.Element | null {
  if (!controller.showWarning) {
    return null;
  }

  const dataset = controller.selectedDataset;
  const queryCount = (dataset?.query_count ?? 0) * controller.form.repetitions;

  const estimatedProviderCalls =
    (dataset?.expected_misses ?? 0) * controller.form.repetitions;

  return (
    <div
      aria-labelledby="benchmark-warning-title"
      className="mt-5 border border-(--coral) bg-[color-mix(in_srgb,var(--coral)_8%,transparent)] p-5"
      role="alertdialog"
    >
      <p className="ui-label text-(--coral-text)" id="benchmark-warning-title">
        External provider warning
      </p>

      <p className="mt-3 max-w-3xl text-sm/6 text-(--text-soft)">
        This bounded run executes {formatCount(queryCount)} queries across{' '}
        {formatCount(controller.form.repetitions)} repetition
        {controller.form.repetitions === 1 ? '' : 's'} and sends at most{' '}
        {formatCount(queryCount)} embedding requests. It may make at most{' '}
        {formatCount(queryCount)} external generation calls; dataset labels estimate
        about {formatCount(estimatedProviderCalls)}. Actual calls can differ when cache
        decisions are false positives or false negatives. Imported prompts may leave
        this system through the configured embedding or generation provider. Provider
        charges may apply.
      </p>

      <p className="font-data mt-3 text-[10px]/5 text-(--text-faint)">
        {(dataset?.dataset_source === 'inline' ||
          dataset?.dataset_source === 'persisted') && (
          <>
            {dataset.dataset_source === 'persisted' ? 'Persisted' : 'Imported'} dataset{' '}
            {dataset.name}, schema v{dataset.schema_version}, digest{' '}
            {dataset.digest.slice(0, 16)}... · {formatCount(dataset.query_count)} cases
            ({formatCount(dataset.expected_hits)} expected hits /{' '}
            {formatCount(dataset.expected_misses)} expected misses) ·{' '}
          </>
        )}
        One measured run supplies {controller.sweep.thresholds.length} frozen-candidate
        threshold values. Alternate thresholds do not repeat provider work.
      </p>

      <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
        Cost assumptions: {formatUsd(controller.form.costPerRequestUsd, 4)} per
        generation request and {formatUsd(controller.form.costPer1kTokensUsd, 4)} per 1K
        estimated tokens. These inputs are estimates, not billing records.
      </p>

      <div className="mt-5 flex flex-wrap gap-3">
        <Button variant="danger" onClick={() => void controller.confirmRun()}>
          Run benchmark now
        </Button>

        <Button
          className="border-(--hairline) text-(--text-soft) hover:border-(--text-muted) hover:text-(--text) focus-visible:outline-(--gold)"
          size="large"
          variant="secondary"
          onClick={controller.cancelRun}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
