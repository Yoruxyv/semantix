import { useState, type JSX } from 'react';

import { formatDecimal } from '@/shared/lib/formatters';

import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';
import {
  BENCHMARK_CONTROL_CLASS,
  benchmarkNumberValue,
  updateBenchmarkForm,
} from './benchmarkControlShared';

interface BenchmarkSweepControlsProps {
  controller: BenchmarkController;
}

export function BenchmarkSweepControls({
  controller,
}: Readonly<BenchmarkSweepControlsProps>): JSX.Element {
  const [isSweepOpen, setIsSweepOpen] = useState(false);
  const { canRun, form, isRunning, sweep } = controller;

  return (
    <div className="border-t border-(--hairline) pt-5 sm:col-span-2 lg:col-span-3">
      <button
        aria-controls="benchmark-sweep-controls"
        aria-expanded={isSweepOpen}
        className="ui-label flex min-h-11 w-full items-center justify-between gap-4 text-left text-(--gold) outline-none focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
        type="button"
        onClick={() => setIsSweepOpen((current) => !current)}
      >
        <span>Advanced frozen-candidate sweep</span>
        <span aria-hidden="true">{isSweepOpen ? '-' : '+'}</span>
      </button>

      <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
        {sweep.thresholds.length} projected thresholds, including the measured value{' '}
        {formatDecimal(form.threshold, 2)}. Alternate values reuse observed candidate
        scores and do not replay cache population.
      </p>

      {isSweepOpen && (
        <div className="mt-4 grid gap-4 sm:grid-cols-3" id="benchmark-sweep-controls">
          <label className="block">
            <span className="ui-label text-(--text-muted)">Sweep start</span>
            <input
              aria-label="Threshold sweep start"
              className={BENCHMARK_CONTROL_CLASS}
              disabled={isRunning}
              max="1"
              min="0"
              step="0.01"
              type="number"
              value={form.sweepStart}
              onChange={(event) =>
                updateBenchmarkForm(controller, {
                  sweepStart: benchmarkNumberValue(event.target.value, form.sweepStart),
                })
              }
            />
          </label>

          <label className="block">
            <span className="ui-label text-(--text-muted)">Sweep end</span>
            <input
              aria-label="Threshold sweep end"
              className={BENCHMARK_CONTROL_CLASS}
              disabled={isRunning}
              max="1"
              min="0"
              step="0.01"
              type="number"
              value={form.sweepEnd}
              onChange={(event) =>
                updateBenchmarkForm(controller, {
                  sweepEnd: benchmarkNumberValue(event.target.value, form.sweepEnd),
                })
              }
            />
          </label>

          <label className="block">
            <span className="ui-label text-(--text-muted)">Sweep step</span>
            <input
              aria-describedby="benchmark-sweep-status"
              aria-label="Threshold sweep step"
              className={BENCHMARK_CONTROL_CLASS}
              disabled={isRunning}
              max="1"
              min="0.01"
              step="0.01"
              type="number"
              value={form.sweepStep}
              onChange={(event) =>
                updateBenchmarkForm(controller, {
                  sweepStep: benchmarkNumberValue(event.target.value, form.sweepStep),
                })
              }
            />
          </label>
        </div>
      )}

      <output
        aria-live="polite"
        className={`font-data mt-3 block text-[10px]/5 ${
          sweep.error === null ? 'text-(--text-faint)' : 'text-(--coral-text)'
        }`}
        id="benchmark-sweep-status"
      >
        {sweep.error ??
          `Explicit list: ${sweep.thresholds
            .map((threshold) => formatDecimal(threshold, 2))
            .join(', ')}`}
      </output>

      {!canRun && (
        <p
          className="font-data mt-3 text-[10px]/5 text-(--coral-text)"
          id="benchmark-run-permission"
        >
          Viewer access can inspect dataset metadata, but Operator access is required to
          initiate provider-backed evaluation runs.
        </p>
      )}
    </div>
  );
}
