import { useMemo, type JSX } from 'react';

import { useAuth } from '@/features/auth/hooks/useAuth';

import type {
  BenchmarkController,
  BenchmarkForm,
} from '@/features/benchmark/hooks/useBenchmark';
import { BenchmarkDatasetImport } from '../datasets/BenchmarkDatasetImport';
import { BENCHMARK_CONTROL_CLASS, updateBenchmarkForm } from './benchmarkControlShared';

interface BenchmarkDatasetControlsProps {
  controller: BenchmarkController;
}

export function BenchmarkDatasetControls({
  controller,
}: Readonly<BenchmarkDatasetControlsProps>): JSX.Element {
  const auth = useAuth();
  const authorizedNamespaces = useMemo(
    () => auth.session?.namespaces.filter((item) => item !== '*') ?? [],
    [auth.session],
  );
  const hasGlobalNamespace = auth.session?.namespaces.includes('*') ?? false;
  const {
    datasets,
    datasetsLoading,
    form,
    historyNamespaceRequired,
    historyNamespaceValid,
    isRunning,
  } = controller;

  let historyNamespaceControl: JSX.Element;

  if (
    auth.status === 'authenticated' &&
    !hasGlobalNamespace &&
    authorizedNamespaces.length === 1
  ) {
    historyNamespaceControl = (
      <span
        aria-label="Benchmark history namespace"
        className={`${BENCHMARK_CONTROL_CLASS} flex items-center`}
      >
        {authorizedNamespaces[0]}
      </span>
    );
  } else if (
    auth.status === 'authenticated' &&
    !hasGlobalNamespace &&
    authorizedNamespaces.length > 1
  ) {
    historyNamespaceControl = (
      <select
        aria-describedby="benchmark-history-namespace-guidance"
        aria-invalid={!historyNamespaceValid}
        aria-label="Benchmark history namespace"
        aria-required={historyNamespaceRequired}
        className={BENCHMARK_CONTROL_CLASS}
        disabled={isRunning}
        value={form.historyNamespace}
        onChange={(event) =>
          updateBenchmarkForm(controller, {
            historyNamespace: event.target.value,
          })
        }
      >
        <option value="">Choose a namespace</option>
        {authorizedNamespaces.map((namespace) => (
          <option key={namespace} value={namespace}>
            {namespace}
          </option>
        ))}
      </select>
    );
  } else {
    historyNamespaceControl = (
      <input
        aria-describedby="benchmark-history-namespace-guidance"
        aria-invalid={!historyNamespaceValid}
        aria-label="Benchmark history namespace"
        aria-required={historyNamespaceRequired}
        className={BENCHMARK_CONTROL_CLASS}
        disabled={isRunning}
        placeholder="Required for wildcard history retention"
        value={form.historyNamespace}
        onChange={(event) =>
          updateBenchmarkForm(controller, {
            historyNamespace: event.target.value,
          })
        }
      />
    );
  }

  let historyNamespaceGuidance: string;
  if (!historyNamespaceValid) {
    historyNamespaceGuidance =
      'Choose a concrete authorized namespace before reviewing this built-in run.';
  } else if (auth.status === 'disabled' || hasGlobalNamespace) {
    historyNamespaceGuidance =
      'Choose a concrete namespace for retained built-in history. The * marker grants authorization scope and is never stored as run ownership.';
  } else if (authorizedNamespaces.length === 1) {
    historyNamespaceGuidance =
      'Built-in runs inherit your sole authorized namespace automatically.';
  } else {
    historyNamespaceGuidance =
      'Choose one authorized namespace for retained built-in history.';
  }

  return (
    <>
      <fieldset className="sm:col-span-2 lg:col-span-3">
        <legend className="ui-label text-(--text-muted)">Dataset source</legend>
        <div className="font-data mt-3 flex flex-wrap gap-x-6 gap-y-3 text-xs text-(--text-soft)">
          <label className="flex min-h-11 items-center gap-3">
            <input
              checked={form.datasetSource === 'builtin'}
              className="size-5 accent-(--gold)"
              disabled={isRunning}
              name="evaluation-dataset-source"
              type="radio"
              onChange={() =>
                updateBenchmarkForm(controller, { datasetSource: 'builtin' })
              }
            />
            <span>Built-in dataset</span>
          </label>
          <label className="flex min-h-11 items-center gap-3">
            <input
              checked={form.datasetSource === 'custom'}
              className="size-5 accent-(--gold)"
              disabled={isRunning}
              name="evaluation-dataset-source"
              type="radio"
              onChange={() =>
                updateBenchmarkForm(controller, { datasetSource: 'custom' })
              }
            />
            <span>Custom JSON dataset</span>
          </label>
          {controller.persistedDataset !== null && (
            <label className="flex min-h-11 items-center gap-3">
              <input
                checked={form.datasetSource === 'persisted'}
                className="size-5 accent-(--gold)"
                disabled={isRunning}
                name="evaluation-dataset-source"
                type="radio"
                onChange={() =>
                  updateBenchmarkForm(controller, {
                    datasetSource: 'persisted',
                  })
                }
              />
              <span>Persisted dataset: {controller.persistedDataset.name}</span>
            </label>
          )}
        </div>
      </fieldset>

      <label className="block">
        <span className="ui-label text-(--text-muted)">Built-in dataset</span>

        <select
          aria-label="Benchmark dataset"
          className={BENCHMARK_CONTROL_CLASS}
          disabled={datasetsLoading || isRunning || form.datasetSource !== 'builtin'}
          value={form.datasetId}
          onChange={(event) =>
            updateBenchmarkForm(controller, {
              datasetId: event.target.value as BenchmarkForm['datasetId'],
            })
          }
        >
          {datasets.map((dataset) => (
            <option key={dataset.dataset_id} value={dataset.dataset_id}>
              {dataset.name} ({dataset.query_count})
            </option>
          ))}
        </select>
      </label>

      {form.datasetSource === 'builtin' && (
        <label className="block">
          <span className="ui-label text-(--text-muted)">History namespace</span>
          {historyNamespaceControl}
          <span
            className={`font-data mt-2 block text-[10px]/5 ${
              historyNamespaceValid ? 'text-(--text-faint)' : 'text-(--coral)'
            }`}
            id="benchmark-history-namespace-guidance"
          >
            {historyNamespaceGuidance}
          </span>
        </label>
      )}

      {form.datasetSource === 'custom' && (
        <div className="sm:col-span-2 lg:col-span-3">
          <BenchmarkDatasetImport controller={controller} />
        </div>
      )}
    </>
  );
}
