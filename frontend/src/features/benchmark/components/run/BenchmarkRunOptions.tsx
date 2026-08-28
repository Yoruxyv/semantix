import type { JSX } from 'react';

import { Button } from '@/shared/components/ui';
import { formatDecimal } from '@/shared/lib/formatters';

import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';
import {
  BENCHMARK_CONTROL_CLASS,
  benchmarkNumberValue,
  updateBenchmarkForm,
} from './benchmarkControlShared';

interface BenchmarkRunOptionsProps {
  controller: BenchmarkController;
}

export function BenchmarkRunOptions({
  controller,
}: Readonly<BenchmarkRunOptionsProps>): JSX.Element {
  const {
    canRun,
    datasets,
    datasetsLoading,
    form,
    historyNamespaceValid,
    isRunning,
    sweep,
  } = controller;

  return (
    <>
      <label className="block">
        <span className="ui-label text-(--text-muted)">Similarity threshold</span>

        <span className="font-data mt-2 flex min-h-11 items-center gap-3">
          <input
            aria-label="Benchmark threshold"
            className="threshold-range"
            disabled={isRunning}
            max="0.99"
            min="0.5"
            step="0.01"
            type="range"
            value={form.threshold}
            onChange={(event) =>
              updateBenchmarkForm(controller, {
                threshold: benchmarkNumberValue(event.target.value, form.threshold),
              })
            }
          />

          <output className="w-12 text-right text-xs">
            {formatDecimal(form.threshold, 2)}
          </output>
        </span>
      </label>

      <label className="block">
        <span className="ui-label text-(--text-muted)">Repetitions</span>

        <input
          aria-label="Benchmark repetitions"
          className={BENCHMARK_CONTROL_CLASS}
          disabled={isRunning}
          max="5"
          min="1"
          type="number"
          value={form.repetitions}
          onChange={(event) =>
            updateBenchmarkForm(controller, {
              repetitions: benchmarkNumberValue(event.target.value, form.repetitions),
            })
          }
        />
      </label>

      <label className="block">
        <span className="ui-label text-(--text-muted)">
          Cost / provider request (USD)
        </span>

        <input
          aria-label="Estimated cost per provider request"
          className={BENCHMARK_CONTROL_CLASS}
          disabled={isRunning}
          min="0"
          step="0.001"
          type="number"
          value={form.costPerRequestUsd}
          onChange={(event) =>
            updateBenchmarkForm(controller, {
              costPerRequestUsd: benchmarkNumberValue(
                event.target.value,
                form.costPerRequestUsd,
              ),
            })
          }
        />
      </label>

      <label className="block">
        <span className="ui-label text-(--text-muted)">Cost / 1K tokens (USD)</span>

        <input
          aria-label="Estimated cost per 1K tokens"
          className={BENCHMARK_CONTROL_CLASS}
          disabled={isRunning}
          min="0"
          step="0.001"
          type="number"
          value={form.costPer1kTokensUsd}
          onChange={(event) =>
            updateBenchmarkForm(controller, {
              costPer1kTokensUsd: benchmarkNumberValue(
                event.target.value,
                form.costPer1kTokensUsd,
              ),
            })
          }
        />
      </label>

      <div className="flex flex-col justify-between gap-4">
        <label className="font-data flex min-h-11 items-center gap-3 text-xs text-(--text-soft)">
          <input
            checked={form.resetCacheBeforeRun}
            className="size-5 accent-(--gold)"
            disabled={isRunning}
            type="checkbox"
            onChange={(event) =>
              updateBenchmarkForm(controller, {
                resetCacheBeforeRun: event.target.checked,
              })
            }
          />

          <span>Reset isolated benchmark cache before each repetition</span>
        </label>

        <Button
          aria-describedby={!canRun ? 'benchmark-run-permission' : undefined}
          className="disabled:opacity-40"
          disabled={
            datasetsLoading ||
            isRunning ||
            datasets.length === 0 ||
            !canRun ||
            controller.selectedDataset === null ||
            sweep.error !== null ||
            !historyNamespaceValid
          }
          size="large"
          variant="primary"
          onClick={() => void controller.reviewRun()}
        >
          {isRunning ? 'Benchmark running...' : 'Review benchmark run'}
        </Button>
      </div>
    </>
  );
}
